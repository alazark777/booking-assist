from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed runtime configuration. Secrets are never included in repr/log output."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    google_api_key: SecretStr | None = Field(default=None, alias="GOOGLE_API_KEY")
    google_model: str = Field(default="gemini-3.8-flash", alias="GOOGLE_MODEL")
    database_url: str = Field(
        default="postgresql+asyncpg://appointment:appointment@localhost:5432/appointment_assistant",
        alias="DATABASE_URL",
    )
    service_credentials: str = Field(
        default="alice-token=customer-a,bob-token=customer-b", alias="SERVICE_CREDENTIALS"
    )
    app_env: str = Field(default="local", alias="APP_ENV")
    max_model_requests: int = Field(default=4, alias="MAX_MODEL_REQUESTS", ge=1, le=4)
    max_tool_calls: int = Field(default=4, alias="MAX_TOOL_CALLS", ge=1, le=4)
    turn_deadline_seconds: float = Field(default=90.0, alias="TURN_DEADLINE_SECONDS", gt=0, le=120)
    model_timeout_seconds: float = Field(default=55.0, alias="MODEL_TIMEOUT_SECONDS", gt=0, le=60)
    max_output_tokens: int = Field(default=800, alias="MAX_OUTPUT_TOKENS", ge=100, le=4096)
    otel_exporter_otlp_endpoint: str | None = Field(default=None, alias="OTEL_EXPORTER_OTLP_ENDPOINT")
    langfuse_tracing_enabled: bool = Field(default=False, alias="LANGFUSE_TRACING_ENABLED")
    langfuse_public_key: SecretStr | None = Field(default=None, alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: SecretStr | None = Field(default=None, alias="LANGFUSE_SECRET_KEY")
    langfuse_base_url: str = Field(default="https://cloud.langfuse.com", alias="LANGFUSE_BASE_URL")
    langfuse_environment: str = Field(default="local", alias="LANGFUSE_TRACING_ENVIRONMENT")
    langfuse_capture_content: bool = Field(default=False, alias="LANGFUSE_CAPTURE_CONTENT")
    booking_writes_enabled: bool = Field(default=True, alias="BOOKING_WRITES_ENABLED")

    @field_validator("google_model")
    @classmethod
    def model_is_safe_name(cls, value: str) -> str:
        if not value.strip() or any(ch.isspace() for ch in value):
            raise ValueError("GOOGLE_MODEL must be a non-empty model name")
        return value.strip()

    def credential_map(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for item in self.service_credentials.split(","):
            if not item.strip() or "=" not in item:
                raise ValueError("SERVICE_CREDENTIALS must contain comma-separated token=principal pairs")
            token, principal = item.split("=", 1)
            if not token or not principal:
                raise ValueError("SERVICE_CREDENTIALS contains an empty token or principal")
            result[token] = principal
        if not result:
            raise ValueError("At least one service credential is required")
        return result

    def validate_runtime(self, *, require_google: bool = True) -> None:
        self.credential_map()
        if require_google and not self.google_api_key:
            raise ValueError("GOOGLE_API_KEY is required for the real Gemini service")


@lru_cache
def get_settings() -> Settings:
    return Settings()
