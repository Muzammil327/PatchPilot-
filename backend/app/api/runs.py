import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.agent.runs import (
    Run,
    RunConflictError,
    RunError,
    RunNotFoundError,
    RunStore,
    get_run_store,
)
from app.agent.service import RunService
from app.api.llm import get_llm_client
from app.api.repos import CamelModel, require_text, to_http_error
from app.config import get_settings
from app.llm.client import LLMClient
from app.repo.errors import RepoError
from app.repo.service import RepoService, get_repo_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/repos/{repo_id}/runs")

MAX_ISSUE_LENGTH = 4000

STATUS_BY_RUN_ERROR: dict[type[RunError], int] = {
    RunNotFoundError: status.HTTP_404_NOT_FOUND,
    RunConflictError: status.HTTP_409_CONFLICT,
}


class CreateRunRequest(BaseModel):
    issue: str = Field(min_length=1, max_length=MAX_ISSUE_LENGTH)


class RunCreatedResponse(CamelModel):
    run_id: str
    status: str


class RunEventResponse(CamelModel):
    seq: int
    type: str
    message: str
    detail: str | None
    timestamp: str


class PlanResponse(CamelModel):
    root_cause: str
    files_to_inspect: list[str]
    steps: list[str]
    tests_to_add: list[str]


class RunResponse(CamelModel):
    run_id: str
    repo_id: str
    issue: str
    status: str
    created_at: str
    finished_at: str | None
    steps: int
    summary: str
    diff: str
    error: str | None
    plan: PlanResponse | None
    events: list[RunEventResponse]


def get_run_service(
    repos: Annotated[RepoService, Depends(get_repo_service)],
    store: Annotated[RunStore, Depends(get_run_store)],
) -> RunService:
    return RunService(repos, store, get_settings())


RunServiceDep = Annotated[RunService, Depends(get_run_service)]


def to_run_http_error(error: RunError) -> HTTPException:
    status_code = STATUS_BY_RUN_ERROR.get(type(error), status.HTTP_500_INTERNAL_SERVER_ERROR)
    return HTTPException(status_code, error.public_message)


def to_run_response(run: Run) -> RunResponse:
    return RunResponse(
        run_id=run.run_id,
        repo_id=run.repo_id,
        issue=run.issue,
        status=run.status,
        created_at=run.created_at,
        finished_at=run.finished_at,
        steps=run.steps,
        summary=run.summary,
        diff=run.diff,
        error=run.error,
        plan=(
            PlanResponse(
                root_cause=run.plan.root_cause,
                files_to_inspect=run.plan.files_to_inspect,
                steps=run.plan.steps,
                tests_to_add=run.plan.tests_to_add,
            )
            if run.plan
            else None
        ),
        events=[
            RunEventResponse(
                seq=event.seq,
                type=event.type,
                message=event.message,
                detail=event.detail,
                timestamp=event.timestamp,
            )
            for event in run.events
        ],
    )


@router.post(
    "",
    response_model=RunCreatedResponse,
    response_model_by_alias=True,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_run(
    repo_id: str,
    body: CreateRunRequest,
    background: BackgroundTasks,
    runs: RunServiceDep,
    llm: Annotated[LLMClient, Depends(get_llm_client)],
) -> RunCreatedResponse:
    issue = require_text(body.issue, "Issue")
    if not llm.is_configured:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "The model provider is not configured"
        )
    try:
        run = runs.start(repo_id, issue)
    except RepoError as exc:
        raise to_http_error(exc) from exc
    except RunError as exc:
        raise to_run_http_error(exc) from exc
    # Runs after the response is sent; poll GET .../runs/{run_id} for progress.
    background.add_task(runs.execute, run, llm)
    return RunCreatedResponse(run_id=run.run_id, status=run.status)


@router.get("/{run_id}", response_model=RunResponse, response_model_by_alias=True)
async def get_run(repo_id: str, run_id: str, runs: RunServiceDep) -> RunResponse:
    try:
        run = runs.get(repo_id, run_id)
    except RepoError as exc:
        raise to_http_error(exc) from exc
    except RunError as exc:
        raise to_run_http_error(exc) from exc
    return to_run_response(run)
