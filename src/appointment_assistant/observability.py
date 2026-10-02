from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import ProxyTracerProvider

tracer = trace.get_tracer("appointment-assistant")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": time.time(),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            **getattr(record, "fields", {}),
        }
        return json.dumps(payload, separators=(",", ":"))


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def configure_tracing(endpoint: str | None) -> None:
    # Langfuse's Python SDK may already have installed a provider. OpenTelemetry
    # permits only one global provider, so never overwrite an initialized one.
    if not isinstance(trace.get_tracer_provider(), ProxyTracerProvider):
        return
    provider = TracerProvider(resource=Resource.create({"service.name": "appointment-assistant"}))
    if endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)


class LangfuseTelemetry:
    """Optional Langfuse Cloud instrumentation for one conversation turn."""

    def __init__(self, settings=None) -> None:
        self.client: Any | None = None
        self.capture_content = bool(getattr(settings, "langfuse_capture_content", False))
        self.environment = getattr(settings, "langfuse_environment", "local")
        if settings is None or not getattr(settings, "langfuse_tracing_enabled", False):
            return
        public_key = getattr(settings, "langfuse_public_key", None)
        secret_key = getattr(settings, "langfuse_secret_key", None)
        public_value = public_key.get_secret_value() if public_key else ""
        secret_value = secret_key.get_secret_value() if secret_key else ""
        if not public_value or not secret_value:
            logging.getLogger(__name__).warning(
                "Langfuse tracing is enabled but credentials are missing; tracing is disabled"
            )
            return
        from langfuse import Langfuse

        self.client = Langfuse(
            public_key=public_value,
            secret_key=secret_value,
            base_url=settings.langfuse_base_url,
            environment=settings.langfuse_environment,
            tracing_enabled=True,
        )

    @property
    def enabled(self) -> bool:
        return self.client is not None

    @contextmanager
    def conversation(self, principal_id: str, session_id: str, message: str) -> Iterator[Any | None]:
        if self.client is None:
            yield None
            return
        from langfuse import propagate_attributes

        root_input = (
            {"message": message}
            if self.capture_content
            else {"message_length": len(message), "content_capture": "disabled"}
        )
        with self.client.start_as_current_observation(
            as_type="agent", name="appointment-chat", input=root_input
        ) as root:
            with propagate_attributes(
                user_id=principal_id,
                session_id=session_id,
                environment=self.environment,
                metadata={"service": "appointment-assistant"},
                trace_name="appointment-chat",
            ):
                yield root

    @contextmanager
    def model_generation(self, model: str, turn: int, message: str) -> Iterator[Any | None]:
        if self.client is None:
            yield None
            return
        generation_input = (
            {"turn": turn, "message": message}
            if self.capture_content
            else {"turn": turn, "content_capture": "disabled"}
        )
        with self.client.start_as_current_observation(
            as_type="generation", name="google-gemini.generate", model=model, input=generation_input
        ) as generation:
            yield generation

    @contextmanager
    def tool_call(self, name: str, args: dict[str, Any]) -> Iterator[Any | None]:
        if self.client is None:
            yield None
            return
        tool_input = args if self.capture_content else {"argument_names": sorted(args)}
        with self.client.start_as_current_observation(
            as_type="tool", name=f"tool.{name}", input=tool_input
        ) as tool:
            yield tool

    def current_trace_id(self) -> str | None:
        if self.client is None:
            return None
        return self.client.get_current_trace_id()

    @staticmethod
    def update(observation: Any | None, **fields: Any) -> None:
        if observation is not None:
            observation.update(**fields)

    def shutdown(self) -> None:
        if self.client is not None:
            self.client.shutdown()


def request_id() -> str:
    return str(uuid4())


@contextmanager
def timed_log(logger: logging.Logger, event: str, **fields):
    started = time.perf_counter()
    try:
        yield
        fields["outcome"] = "success"
    except Exception as exc:
        fields["outcome"] = "error"
        fields["error_code"] = getattr(exc, "code", "internal_error")
        raise
    finally:
        fields["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
        logger.info(event, extra={"fields": fields})
