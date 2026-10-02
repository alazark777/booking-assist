from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

from google import genai
from google.genai import errors, types


@dataclass
class FunctionCall:
    name: str
    args: dict[str, Any]
    call_id: str | None = None


@dataclass
class ModelTurn:
    text: str
    function_calls: list[FunctionCall]
    model_content: Any = None
    usage: dict[str, int] | None = None


class LLMClient(Protocol):
    async def generate(
        self, contents: list[Any], system_prompt: str, tools: list[dict[str, Any]], max_output_tokens: int
    ) -> ModelTurn: ...

    async def close(self) -> None: ...


class ProviderError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class GoogleGeminiClient:
    """Manual Google function-calling adapter; automatic SDK tool execution is disabled."""

    def __init__(self, api_key: str, model: str, timeout_seconds: float = 20.0):
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.client = genai.Client(api_key=api_key)

    @staticmethod
    def _content_from_history(contents: list[Any]) -> list[types.Content]:
        result: list[types.Content] = []
        for item in contents:
            if isinstance(item, types.Content):
                result.append(item)
            else:
                role, text = item
                role = "model" if role == "assistant" else role
                result.append(types.Content(role=role, parts=[types.Part.from_text(text=text)]))
        return result

    async def generate(
        self, contents: list[Any], system_prompt: str, tools: list[dict[str, Any]], max_output_tokens: int
    ) -> ModelTurn:
        declarations = [
            types.FunctionDeclaration(
                name=tool["name"],
                description=tool["description"],
                parameters_json_schema=tool["parameters"],
            )
            for tool in tools
        ]
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=max_output_tokens,
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
            tools=[types.Tool(function_declarations=declarations)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        try:
            response = await asyncio.wait_for(
                self.client.aio.models.generate_content(
                    model=self.model,
                    contents=self._content_from_history(contents),
                    config=config,
                ),
                timeout=self.timeout_seconds,
            )
        except TimeoutError as exc:
            raise ProviderError("provider_timeout", "The Google model took too long to respond.") from exc
        except errors.APIError as exc:
            if exc.code in {401, 403}:
                code = "provider_authentication_failed"
            elif exc.code == 429:
                code = "provider_rate_limited"
            else:
                code = "provider_error"
            raise ProviderError(code, "The Google model is temporarily unavailable.") from exc
        except Exception as exc:
            raise ProviderError("provider_error", "The Google model is temporarily unavailable.") from exc

        candidate = response.candidates[0] if response.candidates else None
        model_content = candidate.content if candidate else None
        calls: list[FunctionCall] = []
        if candidate and candidate.content:
            for part in candidate.content.parts or []:
                if part.function_call:
                    calls.append(
                        FunctionCall(
                            part.function_call.name or "",
                            dict(part.function_call.args or {}),
                            getattr(part, "id", None) or getattr(part.function_call, "id", None),
                        )
                    )
        usage = None
        if response.usage_metadata:
            usage = {
                "prompt_tokens": response.usage_metadata.prompt_token_count or 0,
                "output_tokens": response.usage_metadata.candidates_token_count or 0,
                "total_tokens": response.usage_metadata.total_token_count or 0,
            }
        return ModelTurn(response.text or "", calls, model_content, usage)

    async def close(self) -> None:
        await self.client.aio.aclose()
