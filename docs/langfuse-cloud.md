# Langfuse Cloud tracing

The backend is prepared for Langfuse Cloud. It sends traces outbound over HTTPS; you do not need to run Langfuse locally or expose your computer to the internet.

## Configure it

1. Create a free project at <https://cloud.langfuse.com>.
2. Open the project settings and create API credentials.
3. Add these values to the backend `.env` file:

```dotenv
LANGFUSE_TRACING_ENABLED=true
LANGFUSE_PUBLIC_KEY=pk-lf-your-key
LANGFUSE_SECRET_KEY=sk-lf-your-key
LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_TRACING_ENVIRONMENT=local
LANGFUSE_CAPTURE_CONTENT=false
```

For the US data region, use `https://us.cloud.langfuse.com` instead.

Then restart the backend:

```bash
podman compose up --build
```

Send a chat message from the Streamlit client and open the Langfuse project’s **Traces** view. Each turn is grouped by `session_id` and associated with the authenticated customer. The trace contains:

- an `appointment-chat` agent observation;
- one model generation per LLM call, including token usage;
- one child tool observation per scheduler tool call; and
- the Langfuse trace ID in the API response and `X-Trace-Id` header.

Content capture is disabled by default. This still records timing, model, usage, session, user, status, and tool names while avoiding full prompts and appointment payloads. Set `LANGFUSE_CAPTURE_CONTENT=true` only when you want the user message, model response, and tool payloads in the trace.

If the keys are absent or tracing is disabled, the application continues to run without sending telemetry.
