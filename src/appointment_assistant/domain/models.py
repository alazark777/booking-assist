from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


class DomainError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class Principal:
    id: str


@dataclass(frozen=True)
class Slot:
    id: str
    service: str
    location: str
    starts_at: datetime
    timezone: str
    duration_minutes: int = 30


@dataclass(frozen=True)
class Proposal:
    id: str
    principal_id: str
    session_id: str
    slot: Slot
    expires_at: datetime
    revision: int
    status: str
    approved_message_id: str | None = None


@dataclass(frozen=True)
class Booking:
    id: str
    proposal_id: str
    principal_id: str
    slot: Slot
    created_at: datetime
