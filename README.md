# Google Gemini Appointment Assistant

This is a small, runnable Python HTTP service for learning agent deployment. It uses a real Google
Gemini call and a PostgreSQL-backed synthetic scheduler. The scheduler is intentionally mocked; the
model call, authentication boundary, persistence, migrations, limits, and tests are real.

## Quick start

Requirements: Python 3.12+, `uv`, Docker, and a Google AI API key.

```bash
cp .env.example .env
# edit GOOGLE_API_KEY in .env
uv sync --dev
docker compose up --build
```

The API listens on `http://localhost:8000`. The demo bearer credentials are `alice-token` and
`bob-token`; these map server-side to synthetic principals and are not public authentication.

### Podman

On macOS, install Podman and initialize its Linux VM once. Podman requires this VM because the
containers run Linux. `podman compose` also needs an external Compose provider such as
`podman-compose`.

```bash
podman machine init --now       # first use only
podman machine start            # if the machine is stopped
podman compose version          # verify a Compose provider is installed
podman compose up --build
```

The same `compose.yaml` is used; no PostgreSQL-specific changes are needed. Stop it with:

```bash
podman compose down
```

The database is available to host-side integration tests at
`postgresql+asyncpg://appointment:appointment@127.0.0.1:5433/appointment_assistant`.

## Local setup

Start PostgreSQL, then run:

```bash
uv sync --dev
uv run alembic upgrade head
uv run python -m appointment_assistant.seed
uv run uvicorn appointment_assistant.main:app --reload
```

The service uses `GOOGLE_API_KEY` and `GOOGLE_MODEL` (default `gemini-3.8-flash`). The Google GenAI
SDK's async client is reused across requests and closed at shutdown. Do not commit `.env` or a real
key.

## Try the real conversation

Use fresh UUIDs for each request. The response's `session_id` and `proposal.id` are authoritative.

```bash
curl -s http://localhost:8000/v1/chat \
  -H 'Authorization: Bearer alice-token' -H 'Content-Type: application/json' \
  -d '{"message":"Find a consultation Downtown on October 6, 2026 after 17:00","session_id":null,"client_message_id":"11111111-1111-4111-8111-111111111111"}'
```

Continue with the returned session ID and select `S1` when the model presents it:

```bash
curl -s http://localhost:8000/v1/chat \
  -H 'Authorization: Bearer alice-token' -H 'Content-Type: application/json' \
  -d '{"message":"The 17:30 slot","session_id":"<session_id>","client_message_id":"22222222-2222-4222-8222-222222222222"}'
```

Then reply exactly `confirm` or `yes`, using a new client message ID:

```bash
curl -s http://localhost:8000/v1/chat \
  -H 'Authorization: Bearer alice-token' -H 'Content-Type: application/json' \
  -d '{"message":"confirm","session_id":"<session_id>","client_message_id":"33333333-3333-4333-8333-333333333333"}'
```

The application records approval before the next model call, and only the `create_booking` tool
can write a booking. Exact proposal and booking fields come from PostgreSQL, not model prose.

## Tests and evaluations

Offline tests inject a scripted fake LLM and never require or contact Google. PostgreSQL integration
tests are marked `postgres` and require the Compose database. Live behavioral evaluations are opt-in:

```bash
uv run pytest
DATABASE_URL=postgresql+asyncpg://appointment:appointment@127.0.0.1:5433/appointment_assistant uv run pytest -m postgres
GOOGLE_API_KEY=... uv run python evals/run_live.py --case-file evals/cases.jsonl
```

`evals/cases.jsonl` contains stateful expectations, not just expected sentences. Passing the small
suite is a smoke check, not production readiness.

## Design and boundaries

See [docs/architecture.md](docs/architecture.md) for the request flow, Google function-calling
protocol, persistence model, confirmation vocabulary, operational limits, documentation sources,
and replacements required before real scheduling use. The companion Streamlit client is in
`/Users/alk/Desktop/cc-data-science/Learning/book-assist-client`.

For a component-by-component explanation and change guide, see [docs/development.md](docs/development.md).

For hosted AI traces, see [docs/langfuse-cloud.md](docs/langfuse-cloud.md). Langfuse is optional and
disabled until credentials are added.
