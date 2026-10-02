from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from appointment_assistant.adapters.database import check_database, create_engine_and_sessionmaker
from appointment_assistant.adapters.google_client import GoogleGeminiClient, LLMClient
from appointment_assistant.adapters.mock_scheduler import MockScheduler
from appointment_assistant.adapters.repositories import ConversationStore, utc_now
from appointment_assistant.agent.service import AgentService, ChatService
from appointment_assistant.agent.tools import ToolDispatcher
from appointment_assistant.api.routes import error_response, router
from appointment_assistant.config import Settings, get_settings
from appointment_assistant.domain.models import DomainError
from appointment_assistant.observability import (
    LangfuseTelemetry,
    configure_logging,
    configure_tracing,
    tracer,
)

logger = logging.getLogger(__name__)


def load_system_prompt() -> str:
    return (Path(__file__).parent / "agent" / "prompts" / "system.md").read_text(encoding="utf-8")


def create_app(
    settings: Settings | None = None,
    *,
    llm: LLMClient | None = None,
    database_url: str | None = None,
    create_tables: bool = False,
) -> FastAPI:
    settings = settings or get_settings()
    if llm is None:
        settings.validate_runtime(require_google=True)
        assert settings.google_api_key
        llm = GoogleGeminiClient(settings.google_api_key.get_secret_value(), settings.google_model, settings.model_timeout_seconds)
    engine, session_factory = create_engine_and_sessionmaker(database_url or settings.database_url)
    store = ConversationStore(session_factory, utc_now)
    scheduler = MockScheduler(store, settings.booking_writes_enabled)
    configure_tracing(settings.otel_exporter_otlp_endpoint)
    telemetry = LangfuseTelemetry(settings)
    agent = AgentService(
        llm, ToolDispatcher(scheduler), load_system_prompt(), settings.max_model_requests,
        settings.max_tool_calls, settings.max_output_tokens, telemetry,
    )
    chat_service = ChatService(store, agent, utc_now, settings.turn_deadline_seconds, telemetry)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging()
        if create_tables:
            from appointment_assistant.adapters.database import create_schema

            await create_schema(engine)
        yield
        telemetry.shutdown()
        await llm.close()
        await engine.dispose()

    app = FastAPI(title="Appointment Assistant", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.store = store
    app.state.chat_service = chat_service
    app.state.store_ready = lambda: check_database(engine)
    app.include_router(router)

    @app.middleware("http")
    async def request_span(request: Request, call_next):
        with tracer.start_as_current_span("appointment.http_request") as span:
            span.set_attribute("http.route", request.url.path)
            response = await call_next(request)
            span.set_attribute("http.status_code", response.status_code)
            return response

    @app.exception_handler(DomainError)
    async def handle_domain_error(request: Request, exc: DomainError):
        return error_response(request, exc)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"code": "invalid_request", "message": "The request is invalid.", "request_id": request.headers.get("x-request-id", "unknown")})

    return app


app = create_app()
