"""Shared FastAPI wiring for routes that call the model provider."""

import logging

from fastapi import HTTPException, status

from app.config import get_settings
from app.llm.client import LLMClient, LLMError, LLMNotConfiguredError

logger = logging.getLogger(__name__)


def get_llm_client() -> LLMClient:
    return LLMClient(get_settings())


def to_llm_http_error(error: LLMError) -> HTTPException:
    """Map a provider failure to a client-safe error; details stay in the log."""
    if isinstance(error, LLMNotConfiguredError):
        logger.error("llm not configured: %s", error)
        return HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "The model provider is not configured"
        )
    logger.error("llm request failed: %s", error)
    return HTTPException(status.HTTP_502_BAD_GATEWAY, "The model provider request failed")
