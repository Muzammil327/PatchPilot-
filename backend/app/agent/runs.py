import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from typing import Literal

RunStatus = Literal["running", "succeeded", "no_changes", "failed"]
EventType = Literal["started", "model_message", "tool_call", "tool_result", "finished", "failed"]

MAX_EVENT_DETAIL_CHARS = 2000


class RunError(Exception):
    public_message = "The run request failed"


class RunNotFoundError(RunError):
    public_message = "Run not found"


class RunConflictError(RunError):
    public_message = "This repository already has a run in progress"


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class RunEvent:
    seq: int
    type: EventType
    message: str
    detail: str | None
    timestamp: str


@dataclass
class Run:
    run_id: str
    repo_id: str
    issue: str
    status: RunStatus = "running"
    created_at: str = field(default_factory=now_iso)
    finished_at: str | None = None
    steps: int = 0
    events: list[RunEvent] = field(default_factory=list)
    diff: str = ""
    summary: str = ""
    error: str | None = None

    @property
    def is_active(self) -> bool:
        return self.status == "running"

    def add_event(self, type: EventType, message: str, detail: str | None = None) -> None:
        if detail is not None and len(detail) > MAX_EVENT_DETAIL_CHARS:
            detail = detail[:MAX_EVENT_DETAIL_CHARS] + "\n… (truncated)"
        self.events.append(
            RunEvent(
                seq=len(self.events) + 1,
                type=type,
                message=message,
                detail=detail,
                timestamp=now_iso(),
            )
        )

    def finish(self, status: RunStatus, diff: str = "", summary: str = "") -> None:
        self.status = status
        self.diff = diff
        self.summary = summary
        self.finished_at = now_iso()
        self.add_event("finished", f"Run finished: {status}", summary or None)

    def fail(self, error: str) -> None:
        self.status = "failed"
        self.error = error
        self.finished_at = now_iso()
        self.add_event("failed", error)


class RunStore:
    """In-memory runs, one active run per repository. Resets when the backend restarts."""

    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}

    def create(self, repo_id: str, issue: str) -> Run:
        if any(run.repo_id == repo_id and run.is_active for run in self._runs.values()):
            raise RunConflictError(f"Repo {repo_id} has an active run")
        run = Run(run_id=uuid.uuid4().hex, repo_id=repo_id, issue=issue)
        self._runs[run.run_id] = run
        return run

    def get(self, repo_id: str, run_id: str) -> Run:
        run = self._runs.get(run_id)
        if run is None or run.repo_id != repo_id:
            raise RunNotFoundError(f"Unknown run {run_id!r} for repo {repo_id!r}")
        return run


@lru_cache
def get_run_store() -> RunStore:
    return RunStore()
