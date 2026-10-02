# Developer Guide

This guide explains how the appointment assistant fits together and where to make changes.

## Start here

- [README.md](../README.md): setup, Docker/local commands, and curl walkthrough.
- [architecture.md](architecture.md): design decisions, persistence, security, recovery, and limitations.
- `src/appointment_assistant/agent/prompts/system.md`: model behavior and confirmation rules.
- `tests/`: offline software tests using fakes.
- `evals/cases.jsonl`: opt-in behavioral evaluation cases.

## High-level request flow

```text
HTTP request
  -> bearer authentication
  -> request validation and idempotency
  -> session ownership and turn claim
  -> Google Gemini model call
       -> search_slots
       -> prepare_booking
       -> exact customer confirmation recorded by application
       -> create_booking
  -> trusted proposal/booking response
```

The model chooses when to ask questions or call a tool. Application code remains authoritative for
identity, ownership, approval, expiry, availability, and writes.

## Components

### `main.py`

Application factory and lifespan. It constructs the database engine, repository, scheduler, tool
dispatcher, Google client, and agent service. It also closes shared resources during shutdown.

### `config.py`

Typed environment configuration. The important settings are:

- `GOOGLE_API_KEY`: required for the real model client.
- `GOOGLE_MODEL`: defaults to `gemini-3.8-flash`.
- `DATABASE_URL`: PostgreSQL connection string.
- `SERVICE_CREDENTIALS`: demo bearer-token-to-principal mapping.
- Model/tool/deadline limits and the booking-write kill switch.

### `api/`

- `routes.py`: HTTP endpoints and response mapping.
- `schemas.py`: public request/response validation.
- `dependencies.py`: maps a bearer token to a synthetic principal.

The main endpoint is `POST /v1/chat`. There is deliberately no separate confirmation endpoint;
confirmation is part of the same conversation.

### `agent/`

- `service.py`: bounded model/tool loop and conversation continuation.
- `tools.py`: allowlisted Gemini tool declarations, Pydantic argument validation, and dispatch.
- `prompts/system.md`: version-controlled behavioral instructions.

The loop preserves the model's function-call content, executes only registered Python handlers,
returns function responses, and continues until the model produces text. It allows at most four
model requests and four tool calls per turn.

### `adapters/google_client.py`

The only Google-specific layer. It creates the async `google-genai` client, sends Gemini requests,
extracts function calls and usage, maps provider failures to safe application errors, and closes
the client at shutdown. Replacing Gemini should primarily affect this adapter and configuration.

### `adapters/database.py`

SQLAlchemy async engine, session factory, and persistence models. PostgreSQL is the deployment
database. SQLite is useful only for lightweight local smoke checks; PostgreSQL integration tests
are marked separately.

### `adapters/repositories.py`

Durable state operations for sessions, messages, idempotency records, slots, proposals, and
bookings. Database uniqueness constraints protect proposal replay and slot double-booking across
processes.

### `adapters/mock_scheduler.py`

The scheduler boundary. It exposes availability, proposal preparation, and booking creation to the
agent without exposing SQLAlchemy details. A real scheduling integration should replace this
adapter while preserving the agent and HTTP layers.

### `domain/`

- `models.py`: provider-independent domain values and errors.
- `booking.py`: exact confirmation vocabulary and booking preconditions.

The accepted confirmation messages are only standalone `confirm` or `yes`, ignoring case and
surrounding whitespace. The application records approval before the model receives the message.

### `observability.py`

Configures JSON stdout logs and OpenTelemetry request, model, and tool spans. It intentionally does
not log full prompts, conversations, credentials, or customer details by default. When
`LANGFUSE_TRACING_ENABLED=true` and valid Cloud credentials are supplied, it also emits an
`appointment-chat` trace with nested Gemini generations and scheduler tool observations. Set
`LANGFUSE_CAPTURE_CONTENT=true` only when prompt and response content should be retained. See
[Langfuse Cloud setup](langfuse-cloud.md).

## Booking state machine

```text
No proposal
  -> search_slots
  -> prepare_booking
Active proposal, unapproved
  -> exact "confirm" or "yes"
Active proposal, approved
  -> create_booking
Booked
```

Changing preferences creates a replacement proposal and invalidates the previous approval. Expired,
unowned, unavailable, or unapproved proposals cannot be booked.

## Persistence setup

```bash
cp .env.example .env
uv sync --dev
docker compose up -d db
uv run alembic upgrade head
uv run python -m appointment_assistant.seed
uv run uvicorn appointment_assistant.main:app --reload
```

Use `alembic upgrade head` for schema changes. Keep synthetic availability seeding repeatable;
`python -m appointment_assistant.seed` inserts missing slots and does not overwrite bookings.

### Podman PostgreSQL

The service uses the same `compose.yaml` with Podman. On macOS, Podman runs containers inside a
managed Linux VM, so initialize/start that VM before using Compose:

```bash
podman machine init --now
podman compose version
podman compose up --build
```

The Compose file publishes PostgreSQL on host port `5433` for integration testing. After the stack
is healthy, run the PostgreSQL test from the host:

```bash
DATABASE_URL=postgresql+asyncpg://appointment:appointment@127.0.0.1:5433/appointment_assistant \
  uv run pytest -m postgres
```

## How to make common changes

### Add or change a supported service

Update the allowlist and tool schema in `agent/tools.py`, update the prompt, add synthetic slots in
`seed.py`, then add offline and behavioral tests.

### Change booking rules

Put the enforcement in `domain/booking.py` or the repository transaction. Update the prompt only
to explain the rule; never rely on prompt text as the security boundary.

### Replace the scheduler

Implement the narrow methods represented by `MockScheduler`, preserve the trusted principal and
session arguments, and keep booking idempotency and authorization in application code.

### Change the model provider

Implement the `LLMClient` protocol in a new adapter, preserve the `ModelTurn` contract, and update
configuration and dependency documentation. Do not move tool authorization into the provider
adapter.

## Verification commands

```bash
uv run ruff check .
uv run mypy src
uv run pytest
uv run pytest -m postgres
GOOGLE_API_KEY=... uv run python evals/run_live.py --case-file evals/cases.jsonl
```

The live evaluator is intentionally opt-in. Passing offline tests or the small evaluation suite is
not evidence of production readiness; use the acceptance checklist for the broader release review.
