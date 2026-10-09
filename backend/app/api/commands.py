from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.repos import CamelModel, to_http_error
from app.repo.errors import RepoError
from app.repo.service import RepoService, get_repo_service
from app.sandbox.commands import CommandName
from app.sandbox.errors import (
    CommandUnavailableError,
    SandboxBusyError,
    SandboxError,
    SandboxUnavailableError,
)
from app.sandbox.runner import CommandResult
from app.sandbox.service import SandboxService, get_sandbox_service

router = APIRouter(prefix="/api/repos/{repo_id}/commands")

STATUS_BY_SANDBOX_ERROR: dict[type[SandboxError], int] = {
    CommandUnavailableError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    SandboxBusyError: status.HTTP_409_CONFLICT,
    SandboxUnavailableError: status.HTTP_503_SERVICE_UNAVAILABLE,
}


class RunCommandRequest(BaseModel):
    name: CommandName


class CommandResultResponse(CamelModel):
    name: str
    command: str
    exit_code: int
    passed: bool
    timed_out: bool
    duration_ms: int
    output: str


def to_result_response(result: CommandResult) -> CommandResultResponse:
    return CommandResultResponse(
        name=result.name,
        command=result.command,
        exit_code=result.exit_code,
        passed=result.passed,
        timed_out=result.timed_out,
        duration_ms=result.duration_ms,
        output=result.output,
    )


@router.post("", response_model=CommandResultResponse, response_model_by_alias=True)
async def run_command(
    repo_id: str,
    body: RunCommandRequest,
    repos: Annotated[RepoService, Depends(get_repo_service)],
    sandbox: Annotated[SandboxService, Depends(get_sandbox_service)],
) -> CommandResultResponse:
    """Run one allow-listed command (install/test/lint/build) in the sandbox.

    A command that runs but fails (non-zero exit, timeout) is still a 200 with
    `passed: false`; only failing to start it is an error.
    """
    try:
        result = await sandbox.run(repos, repo_id, body.name)
    except RepoError as exc:
        raise to_http_error(exc) from exc
    except SandboxError as exc:
        status_code = STATUS_BY_SANDBOX_ERROR.get(type(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)
        raise HTTPException(status_code, exc.public_message) from exc
    return to_result_response(result)
