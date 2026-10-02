from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from appointment_assistant.api.dependencies import current_principal
from appointment_assistant.api.schemas import ChatRequest, ChatResponse, ErrorBody, HealthResponse
from appointment_assistant.domain.models import DomainError, Principal
from appointment_assistant.observability import request_id

router = APIRouter()


@router.post("/v1/chat", response_model=ChatResponse)
async def chat(
    request: Request,
    body: ChatRequest,
    response: Response,
    principal: Principal = Depends(current_principal),
):
    result = await request.app.state.chat_service.handle(
        principal, body.message, str(body.session_id) if body.session_id else None, str(body.client_message_id)
    )
    if result.get("trace_id"):
        response.headers["X-Trace-Id"] = result["trace_id"]
    result.pop("tool_calls", None)
    return result


@router.get("/health/live", response_model=HealthResponse)
async def live() -> HealthResponse:
    return HealthResponse(status="live")


@router.get("/health/ready", response_model=HealthResponse)
async def ready(request: Request):
    if not await request.app.state.store_ready():
        return JSONResponse(status_code=503, content={"status": "not_ready"})
    return HealthResponse(status="ready")


def error_response(request: Request, exc: DomainError) -> JSONResponse:
    rid = request.headers.get("x-request-id") or request_id()
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorBody(code=exc.code, message=exc.message, request_id=rid).model_dump(),
    )
