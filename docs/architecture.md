# Architecture at a glance

This is a small, server-side appointment assistant. The Streamlit app is only a client; the API
owns the Google key, conversation state, authorization, confirmation boundary, and booking write.

## 1. System context

```mermaid
flowchart LR
    U[Customer] --> UI[Streamlit client\nbook-assist-client]
    UI -->|Bearer token + message| API[FastAPI appointment API]
    API --> AUTH[Principal authentication]
    API --> AGENT[Bounded agent loop]
    AGENT --> GEM[Google Gemini\nGOOGLE_API_KEY]
    AGENT --> TOOLS[Allowlisted tools]
    TOOLS --> SCHED[Mock scheduler adapter]
    SCHED --> DB[(PostgreSQL)]
    API --> DB
    API --> OBS[JSON logs + OpenTelemetry]
```

Important boundary: the browser never calls Gemini directly. `GOOGLE_API_KEY` stays in the API
process. The client sends only user text and receives trusted structured proposal/booking fields.

## 2. Container and code map

```mermaid
flowchart TB
    subgraph Client[book-assist-client]
        ST[app.py\nStreamlit UI]
    end

    subgraph Service[booking-assist API]
        ROUTES[api/routes.py\nHTTP contract]
        DEPS[api/dependencies.py\nBearer -> Principal]
        CHAT[agent/service.py\nChatService + AgentService]
        PROMPT[agent/prompts/system.md]
        GOOGLE[adapters/google_client.py\nGemini adapter]
        DISPATCH[agent/tools.py\nSchemas + allowlist]
        DOMAIN[domain/booking.py + models.py\nBusiness rules]
        REPO[adapters/repositories.py\nDurable state]
        SCHED[adapters/mock_scheduler.py\nScheduler boundary]
        SQL[adapters/database.py\nSQLAlchemy async]
    end

    ST --> ROUTES
    ROUTES --> DEPS
    ROUTES --> CHAT
    CHAT --> PROMPT
    CHAT --> GOOGLE
    CHAT --> DISPATCH
    DISPATCH --> DOMAIN
    DISPATCH --> SCHED
    SCHED --> REPO
    REPO --> SQL
```

| Component | Owns | Does not own |
|---|---|---|
| Streamlit client | Chat UI, session ID, bearer token, rendering receipts | Google key, booking rules, database |
| FastAPI routes | HTTP validation and status codes | Model prompts or SQL |
| Agent service | Bounded Gemini/tool continuation | Authority to bypass domain rules |
| Google adapter | SDK calls, provider errors, usage extraction | Principal identity or booking writes |
| Tool dispatcher | Tool allowlist and argument validation | Arbitrary code execution |
| Domain layer | Confirmation, ownership, expiry, booking preconditions | HTTP or Gemini SDK details |
| Repository | Transactions, idempotency, uniqueness, durable state | Conversation wording |
| Mock scheduler | Synthetic availability and scheduler-shaped interface | Authentication and approval policy |

## 3. One booking conversation

```mermaid
sequenceDiagram
    actor Customer
    participant UI as Streamlit
    participant API as FastAPI
    participant DB as PostgreSQL
    participant G as Gemini
    participant T as Tool dispatcher

    Customer->>UI: Find consultation Downtown after 17:00
    UI->>API: POST /v1/chat
    API->>DB: Authenticate, create/claim session, store message
    API->>G: User history + system prompt + 3 tool schemas
    G-->>API: search_slots(service, date, preference)
    API->>T: Validate and dispatch search_slots
    T->>DB: Read available synthetic slots
    DB-->>T: S1, S2
    T-->>API: Function response with call ID
    API->>G: Preserve model call + function response
    G-->>API: Present slots and ask customer to choose
    API-->>UI: Reply + no proposal
    UI-->>Customer: Show available slots

    Customer->>UI: The 17:30 slot
    UI->>API: POST /v1/chat
    API->>G: Continue conversation
    G-->>API: prepare_booking(slot_id=S1)
    API->>T: Validate owner/session and prepare proposal
    T->>DB: Supersede old proposal; create 5-minute proposal
    DB-->>T: Proposal P1
    T-->>API: Exact proposal details
    API->>G: Continue with proposal result
    G-->>API: Display details; ask for confirm/yes
    API-->>UI: proposal P1 + awaiting_confirmation

    Customer->>UI: confirm
    UI->>API: POST /v1/chat
    API->>DB: Record approval for P1 before Gemini call
    API->>G: Continue with approval message
    G-->>API: create_booking(proposal_id=P1)
    API->>T: Validate approval, owner, expiry, availability
    T->>DB: Atomic insert with unique slot/proposal constraints
    DB-->>T: Booking B1
    T-->>API: Booking result
    API->>G: Continue with stored booking result
    G-->>API: Confirmation explanation
    API-->>UI: Trusted booking B1 + booked
    UI-->>Customer: Booking receipt
```

