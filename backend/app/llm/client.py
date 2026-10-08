import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

ModelRole = Literal["planner", "worker"]
Message = dict[str, Any]  # one OpenAI-style chat message

RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
# Providers answer a request they cannot handle (e.g. an unsupported `tools` field) with these.
REJECTED_REQUEST_STATUS_CODES = frozenset({400, 422})
RETRY_BASE_DELAY_SECONDS = 0.5


class LLMError(Exception):
    """Provider failure. The message is safe to log; it is never sent to clients."""


class LLMNotConfiguredError(LLMError):
    pass


class LLMHTTPError(LLMError):
    def __init__(self, status_code: int):
        super().__init__(f"Provider returned HTTP {status_code}")
        self.status_code = status_code


class LLMToolsUnsupportedError(LLMError):
    """The provider rejected a request that carried tool definitions."""


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON text, exactly as the model produced it


@dataclass(frozen=True)
class ChatResult:
    content: str
    model: str
    latency_ms: int
    prompt_tokens: int | None
    completion_tokens: int | None
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass(frozen=True)
class Completion:
    output: str
    model: str
    latency_ms: int
    prompt_tokens: int | None
    completion_tokens: int | None


class LLMClient:
    """Nebius Token Factory client using its OpenAI-compatible chat completions API."""

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self._settings = settings
        self._transport = transport

    @property
    def is_configured(self) -> bool:
        return self._settings.is_llm_configured

    def model_for(self, role: ModelRole) -> str:
        return self._settings.model_planner if role == "planner" else self._settings.model_worker

    async def complete(
        self, prompt: str, role: ModelRole = "worker", system: str | None = None
    ) -> Completion:
        messages: list[Message] = [{"role": "system", "content": system}] if system else []
        messages.append({"role": "user", "content": prompt})
        result = await self.chat(messages, role=role)
        return Completion(
            output=result.content,
            model=result.model,
            latency_ms=result.latency_ms,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
        )

    async def chat(
        self,
        messages: list[Message],
        role: ModelRole = "worker",
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResult:
        if not self._settings.is_llm_configured:
            raise LLMNotConfiguredError("Nebius settings are missing")

        model = self.model_for(role)
        payload: dict[str, Any] = {"model": model, "messages": messages}
        if tools:
            payload["tools"] = tools
        started = time.perf_counter()
        try:
            data = await self._post_with_retries("/chat/completions", payload)
        except LLMHTTPError as exc:
            if tools and exc.status_code in REJECTED_REQUEST_STATUS_CODES:
                raise LLMToolsUnsupportedError(str(exc)) from exc
            raise
        latency_ms = int((time.perf_counter() - started) * 1000)

        try:
            message = data["choices"][0]["message"]
            content = message.get("content") or ""
            tool_calls = [
                ToolCall(
                    id=str(call.get("id") or f"call_{index}"),
                    name=call["function"]["name"],
                    arguments=call["function"].get("arguments") or "{}",
                )
                for index, call in enumerate(message.get("tool_calls") or [])
            ]
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            raise LLMError("Unexpected response shape from provider") from exc

        usage = data.get("usage") or {}
        result = ChatResult(
            content=content,
            model=data.get("model", model),
            latency_ms=latency_ms,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            tool_calls=tool_calls,
        )
        logger.info(
            "llm chat model=%s latency_ms=%d prompt_tokens=%s completion_tokens=%s tool_calls=%d",
            result.model,
            result.latency_ms,
            result.prompt_tokens,
            result.completion_tokens,
            len(result.tool_calls),
        )
        return result

    async def _post_with_retries(self, path: str, payload: dict) -> dict:
        headers = {"Authorization": f"Bearer {self._settings.nebius_api_key}"}
        attempts = self._settings.llm_max_retries + 1

        async with httpx.AsyncClient(
            base_url=self._settings.nebius_base_url.rstrip("/"),
            timeout=self._settings.llm_timeout_seconds,
            transport=self._transport,
        ) as client:
            for attempt in range(1, attempts + 1):
                is_last = attempt == attempts
                try:
                    response = await client.post(path, json=payload, headers=headers)
                except httpx.TransportError as exc:
                    if is_last:
                        raise LLMError(f"Provider unreachable: {type(exc).__name__}") from exc
                    logger.warning("llm transport error attempt=%d", attempt)
                else:
                    if response.status_code < 400:
                        return response.json()
                    if is_last or response.status_code not in RETRYABLE_STATUS_CODES:
                        raise LLMHTTPError(response.status_code)
                    logger.warning(
                        "llm retryable status=%d attempt=%d", response.status_code, attempt
                    )
                await asyncio.sleep(RETRY_BASE_DELAY_SECONDS * 2 ** (attempt - 1))

        raise LLMError("Retries exhausted")
