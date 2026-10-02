from datetime import datetime, timedelta, timezone

from appointment_assistant.domain.booking import is_confirmation, validate_proposal_for_booking
from appointment_assistant.domain.models import Proposal, Slot


def proposal(approved: str | None = "message") -> Proposal:
    slot = Slot("S1", "consultation", "Downtown", datetime.now(timezone.utc) + timedelta(days=1), "America/New_York")
    return Proposal("p1", "customer-a", "session", slot, datetime.now(timezone.utc) + timedelta(minutes=5), 1, "active", approved)


def test_only_standalone_confirmation_is_accepted():
    assert is_confirmation(" CONFIRM ")
    assert is_confirmation("yes")
    assert not is_confirmation("yes, but Friday instead")
    assert not is_confirmation("please confirm this")


def test_booking_requires_recorded_approval():
    try:
        validate_proposal_for_booking(proposal(None), "customer-a", "session", datetime.now(timezone.utc), True)
    except Exception as exc:
        assert exc.code == "confirmation_required"
    else:
        raise AssertionError("unapproved proposal was accepted")
