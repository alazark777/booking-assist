from __future__ import annotations

from datetime import UTC, datetime

from .models import DomainError, Proposal


def is_confirmation(message: str) -> bool:
    return message.strip().casefold() in {"confirm", "yes"}


def validate_proposal_for_booking(
    proposal: Proposal,
    principal_id: str,
    session_id: str,
    now: datetime,
    booking_writes_enabled: bool,
) -> None:
    if proposal.principal_id != principal_id or proposal.session_id != session_id:
        raise DomainError("proposal_not_owned", "That appointment proposal is not available in this session.", 403)
    if proposal.status != "active":
        raise DomainError("proposal_not_active", "That appointment proposal is no longer active.")
    expires_at = proposal.expires_at.replace(tzinfo=UTC) if proposal.expires_at.tzinfo is None else proposal.expires_at
    if expires_at <= now.astimezone(UTC):
        raise DomainError("proposal_expired", "The appointment proposal expired; please choose a slot again.")
    if not proposal.approved_message_id:
        raise DomainError("confirmation_required", "The customer must explicitly confirm this appointment first.")
    if not booking_writes_enabled:
        raise DomainError("booking_disabled", "Booking is temporarily disabled; no appointment was created.", 503)
