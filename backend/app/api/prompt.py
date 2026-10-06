import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.config import get_settings
from app.llm.client import LLMClient, LLMError, LLMNotConfiguredError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

MAX_PROMPT_LENGTH = 20_000


class PromptRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_LENGTH)


class PromptResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    output: str
    model: str
    latency_ms: int


def get_llm_client() -> LLMClient:
    return LLMClient(get_settings())


@router.post("/prompt", response_model=PromptResponse, response_model_by_alias=True)
async def create_prompt_completion(
    body: PromptRequest, llm: Annotated[LLMClient, Depends(get_llm_client)]
) -> PromptResponse:
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Prompt must not be empty")

    try:
        completion = await llm.complete(prompt, role="worker")
    except LLMNotConfiguredError as exc:
        logger.error("llm not configured: %s", exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "The model provider is not configured"
        ) from exc
    except LLMError as exc:
        logger.error("llm request failed: %s", exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "The model provider request failed"
        ) from exc

    return PromptResponse(
        output=completion.output, model=completion.model, latency_ms=completion.latency_ms
    )
