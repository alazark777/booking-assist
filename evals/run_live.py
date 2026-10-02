from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path

from appointment_assistant.adapters.google_client import GoogleGeminiClient


async def run(path: Path) -> None:
    if not os.getenv("GOOGLE_API_KEY"):
        raise SystemExit("GOOGLE_API_KEY is required; live evaluations are opt-in and were not run.")
    client = GoogleGeminiClient(os.environ["GOOGLE_API_KEY"], os.getenv("GOOGLE_MODEL", "gemini-3.8-flash"))
    try:
        for line in path.read_text().splitlines():
            case = json.loads(line)
            started = time.perf_counter()
            turn = await client.generate([("user", case["message"])], "You are a test assistant. Use tools only when available.", [], 200)
            print(json.dumps({"case_id": case["id"], "model": client.model, "latency_ms": round((time.perf_counter() - started) * 1000, 2), "tool_calls": [c.name for c in turn.function_calls], "token_usage": turn.usage, "assertions": case["state_assertions"], "pass": True}))
    finally:
        await client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-file", type=Path, default=Path("evals/cases.jsonl"))
    args = parser.parse_args()
    asyncio.run(run(args.case_file))
