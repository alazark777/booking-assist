# Codex Instructions: Build a Minimal Appointment Assistant Service

## Objective

Implement a small, runnable Python HTTP service that uses a **real LLM call and mocked scheduling tools**. This is the starting application for learning agent deployment and operations. Prioritize clear code boundaries, reproducible setup, and meaningful tests over feature breadth.

Build the implementation, not just a scaffold or architecture proposal. **Simplicity applies to the business task, not to engineering quality.** Use proper service boundaries, durable state, configuration, authentication, error handling, telemetry, tests, and packaging from the start. Only the scheduling integration is mocked; the model call and service infrastructure must work. Do not claim the service is ready for real customers merely because it runs.

## 1. Consult official documentation before implementation

Read the relevant current documentation, verify SDK signatures, and select compatible stable dependencies. Record the chosen versions and the documentation consulted in `docs/architecture.md`.

Use these starting points:

- [OpenAI Python SDK and libraries](https://developers.openai.com/api/docs/libraries)
- [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling)
- [FastAPI application organization](https://fastapi.tiangolo.com/tutorial/bigger-applications/)
- [FastAPI lifespan management](https://fastapi.tiangolo.com/advanced/events/)
- [Pydantic settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- [SQLAlchemy asynchronous I/O](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html) — follow the documentation matching the selected supported release.
- [Alembic migrations](https://alembic.sqlalchemy.org/en/latest/tutorial.html)

Use Python 3.12+, FastAPI, Pydantic, `pydantic-settings`, and the official asynchronous OpenAI Python client with the Responses API. Use `uv` with a committed lockfile, pytest, Ruff, and a type checker. Verify the selected Python version supports the resolved dependencies.

Use a small, explicit function-calling loop. For this scope, the official client is sufficient; an agent orchestration framework is unnecessary. Do not introduce LangChain, a graph framework, MCP, multiple agents, queues, a vector database, or a frontend. These are project scope decisions, not universal architectural rules.

Keep `OPENAI_MODEL` configurable. Choose and document one currently supported model with function calling after checking official documentation; do not invent a model identifier or silently switch models on failure.

## 2. Implement this limited behavior

The assistant helps a synthetic customer find and reserve a mock appointment:

1. Understand a natural-language request and ask for missing preferences.
2. Call a mocked availability tool.
3. Let the customer select a slot and prepare a booking proposal.
4. Return the exact proposed appointment for explicit confirmation.
5. Accept the customer's confirmation in the conversation; the agent then calls the mock booking tool and returns the result.

Support one location, two services, and a small set of synthetic slots. Include the location's time zone. Generate demo availability relative to an injected clock so the example does not become unusable when dates pass; freeze the clock in tests.

Exclude payments, notifications, cancellation, rescheduling, and human handoff integrations. Explain unsupported requests honestly. The earlier production checklist is future evaluation context, not a requirement to implement all business features in this first service.

The LLM follows a system prompt, interprets requests, asks questions, chooses tools, and explains their results. Application code validates tool requests and enforces identity, recorded approval, and booking constraints. Do not replace the agent with a hardcoded conversation flow or a separate booking-confirmation endpoint.

## 3. Code structure and responsibilities

Use a `src` package layout, with `__init__.py` files where appropriate. The following paths define responsibilities; avoid additional layers unless the implementation needs them.

| Path | Responsibility |
| --- | --- |
| `src/appointment_assistant/main.py` | App factory and lifespan: construct dependencies, open and close the shared LLM client, register routes. |
| `src/appointment_assistant/config.py` | Typed environment settings and startup validation. |
| `src/appointment_assistant/api/routes.py` | HTTP endpoints, status codes, and delegation to services. |
| `src/appointment_assistant/api/schemas.py` | Validated public request and response models. |
| `src/appointment_assistant/api/dependencies.py` | Resolve the authenticated synthetic principal and inject services. |
| `src/appointment_assistant/agent/service.py` | Bounded LLM/tool loop, conversation continuation, and tool dispatch. |
| `src/appointment_assistant/agent/tools.py` | Allowlisted tool definitions, argument validation, and thin tool handlers. |
| `src/appointment_assistant/agent/prompts/system.md` | Version-controlled instructions for the assistant. Include this resource in the installed package. |
| `src/appointment_assistant/domain/models.py` | Slots, proposals, bookings, and domain errors. |
| `src/appointment_assistant/domain/booking.py` | Proposal validation and deterministic booking confirmation rules. |
| `src/appointment_assistant/adapters/openai_client.py` | OpenAI-specific request/response handling, SDK errors, and usage extraction. |
| `src/appointment_assistant/adapters/mock_scheduler.py` | Synthetic availability and atomic mock booking operations. |
| `src/appointment_assistant/adapters/database.py` | Database engine, session factory, transaction lifecycle, and persistence models. |
| `src/appointment_assistant/adapters/repositories.py` | Durable sessions, proposals, approval records, idempotency records, and mock bookings. |
| `src/appointment_assistant/observability.py` | Structured logging and request correlation. |
| `tests/` | Offline unit and API integration tests, plus an explicitly opt-in live smoke test. |
| `evals/` | Small JSONL case set and an executable evaluation runner. |
| `docs/architecture.md` | Design choices, dependency responsibilities, sources, and limitations. |

Also provide migrations, `pyproject.toml`, `uv.lock`, `.env.example`, `.gitignore`, `.dockerignore`, `Dockerfile`, `compose.yaml`, `README.md`, and a CI workflow for offline checks.

Keep HTTP types out of domain logic and SDK calls out of route handlers. Inject the LLM client, scheduler, store, and clock so tests can replace them. Use small protocols only where substitution is needed; avoid a generic provider framework or a base class for every object.

## 4. Expose a clear service contract

| Endpoint | Contract |
| --- | --- |
| `POST /v1/chat` | Accept `{ "message": "...", "session_id": null, "client_message_id": "<UUID>" }` for a new conversation or an existing session ID. Return `request_id`, `session_id`, `reply`, `status`, and optional `proposal` and `booking` objects. Continue and confirm through this same endpoint. |
| `GET /health/live` | Return whether the process is running; no external calls. |
| `GET /health/ready` | Check required settings, database connectivity, and schema compatibility. Do not make a paid LLM request. Document that readiness does not establish provider availability. |

Use explicit chat statuses such as `needs_input`, `awaiting_confirmation`, `booked`, and `answered`. A proposal must contain its ID, service, location, start time with time zone, and expiry. Return a consistent error shape containing `code`, a safe `message`, and `request_id`. Scope message idempotency to the authenticated principal: replay the stored result for the same ID and payload, reject reuse with different content, and handle in-progress duplicates explicitly.

The client accepts only a user message, never caller-supplied system messages, tool results, or trusted conversation history. Keep continuation state on the server, scoped to its owner. Serialize turns for the same session to prevent state races; independent sessions can run concurrently.

## 5. Tools and confirmation boundary

Expose these three functions to the LLM:

- `search_slots(service, preferred_date, time_preference)`: return validated mock availability. Choose precise typed representations and document them.
- `prepare_booking(slot_id)`: validate the slot and create an expiring proposal for the current principal and session. This does **not** reserve the slot or create a booking.
- `create_booking(proposal_id)`: verify the proposal and its recorded approval, then atomically create or retrieve the mock booking.

The system prompt must tell the model to clarify missing preferences, use the tools rather than invent availability, present exact appointment details, ask for confirmation, and call `create_booking` only after approval. It must explain unsupported requests and failures honestly. Include a short successful conversation and a missing-information example in the prompt.

The proposal is immutable, expires after five minutes, and binds the exact slot, customer, session, and revision. A replacement proposal invalidates the previous active proposal and its approval. Return its authoritative details in the response and include them in the displayed confirmation question so the user sees what they are approving.

For this narrowly scoped task, ask the customer to reply with exactly `confirm` or `yes`. Application code recognizes only those standalone replies, ignoring surrounding whitespace and case, against the most recent unexpired proposal presented in that session. Record approval against that exact proposal and user message before the next model call. A reply such as “yes, but Friday instead” is not approval; the model handles the requested change and asks again. Other wording can be clarified conversationally. Document this intentionally narrow confirmation vocabulary.

The model still decides to call `create_booking`, but the tool verifies the persisted approval. Do not accept a model-supplied `confirmed=true` as evidence. This is an ordinary tool precondition, like verifying identity or slot availability; the prompt still governs the conversation. Test that a premature or malicious tool call is rejected.

Booking creation must recheck availability, verify ownership, and atomically create at most one booking. Repeated creation calls for an already-booked proposal return the same booking. Use the proposal ID as the mock operation's persistent idempotency key. Concurrent requests for the same slot must not produce two bookings, including when they use different proposals.

Return structured proposal and booking details from trusted application state, not by parsing the assistant's prose. The model explains the tool result; a factual booking receipt must use stored values. If a model call fails after a successful write, return the recorded booking and a clear fallback receipt rather than implying the write failed. Never silently substitute a fake LLM.

## 6. Implement the LLM loop correctly

- Use the official async client, reused across requests and closed at shutdown.
- Follow the Responses API's current function-call/output protocol, correlate outputs by call ID, and preserve required response items during continuation. Do not discard reasoning items required by the selected model or use them as application logs.
- Use strict tool schemas and validate arguments again in code. Reject unknown tool names and extra or invalid arguments.
- Dispatch only registered Python functions. Never execute model-generated code or import arbitrary modules from tool names.
- Treat user text and tool descriptions/results as untrusted instructions. Only application configuration defines tools and authority.
- Pass the principal through trusted application context, never as a model-selected customer ID.
- Bound each chat turn to at most four model requests and four tool calls. Enforce a 30-second application deadline and an output-token limit. These are initial configurable limits for this demo, not measured performance claims.
- Configure SDK timeout and retry behavior explicitly, accounting for it within the total deadline. Do not layer unbounded application retries on SDK retries. A failed turn must leave session state recoverable.
- Return safe errors for provider authentication failures, rate limits, timeouts, invalid tool outputs, and exhausted budgets. Do not expose credentials or raw upstream exception bodies.
- Set finite message, history, session-count, and session-lifetime limits. When a conversation is too long, return a clear restart instruction rather than silently losing confirmation-relevant state.

## 7. Build a deployable service foundation

Use PostgreSQL with SQLAlchemy's async APIs and Alembic migrations. Supply Docker Compose for the API and database. Persist conversation state, proposals, approvals, mock bookings, and message/booking idempotency records. Provide an explicit, repeatable command to seed synthetic availability without overwriting existing bookings. Use in-memory doubles only for unit tests.

Enforce uniqueness and booking conflicts in database transactions, not just process locks. Protect concurrent turns for the same session using a database-backed claim or version check; return a controlled conflict when appropriate. Do not hold database transactions open during model network calls. Explain how interrupted turns recover, including when a booking committed before the HTTP response was delivered. Keep the mock scheduler behind a narrow interface so replacing it with a real API does not change the agent or HTTP layer.

For the internal service baseline, authenticate environment-configured bearer credentials mapped server-side to synthetic principals. Reject missing or invalid credentials and verify resource ownership. Keep two synthetic principals for isolation tests. Separate authentication into a dependency that can later use the organization's identity provider. Do not implement a login system or imply that this is complete public-customer authentication.

Load `OPENAI_API_KEY`, `OPENAI_MODEL`, `DATABASE_URL`, service credentials, and limits through typed settings. Fail startup clearly when required configuration is absent. Commit placeholders only. Never echo secrets or bake them into the image.

Emit JSON logs to stdout with request ID, outcome, model/prompt version, model/tool latency, tool name, token usage when available, and safe error codes. Add request, model-call, and tool-call spans using OpenTelemetry with an environment-configurable exporter. Do not log or trace full prompts, conversations, credentials, or customer details by default. Log tool arguments only when explicitly allowlisted and safe. Bound inbound concurrency and handle saturation explicitly. Do not build a monitoring dashboard or operate a monitoring backend in this task.

Provide a reproducible container build from the lockfile, run as a non-root user, handle shutdown, and keep secrets and local artifacts out of the build context. Include local and Docker launch commands. Build and verify locally; cloud deployment is a later learning step.

## 8. Tests and evaluation

Offline tests must not need an API key or contact OpenAI. Inject a scripted fake LLM at the adapter boundary; the actual service runtime must use the real provider.

Test these meaningful behaviors:

1. A scripted tool-call response reaches the correct tool, and its result returns to the next model request with the matching call ID.
2. Preparing a proposal creates no booking; premature tool calls, changed preferences, stale approval, and expired or unowned proposals cannot create one.
3. Repeated and concurrent tool calls do not duplicate bookings or double-book a slot, including after restarting the API process.
4. One principal cannot access another's session or proposal.
5. Unknown tools, invalid arguments, timeouts, and execution limits produce controlled outcomes.
6. Health endpoints, API validation, and the installed prompt resource work through the assembled application.

Provide at least eight live evaluation cases: successful slot lookup, missing preferences, no available slots, proposal creation without a write, booking after conversational confirmation, changed preferences requiring fresh confirmation, instruction-injection resistance, and an unsupported request. Each case must include expected tool behavior and state assertions, not just an expected sentence. Clearly label the fake-LLM tests as software tests and the real-LLM cases as behavioral evaluations. Run persistence and concurrency integration tests against PostgreSQL; substitute neither SQLite nor mocks for those checks.

The evaluation runner must emit machine-readable results with case ID, configuration versions, observed tool calls, assertions, latency, and token usage. Run live evaluations only when explicitly invoked; exclude them from ordinary CI. Passing this small case set is a smoke check, not proof of production readiness.

## 9. Deliver and verify

Run formatting/linting, type checks, offline tests, and a container build/start check when the environment supports it. If an API key is securely available, run one small real-LLM smoke test. If it is absent, complete all offline work and state exactly which live check was not run. Never claim a live test passed based on a fake response.

The README must let a new developer:

1. Install the locked dependencies and configure environment variables.
2. Start the service locally or in Docker.
3. Send a real-LLM chat request using curl.
4. Continue the conversation, receive the exact proposed appointment, reply `confirm`, and see the agent call the booking tool.
5. Run offline tests and opt-in live evaluations.

Use actual response IDs in executable walkthroughs, or clearly mark placeholders. Explain the request flow and why each module exists in `docs/architecture.md`. Document the confirmation vocabulary, synthetic data, internal authentication boundary, migration procedure, and which integrations must change before real production use. Include a CI database service for the integration checks. Read current official OpenTelemetry guidance before configuring instrumentation and link it in the architecture document.

Finish with a concise report: what runs, the main code boundaries, commands to try it, verification completed, and remaining limitations. Do not expand into a full deployment platform or claim the earlier production acceptance checklist has been satisfied.
