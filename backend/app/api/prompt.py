from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.api.llm import get_llm_client, to_llm_http_error
from app.llm.client import LLMClient, LLMError

router = APIRouter(prefix="/api")

MAX_PROMPT_LENGTH = 20_000


class PromptRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_LENGTH)


class PromptResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    output: str
    model: str
    latency_ms: int


@router.post("/prompt", response_model=PromptResponse, response_model_by_alias=True)
async def create_prompt_completion(
    body: PromptRequest, llm: Annotated[LLMClient, Depends(get_llm_client)]
) -> PromptResponse:
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Prompt must not be empty")

    try:
        completion = await llm.complete(prompt, role="worker")
    except LLMError as exc:
        raise to_llm_http_error(exc) from exc

    return PromptResponse(
        output=completion.output, model=completion.model, latency_ms=completion.latency_ms
    )
