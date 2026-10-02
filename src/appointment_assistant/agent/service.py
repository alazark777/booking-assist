from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from appointment_assistant.adapters.google_client import (
    FunctionCall,
    LLMClient,
    ModelTurn,
    ProviderError,
)
from appointment_assistant.adapters.repositories import ConversationStore
from appointment_assistant.domain.models import DomainError, Principal
from appointment_assistant.observability import LangfuseTelemetry, tracer

from .tools import TOOL_DEFINITIONS, ToolDispatcher


@dataclass
class AgentResult:
    reply: str
    tool_calls: list[str]
    usage: dict[str, int]


class AgentService:
    def __init__(
        self,
        llm: LLMClient,
        dispatcher: ToolDispatcher,
        system_prompt: str,
        max_requests: int,
        max_tools: int,
        max_output_tokens: int,
        telemetry: LangfuseTelemetry | None = None,
    ):
        self.llm = llm
        self.dispatcher = dispatcher
        self.system_prompt = system_prompt
        self.max_requests = max_requests
        self.max_tools = max_tools
        self.max_output_tokens = max_output_tokens
        self.telemetry = telemetry or LangfuseTelemetry()

    async def run(self, principal: Principal, session_id: str, history: list[tuple[str, str]], message: str) -> AgentResult:
        contents: list[Any] = list(history) + [("user", message)]
        tool_calls: list[str] = []
        usage: dict[str, int] = {}
        for turn in range(self.max_requests):
            with tracer.start_as_current_span("appointment.model_call") as span:
                with self.telemetry.model_generation(
                    getattr(self.llm, "model", "google-gemini"), turn + 1, message
                ) as generation:
                    response: ModelTurn = await self.llm.generate(
                        contents, self.system_prompt, TOOL_DEFINITIONS, self.max_output_tokens
                    )
                    self.telemetry.update(
                        generation,
                        output=(
                            {"text": response.text, "function_call_count": len(response.function_calls)}
                            if self.telemetry.capture_content
                            else {"function_call_count": len(response.function_calls)}
                        ),
                        usage_details={
                            "input_tokens": (response.usage or {}).get("prompt_tokens", 0),
                            "output_tokens": (response.usage or {}).get("output_tokens", 0),
                            "total_tokens": (response.usage or {}).get("total_tokens", 0),
                        },
                    )
                span.set_attribute("tool_call_count", len(response.function_calls))
            if response.usage:
                for key, value in response.usage.items():
                    usage[key] = usage.get(key, 0) + value
            if response.model_content is not None:
                contents.append(response.model_content)
            if not response.function_calls:
                return AgentResult(response.text.strip() or "I could not produce a response. Please try again.", tool_calls, usage)
            if len(tool_calls) + len(response.function_calls) > self.max_tools:
                raise DomainError("execution_limit", "This request reached the tool-call limit; please start again.", 503)
            for call in response.function_calls:
                tool_calls.append(call.name)
                try:
                    with tracer.start_as_current_span("appointment.tool_call") as span:
                        span.set_attribute("tool.name", call.name)
                        with self.telemetry.tool_call(call.name, call.args) as observation:
                            result = await self.dispatcher.dispatch(call.name, call.args, principal, session_id)
                            self.telemetry.update(
                                observation,
                                output=result
                                if self.telemetry.capture_content
                                else {"result_keys": sorted(result)},
                            )
                except DomainError as exc:
                    result = {"error": {"code": exc.code, "message": exc.message}}
                contents.append(self._tool_response(call, result))
        raise DomainError("execution_limit", "This request reached the model-call limit; please try again.", 503)

    @staticmethod
    def _tool_response(call: FunctionCall, result: dict[str, Any]) -> Any:
        try:
            from google.genai import types

            return types.Content(
                role="tool",
                parts=[
                    types.Part(
                        function_response=types.FunctionResponse(
                            id=call.call_id, name=call.name, response={"result": result}
                        )
                    )
                ],
            )
        except ImportError:
            return ("user", json.dumps({"tool": call.name, "result": result}))


