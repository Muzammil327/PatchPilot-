import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Literal

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

ModelRole = Literal["planner", "worker"]

RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
RETRY_BASE_DELAY_SECONDS = 0.5


class LLMError(Exception):
    """Provider failure. The message is safe to log; it is never sent to clients."""


class LLMNotConfiguredError(LLMError):
    pass


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

    def model_for(self, role: ModelRole) -> str:
        return self._settings.model_planner if role == "planner" else self._settings.model_worker

    async def complete(
        self, prompt: str, role: ModelRole = "worker", system: str | None = None
    ) -> Completion:
        if not self._settings.is_llm_configured:
            raise LLMNotConfiguredError("Nebius settings are missing")

        model = self.model_for(role)
        messages = [{"role": "system", "content": system}] if system else []
        messages.append({"role": "user", "content": prompt})
        payload = {"model": model, "messages": messages}
        started = time.perf_counter()
        data = await self._post_with_retries("/chat/completions", payload)
        latency_ms = int((time.perf_counter() - started) * 1000)

        try:
            output = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("Unexpected response shape from provider") from exc

        usage = data.get("usage") or {}
        completion = Completion(
            output=output,
            model=data.get("model", model),
            latency_ms=latency_ms,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )
        logger.info(
            "llm completion model=%s latency_ms=%d prompt_tokens=%s completion_tokens=%s",
            completion.model,
            completion.latency_ms,
            completion.prompt_tokens,
            completion.completion_tokens,
        )
        return completion

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
                        raise LLMError(f"Provider returned HTTP {response.status_code}")
                    logger.warning(
                        "llm retryable status=%d attempt=%d", response.status_code, attempt
                    )
                await asyncio.sleep(RETRY_BASE_DELAY_SECONDS * 2 ** (attempt - 1))

        raise LLMError("Retries exhausted")
