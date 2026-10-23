import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from typing import Literal

from app.agent.planner import AgentPlan
from app.agent.verification import CriterionResult, ReviewResult, VerificationContract

RunStatus = Literal["running", "succeeded", "no_changes", "unverified", "failed", "cancelled"]
EventType = Literal[
    "started",
    "baseline",
    "plan",
    "attempt",
    "model_message",
    "tool_call",
    "tool_result",
    "tests_passed",
    "tests_failed",
    "contract",
    "review",
    "verification_failed",
    "hypothesis_rejected",
    "finished",
    "failed",
    "cancelled",
]

MAX_EVENT_DETAIL_CHARS = 2000


class RunError(Exception):
    public_message = "The run request failed"


class RunNotFoundError(RunError):
    public_message = "Run not found"


class RunConflictError(RunError):
    public_message = "This repository already has a run in progress"


class RunNotActiveError(RunError):
    public_message = "This run is not in progress"


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
class Attempt:
    n: int
    hypothesis: str
    diff: str
    test_passed: bool
    failure_summary: str | None


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
    plan: AgentPlan | None = None
    attempts: list[Attempt] = field(default_factory=list)
    baseline_output: str | None = None
    contract: VerificationContract | None = None
    criterion_results: list[CriterionResult] = field(default_factory=list)
    review: ReviewResult | None = None
    pull_request_url: str | None = None

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

    def cancel(self) -> None:
        self.status = "cancelled"
        self.finished_at = now_iso()
        self.add_event("cancelled", "Run cancelled")

    def record_attempt(
        self,
        n: int,
        hypothesis: str,
        diff: str,
        test_passed: bool,
        failure_summary: str | None = None,
    ) -> Attempt:
        attempt = Attempt(
            n=n,
            hypothesis=hypothesis,
            diff=diff,
            test_passed=test_passed,
            failure_summary=failure_summary,
        )
        self.attempts.append(attempt)
        return attempt


class RunStore:
    """In-memory runs, one active run per repository. Resets when the backend restarts."""

    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}
        # The task executing each active run, so a cancel can interrupt it mid-step.
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def create(self, repo_id: str, issue: str) -> Run:
        if self.active_for(repo_id) is not None:
            raise RunConflictError(f"Repo {repo_id} has an active run")
        run = Run(run_id=uuid.uuid4().hex, repo_id=repo_id, issue=issue)
        self._runs[run.run_id] = run
        return run

    def get(self, repo_id: str, run_id: str) -> Run:
        run = self._runs.get(run_id)
        if run is None or run.repo_id != repo_id:
            raise RunNotFoundError(f"Unknown run {run_id!r} for repo {repo_id!r}")
        return run

    def active_for(self, repo_id: str) -> Run | None:
        return next(
            (run for run in self._runs.values() if run.repo_id == repo_id and run.is_active),
            None,
        )

    def attach_task(self, run_id: str, task: asyncio.Task[None]) -> None:
        self._tasks[run_id] = task

    def detach_task(self, run_id: str) -> None:
        self._tasks.pop(run_id, None)

    def cancel(self, repo_id: str, run_id: str) -> Run:
        run = self.get(repo_id, run_id)
        if not run.is_active:
            raise RunNotActiveError(f"Run {run_id!r} is {run.status}")
        # Marked first: the interrupted task sees a finished run and records nothing more.
        run.cancel()
        task = self._tasks.pop(run_id, None)
        if task is not None:
            task.cancel()
        return run


@lru_cache
def get_run_store() -> RunStore:
    return RunStore()
