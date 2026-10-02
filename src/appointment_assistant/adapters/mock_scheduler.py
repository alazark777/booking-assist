from __future__ import annotations

from dataclasses import asdict

from appointment_assistant.domain.models import Principal

from .repositories import ConversationStore


class MockScheduler:
    """Narrow scheduler boundary. Replace this adapter without changing agent or HTTP code."""

    def __init__(self, store: ConversationStore, booking_writes_enabled: bool = True):
        self.store = store
        self.booking_writes_enabled = booking_writes_enabled

    async def search_slots(self, service: str, preferred_date: str, time_preference: str) -> list[dict]:
        slots = await self.store.search_slots(service, preferred_date, time_preference)
        return [asdict(slot) | {"starts_at": slot.starts_at.isoformat()} for slot in slots]

    async def prepare_booking(self, principal: Principal, session_id: str, slot_id: str) -> dict:
        proposal = await self.store.make_proposal(principal, session_id, slot_id)
        return {
            "proposal_id": proposal.id,
            "service": proposal.slot.service,
            "location": proposal.slot.location,
            "start_time": proposal.slot.starts_at.isoformat(),
            "timezone": proposal.slot.timezone,
            "expires_at": proposal.expires_at.isoformat(),
        }

    async def create_booking(self, principal: Principal, session_id: str, proposal_id: str) -> dict:
        booking = await self.store.create_booking(principal, session_id, proposal_id, self.booking_writes_enabled)
        return {
            "booking_id": booking.id,
            "proposal_id": booking.proposal_id,
            "service": booking.slot.service,
            "location": booking.slot.location,
            "start_time": booking.slot.starts_at.isoformat(),
            "timezone": booking.slot.timezone,
        }
