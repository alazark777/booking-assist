from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=4000)
    session_id: UUID | None = None
    client_message_id: UUID


class AppointmentDetails(BaseModel):
    id: str
    service: str
    location: str
    start_time: str
    timezone: str
    expires_at: str | None = None
    proposal_id: str | None = None


class ChatResponse(BaseModel):
    request_id: str
    session_id: str
    reply: str
    status: Literal["needs_input", "awaiting_confirmation", "booked", "answered"]
    proposal: AppointmentDetails | None = None
    booking: AppointmentDetails | None = None
    trace_id: str | None = None


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str


class HealthResponse(BaseModel):
    status: str
