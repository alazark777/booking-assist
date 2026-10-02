from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from appointment_assistant.adapters.mock_scheduler import MockScheduler
from appointment_assistant.domain.models import DomainError, Principal


class SearchSlotsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service: str = Field(min_length=1, max_length=60)
    preferred_date: date
    time_preference: str = Field(min_length=1, max_length=60)


class PrepareBookingArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slot_id: str = Field(min_length=1, max_length=100)


class CreateBookingArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_id: str = Field(min_length=1, max_length=36)


TOOL_DEFINITIONS = [
    {
        "name": "search_slots",
        "description": "Find currently available synthetic appointment slots for a supported service and date.",
        "parameters": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "enum": ["consultation", "cleaning"]},
                "preferred_date": {"type": "string", "description": "Calendar date in YYYY-MM-DD format."},
                "time_preference": {"type": "string", "description": "Customer's time constraint, such as after 17:00."},
            },
            "required": ["service", "preferred_date", "time_preference"],
            "additionalProperties": False,
        },
    },
    {
        "name": "prepare_booking",
        "description": "Prepare an exact appointment proposal. This never books or reserves the slot.",
        "parameters": {
            "type": "object",
            "properties": {"slot_id": {"type": "string"}},
            "required": ["slot_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_booking",
        "description": "Create the appointment only after the application has recorded exact customer approval.",
        "parameters": {
            "type": "object",
            "properties": {"proposal_id": {"type": "string"}},
            "required": ["proposal_id"],
            "additionalProperties": False,
        },
    },
]


class ToolDispatcher:
    def __init__(self, scheduler: MockScheduler):
        self.scheduler = scheduler

    async def dispatch(self, name: str, args: dict[str, Any], principal: Principal, session_id: str) -> dict[str, Any]:
        try:
            if name == "search_slots":
                search_args = SearchSlotsArgs.model_validate(args)
                if search_args.service not in {"consultation", "cleaning"}:
                    raise DomainError("unsupported_service", "That service is not supported.", 422)
                return {"slots": await self.scheduler.search_slots(search_args.service, search_args.preferred_date.isoformat(), search_args.time_preference)}
            if name == "prepare_booking":
                prepare_args = PrepareBookingArgs.model_validate(args)
                return await self.scheduler.prepare_booking(principal, session_id, prepare_args.slot_id)
            if name == "create_booking":
                create_args = CreateBookingArgs.model_validate(args)
                return await self.scheduler.create_booking(principal, session_id, create_args.proposal_id)
            raise DomainError("unknown_tool", "The requested operation is not available.", 400)
        except DomainError:
            raise
        except Exception as exc:
            raise DomainError("invalid_tool_arguments", "The requested operation had invalid arguments.", 422) from exc