## 4. Confirmation and write boundary

```mermaid
stateDiagram-v2
    [*] --> NoProposal
    NoProposal --> Searching: search_slots
    Searching --> NoProposal: no slots / missing information
    Searching --> ProposalUnapproved: prepare_booking
    ProposalUnapproved --> ProposalUnapproved: anything except exact confirm/yes
    ProposalUnapproved --> ProposalApproved: standalone confirm or yes
    ProposalUnapproved --> Searching: changed preference
    ProposalApproved --> Booked: create_booking passes checks
    ProposalApproved --> Searching: expired or unavailable
    Booked --> Booked: repeated request / idempotent replay
```

The model may request `create_booking`, but it cannot make the write valid. The repository checks
principal ownership, session ownership, expiry, recorded approval, booking enablement, current
availability, and database uniqueness.

## 5. Data model

```mermaid
erDiagram
    CONVERSATION_SESSIONS ||--o{ CONVERSATION_MESSAGES : contains
    CONVERSATION_SESSIONS ||--o{ BOOKING_PROPOSALS : owns
    AVAILABILITY_SLOTS ||--o{ BOOKING_PROPOSALS : selected_by
    BOOKING_PROPOSALS ||--o| MOCK_BOOKINGS : creates
    AVAILABILITY_SLOTS ||--o| MOCK_BOOKINGS : reserves
    CONVERSATION_SESSIONS {
        uuid id PK
        string principal_id
        datetime turn_claimed_until
        int version
    }
    CONVERSATION_MESSAGES {
        uuid id PK
        uuid session_id FK
        string role
        text content
        uuid client_message_id
    }
    AVAILABILITY_SLOTS {
        string id PK
        string service
        string location
        datetime starts_at
        string timezone
        boolean available
    }
    BOOKING_PROPOSALS {
        uuid id PK
        string principal_id
        uuid session_id FK
        string slot_id FK
        datetime expires_at
        string approved_message_id
        string status
    }
    MOCK_BOOKINGS {
        uuid id PK
        uuid proposal_id FK UNIQUE
        string slot_id FK UNIQUE
        string principal_id
    }
```

## 6. Deployment/runtime sequence

```mermaid
flowchart LR
    ENV[.env / deployment secrets] --> SETTINGS[Typed Settings]
    SETTINGS --> API[FastAPI process]
    API -->|alembic upgrade head| DB[(PostgreSQL)]
    API -->|shared async client| GEM[Google Gemini]
    API -->|health/live| LIVE[No dependencies]
    API -->|health/ready| READY[Database check only]
    SEED[python -m appointment_assistant.seed] --> DB
```

Startup requires `GOOGLE_API_KEY` for the real client. Database schema is applied by Alembic, not by
the application. Seeding is repeatable and inserts missing synthetic slots without overwriting
bookings.

## 7. Provider note

The first real smoke test exposed that `gemini-2.5-flash` was unavailable to this new API key. The
service now defaults to `gemini-3.8-flash`, which Google currently lists as stable and supporting
function calling. The adapter also preserves Gemini function-call IDs in `FunctionResponse` objects.
See Google's [model page](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash) and
[model migration guidance](https://ai.google.dev/gemini-api/docs/latest-model).

## 8. Documentation sources and limitations

- [Google Gen AI Python SDK](https://googleapis.github.io/python-genai/)
- [Gemini function calling](https://ai.google.dev/gemini-api/docs/function-calling)
- [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/)
- [Pydantic settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- [SQLAlchemy asyncio](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [Alembic tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html)
- [OpenTelemetry Python](https://opentelemetry.io/docs/languages/python/)

The demo uses a 90-second turn deadline and 55-second per-model-call timeout because the real
Gemini tool-calling smoke test showed higher latency than a plain text call. These are configurable
limits, not performance claims. This remains a learning service. Replace `MockScheduler`, validate real business rules, integrate
the organization's identity provider and support/notification systems, and complete the acceptance
checklist before considering a production pilot.
