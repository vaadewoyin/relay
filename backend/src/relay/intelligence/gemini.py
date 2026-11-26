import asyncio
import os
from time import monotonic

import httpx
from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from relay.domain import Contract
from relay.intelligence.contracts import FailureCategory, Usage
from relay.intelligence.provider import ModelProvider, ModelResponse, ProviderFailure

DEFAULT_MODEL = "gemini-3.1-flash-lite"
RETRYABLE = {
    FailureCategory.TIMEOUT,
    FailureCategory.UNAVAILABLE,
    FailureCategory.RATE_LIMITED,
}


def classify(exc: errors.APIError) -> FailureCategory:
    match exc.code:
        case 401 | 403:
            return FailureCategory.UNAUTHORIZED
        case 408 | 504:
            return FailureCategory.TIMEOUT
        case 429:
            return FailureCategory.RATE_LIMITED
        case code if isinstance(code, int) and code >= 500:
            return FailureCategory.UNAVAILABLE
        case _:
            return FailureCategory.INVALID_REQUEST


def supported_schema(node: object) -> object:
    # Size and closed-object constraints can make Gemini's decoding grammar too complex.
    # Pydantic still enforces those constraints on every response.
    if isinstance(node, dict):
        return {
            key: supported_schema(value)
            for key, value in node.items()
            if key
            not in {
                "pattern",
                "format",
                "minLength",
                "maxLength",
                "minItems",
                "maxItems",
                "additionalProperties",
                "title",
                "default",
            }
        }
    if isinstance(node, list):
        return [supported_schema(value) for value in node]
    return node


class GeminiProvider(ModelProvider):
    def __init__(
        self, api_key: str | None, model: str = DEFAULT_MODEL, attempts: int = 2
    ):
        self._api_key = api_key
        self.model = model
        self.attempts = attempts

    @classmethod
    def from_environment(cls) -> "GeminiProvider":
        return cls(
            os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"),
            model=os.getenv("RELAY_GEMINI_MODEL", DEFAULT_MODEL),
            attempts=int(os.getenv("RELAY_AI_ATTEMPTS", "2")),
        )

    async def generate[T: Contract](
        self,
        *,
        instructions: str,
        data: str,
        schema: type[T],
        timeout: float,
        output_tokens: int,
    ) -> ModelResponse[T]:
        if not self._api_key:
            raise ProviderFailure(FailureCategory.NOT_CONFIGURED)
        if not 1 <= self.attempts <= 3 or timeout <= 0:
            raise ProviderFailure(FailureCategory.BUDGET)
        deadline = monotonic() + timeout
        for attempt in range(self.attempts):
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise ProviderFailure(
                    FailureCategory.TIMEOUT, retries=max(0, attempt - 1)
                )
            try:
                async with asyncio.timeout(remaining):
                    result = await self._generate(
                        instructions, data, schema, remaining, output_tokens
                    )
                return ModelResponse(result.result, result.usage, attempt)
            except ProviderFailure as exc:
                if exc.category not in RETRYABLE or attempt + 1 == self.attempts:
                    raise ProviderFailure(
                        exc.category, retries=attempt, usage=exc.usage
                    ) from None
                await asyncio.sleep(
                    min(0.2 * (attempt + 1), max(0, deadline - monotonic()))
                )
            except TimeoutError:
                raise ProviderFailure(
                    FailureCategory.TIMEOUT, retries=attempt
                ) from None
        raise AssertionError("Retry loop did not terminate.")

    async def _generate[T: Contract](
        self,
        instructions: str,
        data: str,
        schema: type[T],
        remaining: float,
        output_tokens: int,
    ) -> ModelResponse[T]:
        try:
            client = genai.Client(
                api_key=self._api_key,
                http_options=types.HttpOptions(
                    timeout=max(1, int(remaining * 1000)),
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            )
            async with client.aio as transport:
                response = await transport.models.generate_content(
                    model=self.model,
                    contents=data,
                    config=types.GenerateContentConfig(
                        system_instruction=instructions,
                        response_mime_type="application/json",
                        response_json_schema=supported_schema(
                            schema.model_json_schema()
                        ),
                        max_output_tokens=output_tokens,
                    ),
                )
        except errors.APIError as exc:
            raise ProviderFailure(classify(exc)) from None
        except httpx.TimeoutException:
            raise ProviderFailure(FailureCategory.TIMEOUT) from None
        except httpx.TransportError:
            raise ProviderFailure(FailureCategory.UNAVAILABLE) from None
        usage = response.usage_metadata
        tokens = (
            Usage(
                input_tokens=usage.prompt_token_count,
                output_tokens=usage.candidates_token_count,
                thinking_tokens=usage.thoughts_token_count,
            )
            if usage
            else Usage()
        )
        candidate = response.candidates[0] if response.candidates else None
        if (response.prompt_feedback and response.prompt_feedback.block_reason) or (
            candidate
            and candidate.finish_reason
            in {"SAFETY", "RECITATION", "PROHIBITED_CONTENT"}
        ):
            raise ProviderFailure(FailureCategory.BLOCKED_RESPONSE, usage=tokens)
        if not candidate or candidate.finish_reason != types.FinishReason.STOP:
            raise ProviderFailure(FailureCategory.MALFORMED_OUTPUT, usage=tokens)
        try:
            return ModelResponse(
                schema.model_validate_json(response.text or ""), tokens
            )
        except ValidationError:
            raise ProviderFailure(
                FailureCategory.MALFORMED_OUTPUT, usage=tokens
            ) from None