class ChatService:
    def __init__(
        self,
        store: ConversationStore,
        agent: AgentService,
        clock,
        deadline_seconds: float,
        telemetry: LangfuseTelemetry | None = None,
    ):
        self.store = store
        self.agent = agent
        self.clock = clock
        self.deadline_seconds = deadline_seconds
        self.telemetry = telemetry or LangfuseTelemetry()

    async def handle(self, principal: Principal, message: str, session_id: str | None, client_message_id: str) -> dict[str, Any]:
        replay = await self.store.idempotent_response(principal.id, client_message_id, message, session_id)
        if replay is not None:
            return replay
        session = await self.store.get_or_create_session(principal, session_id)
        if not await self.store.claim_turn(session.id, principal.id):
            raise DomainError("turn_conflict", "Another message is already being processed for this conversation.", 409)
        try:
            with self.telemetry.conversation(principal.id, session.id, message) as observation:
                return await self._handle_claimed_turn(
                    principal, session.id, message, client_message_id, observation
                )
        finally:
            await self.store.release_turn(session.id)

    async def _handle_claimed_turn(
        self,
        principal: Principal,
        session_id: str,
        message: str,
        client_message_id: str,
        observation: Any | None,
    ) -> dict[str, Any]:
        try:
            history = await self.store.conversation(session_id, principal.id)
            await self.store.append_message(session_id, principal.id, "user", message, client_message_id)
            from appointment_assistant.domain.booking import is_confirmation

            if is_confirmation(message):
                await self.store.approve_latest(principal, session_id, client_message_id)
            import asyncio

            result = await asyncio.wait_for(
                self.agent.run(principal, session_id, history, message), timeout=self.deadline_seconds
            )
            await self.store.append_message(session_id, principal.id, "assistant", result.reply)
            proposal = await self.store.latest_proposal(principal.id, session_id)
            booking = await self.store.booking_for_session(principal.id, session_id)
            response = {
                "request_id": str(uuid4()),
                "session_id": session_id,
                "reply": result.reply,
                "status": "booked" if booking else "awaiting_confirmation" if proposal else "needs_input" if "?" in result.reply else "answered",
                "proposal": proposal_to_dict(proposal) if proposal else None,
                "booking": booking_to_dict(booking) if booking else None,
                "tool_calls": result.tool_calls,
                "trace_id": self.telemetry.current_trace_id(),
            }
            self.telemetry.update(
                observation,
                output=response if self.telemetry.capture_content else {"status": response["status"]},
            )
            await self.store.save_idempotent_response(principal.id, client_message_id, response)
            return response
        except (ProviderError, TimeoutError, DomainError) as exc:
            # A tool may have committed a booking before the following model response failed.
            # Reconcile durable state before returning an error or claiming that nothing happened.
            booking = await self.store.booking_for_session(principal.id, session_id)
            if booking:
                fallback: dict[str, Any] = {
                    "request_id": str(uuid4()),
                    "session_id": session_id,
                    "reply": "Your appointment was booked. The model response was interrupted, so the stored booking details are the source of truth.",
                    "status": "booked",
                    "proposal": None,
                    "booking": booking_to_dict(booking),
                    "tool_calls": [],
                    "trace_id": self.telemetry.current_trace_id(),
                }
                self.telemetry.update(
                    observation,
                    output=fallback if self.telemetry.capture_content else {"status": "booked"},
                )
                await self.store.append_message(session_id, principal.id, "assistant", str(fallback["reply"]))
                await self.store.save_idempotent_response(principal.id, client_message_id, fallback)
                return fallback
            if isinstance(exc, ProviderError):
                raise DomainError(exc.code, exc.message, 502) from exc
            if isinstance(exc, TimeoutError):
                raise DomainError("turn_timeout", "The request exceeded its time limit; no new booking was assumed.", 504) from exc
            raise


def proposal_to_dict(proposal) -> dict[str, str]:
    return {
        "id": proposal.id,
        "service": proposal.slot.service,
        "location": proposal.slot.location,
        "start_time": proposal.slot.starts_at.isoformat(),
        "timezone": proposal.slot.timezone,
        "expires_at": proposal.expires_at.isoformat(),
    }


def booking_to_dict(booking) -> dict[str, str]:
    return {
        "id": booking.id,
        "proposal_id": booking.proposal_id,
        "service": booking.slot.service,
        "location": booking.slot.location,
        "start_time": booking.slot.starts_at.isoformat(),
        "timezone": booking.slot.timezone,
    }
