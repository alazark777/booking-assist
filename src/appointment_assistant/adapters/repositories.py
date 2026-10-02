from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from appointment_assistant.domain.models import Booking, DomainError, Principal, Proposal, Slot

from .database import (
    BookingRow,
    IdempotencyRow,
    MessageRow,
    ProposalRow,
    SessionRow,
    SlotRow,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def slot_from_row(row: SlotRow) -> Slot:
    return Slot(row.id, row.service, row.location, row.starts_at, row.timezone, row.duration_minutes)


class ConversationStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], clock=utc_now):
        self.sessions = session_factory
        self.clock = clock

    async def get_or_create_session(self, principal: Principal, requested_id: str | None) -> SessionRow:
        async with self.sessions() as db:
            row = None
            if requested_id:
                row = await db.get(SessionRow, requested_id)
                if row and row.principal_id != principal.id:
                    raise DomainError("session_not_owned", "That conversation is not available.", 403)
            if not row:
                row = SessionRow(id=requested_id or str(uuid4()), principal_id=principal.id, version=0)
                db.add(row)
                await db.commit()
            return row

    async def claim_turn(self, session_id: str, principal_id: str, lease_seconds: int = 45) -> bool:
        now = self.clock()
        until = now + timedelta(seconds=lease_seconds)
        async with self.sessions() as db:
            result = await db.execute(
                update(SessionRow)
                .where(
                    SessionRow.id == session_id,
                    SessionRow.principal_id == principal_id,
                    (SessionRow.turn_claimed_until.is_(None) | (SessionRow.turn_claimed_until < now)),
                )
                .values(turn_claimed_until=until, updated_at=now)
            )
            await db.commit()
            return getattr(result, "rowcount", 0) == 1

    async def release_turn(self, session_id: str) -> None:
        async with self.sessions() as db:
            await db.execute(update(SessionRow).where(SessionRow.id == session_id).values(turn_claimed_until=None))
            await db.commit()

    async def conversation(self, session_id: str, principal_id: str) -> list[tuple[str, str]]:
        async with self.sessions() as db:
            session = await db.get(SessionRow, session_id)
            if not session or session.principal_id != principal_id:
                raise DomainError("session_not_owned", "That conversation is not available.", 403)
            result = await db.execute(
                select(MessageRow).where(MessageRow.session_id == session_id).order_by(MessageRow.sequence)
            )
            return [(row.role, row.content) for row in result.scalars()]

    async def append_message(
        self, session_id: str, principal_id: str, role: str, content: str, client_message_id: str | None = None
    ) -> None:
        async with self.sessions() as db:
            max_seq = await db.scalar(
                select(MessageRow.sequence).where(MessageRow.session_id == session_id).order_by(MessageRow.sequence.desc()).limit(1)
            )
            db.add(
                MessageRow(
                    id=str(uuid4()),
                    session_id=session_id,
                    principal_id=principal_id,
                    sequence=(max_seq or 0) + 1,
                    role=role,
                    content=content,
                    client_message_id=client_message_id,
                )
            )
            await db.commit()

    async def idempotent_response(self, principal_id: str, client_message_id: str, message: str, session_id: str | None):
        payload = json.dumps({"message": message, "session_id": session_id}, sort_keys=True)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        async with self.sessions() as db:
            row = await db.scalar(
                select(IdempotencyRow).where(
                    IdempotencyRow.principal_id == principal_id,
                    IdempotencyRow.client_message_id == client_message_id,
                )
            )
            if row:
                if row.payload_hash != digest:
                    raise DomainError("idempotency_conflict", "client_message_id was already used for different content.", 409)
                return json.loads(row.response_json) if row.response_json else None
            db.add(IdempotencyRow(id=str(uuid4()), principal_id=principal_id, client_message_id=client_message_id, payload_hash=digest))
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
                return await self.idempotent_response(principal_id, client_message_id, message, session_id)
            return None

    async def save_idempotent_response(self, principal_id: str, client_message_id: str, response: dict) -> None:
        async with self.sessions() as db:
            await db.execute(
                update(IdempotencyRow)
                .where(IdempotencyRow.principal_id == principal_id, IdempotencyRow.client_message_id == client_message_id)
                .values(response_json=json.dumps(response))
            )
            await db.commit()

    async def search_slots(self, service: str, preferred_date: str, time_preference: str) -> list[Slot]:
        requested_date = date.fromisoformat(preferred_date)
        local_zone = ZoneInfo("America/New_York")
        start = datetime.combine(requested_date, time.min, tzinfo=local_zone)
        end = start + timedelta(days=1)
        async with self.sessions() as db:
            result = await db.execute(
                select(SlotRow)
                .where(SlotRow.service == service, SlotRow.starts_at >= start, SlotRow.starts_at < end)
                .order_by(SlotRow.starts_at)
            )
            booked = set((await db.execute(select(BookingRow.slot_id))).scalars())
            slots = [slot_from_row(row) for row in result.scalars() if row.available and row.id not in booked]
            preference = time_preference.casefold()
            if "after" in preference:
                match = re.search(r"(\d{1,2})(?::(\d{2}))?", preference)
                threshold = int(match.group(1)) * 60 + int(match.group(2) or 0) if match else 17 * 60
                slots = [slot for slot in slots if slot.starts_at.hour * 60 + slot.starts_at.minute >= threshold]
            return slots

    async def get_slot(self, slot_id: str) -> Slot | None:
        async with self.sessions() as db:
            row = await db.get(SlotRow, slot_id)
            return slot_from_row(row) if row else None

    async def make_proposal(self, principal: Principal, session_id: str, slot_id: str) -> Proposal:
        now = self.clock()
        async with self.sessions() as db:
            slot_row = await db.get(SlotRow, slot_id)
            booked = await db.scalar(select(BookingRow.id).where(BookingRow.slot_id == slot_id))
            if not slot_row or not slot_row.available or booked:
                raise DomainError("slot_unavailable", "That slot is no longer available; please search again.")
            await db.execute(
                update(ProposalRow).where(
                    ProposalRow.session_id == session_id,
                    ProposalRow.principal_id == principal.id,
                    ProposalRow.status == "active",
                ).values(status="superseded", approved_message_id=None)
            )
            latest = await db.scalar(
                select(ProposalRow.revision).where(ProposalRow.session_id == session_id).order_by(ProposalRow.revision.desc()).limit(1)
            )
            row = ProposalRow(
                id=str(uuid4()), principal_id=principal.id, session_id=session_id, slot_id=slot_id,
                expires_at=now + timedelta(minutes=5), revision=(latest or 0) + 1, status="active",
            )
            db.add(row)
            await db.commit()
            return Proposal(row.id, principal.id, session_id, slot_from_row(slot_row), row.expires_at, row.revision, row.status)

    async def latest_proposal(self, principal_id: str, session_id: str) -> Proposal | None:
        async with self.sessions() as db:
            row = await db.scalar(
                select(ProposalRow).where(
                    ProposalRow.principal_id == principal_id, ProposalRow.session_id == session_id,
                    ProposalRow.status == "active",
                ).order_by(ProposalRow.revision.desc()).limit(1)
            )
            if not row:
                return None
            slot = await db.get(SlotRow, row.slot_id)
            if not slot:
                return None
            return Proposal(row.id, row.principal_id, row.session_id, slot_from_row(slot), row.expires_at, row.revision, row.status, row.approved_message_id)

    async def approve_latest(self, principal: Principal, session_id: str, message_id: str) -> Proposal | None:
        now = self.clock()
        async with self.sessions() as db:
            row = await db.scalar(
                select(ProposalRow).where(
                    ProposalRow.principal_id == principal.id, ProposalRow.session_id == session_id,
                    ProposalRow.status == "active", ProposalRow.expires_at > now,
                ).order_by(ProposalRow.revision.desc()).limit(1)
            )
            if not row:
                return None
            row.approved_message_id = message_id
            await db.commit()
        return await self.latest_proposal(principal.id, session_id)

    async def create_booking(self, principal: Principal, session_id: str, proposal_id: str, writes_enabled: bool) -> Booking:
        from appointment_assistant.domain.booking import validate_proposal_for_booking

        async with self.sessions() as db:
            row = await db.get(ProposalRow, proposal_id)
            if not row:
                raise DomainError("proposal_not_found", "That appointment proposal was not found.", 404)
            slot_row = await db.get(SlotRow, row.slot_id)
            if not slot_row:
                raise DomainError("slot_not_found", "That appointment slot was not found.", 404)
            proposal = Proposal(row.id, row.principal_id, row.session_id, slot_from_row(slot_row), row.expires_at, row.revision, row.status, row.approved_message_id)
            validate_proposal_for_booking(proposal, principal.id, session_id, self.clock(), writes_enabled)
            existing = await db.scalar(select(BookingRow).where(BookingRow.proposal_id == proposal_id))
            if existing:
                return Booking(existing.id, proposal_id, existing.principal_id, proposal.slot, existing.created_at)
            conflicting = await db.scalar(select(BookingRow).where(BookingRow.slot_id == row.slot_id))
            if conflicting:
                raise DomainError("slot_unavailable", "That slot was just booked; please choose another.")
            booking_row = BookingRow(id=str(uuid4()), proposal_id=proposal_id, principal_id=principal.id, slot_id=row.slot_id)
            db.add(booking_row)
            try:
                await db.commit()
            except IntegrityError as exc:
                await db.rollback()
                existing = await db.scalar(select(BookingRow).where(BookingRow.proposal_id == proposal_id))
                if existing:
                    return Booking(existing.id, proposal_id, existing.principal_id, proposal.slot, existing.created_at)
                raise DomainError("slot_unavailable", "That slot was just booked; please choose another.") from exc
            return Booking(booking_row.id, proposal_id, principal.id, proposal.slot, booking_row.created_at or self.clock())

    async def booking_for_session(self, principal_id: str, session_id: str) -> Booking | None:
        async with self.sessions() as db:
            result = await db.execute(
                select(BookingRow, ProposalRow, SlotRow)
                .join(ProposalRow, ProposalRow.id == BookingRow.proposal_id)
                .join(SlotRow, SlotRow.id == BookingRow.slot_id)
                .where(BookingRow.principal_id == principal_id, ProposalRow.session_id == session_id)
                .order_by(BookingRow.created_at.desc()).limit(1)
            )
            row = result.first()
            if not row:
                return None
            booking, _, slot = row
            return Booking(booking.id, booking.proposal_id, principal_id, slot_from_row(slot), booking.created_at)

    async def seed_slots(self, slots: list[Slot]) -> int:
        inserted = 0
        async with self.sessions() as db:
            for slot in slots:
                if await db.get(SlotRow, slot.id):
                    continue
                db.add(SlotRow(id=slot.id, service=slot.service, location=slot.location, starts_at=slot.starts_at, timezone=slot.timezone, duration_minutes=slot.duration_minutes, available=True))
                inserted += 1
            await db.commit()
        return inserted
