import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.agent.errors import ToolError

GIT_TIMEOUT_SECONDS = 30
MAX_STDERR_CHARS = 300
RUN_ID_PATTERN = re.compile(r"^[a-f0-9]{8,64}$")
RUN_BRANCH_PREFIX = "patchpilot/"

# Arguments are always fixed by us, never taken from the model, so a tool call can
# not smuggle in flags such as `--output` or `-c core.sshCommand=...`.
GIT_BASE_ARGS = ("git", "-c", "core.quotepath=false", "-c", "color.ui=false")


@dataclass(frozen=True)
class RunBranch:
    name: str
    base_commit: str


def run_git(workspace: Path, *args: str) -> str:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        result = subprocess.run(
            [*GIT_BASE_ARGS, *args],
            cwd=workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_TIMEOUT_SECONDS,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"git {args[0]} timed out") from exc
    if result.returncode != 0:
        detail = result.stderr.strip()[:MAX_STDERR_CHARS]
        raise ToolError(f"git {args[0]} failed: {detail}")
    return result.stdout


def start_run_branch(workspace: Path, run_id: str) -> RunBranch:
    """Create `patchpilot/<run_id>` at the current commit so the diff is only the agent's work."""
    if not RUN_ID_PATTERN.match(run_id):
        raise ValueError(f"Invalid run id {run_id!r}")
    base_commit = run_git(workspace, "rev-parse", "HEAD").strip()
    name = f"{RUN_BRANCH_PREFIX}{run_id}"
    run_git(workspace, "switch", "--quiet", "-c", name)
    return RunBranch(name=name, base_commit=base_commit)


def reset_workspace(workspace: Path, base_commit: str) -> None:
    """Throw away every change since `base_commit`, including new untracked files."""
    run_git(workspace, "reset", "--quiet", "--hard", base_commit)
    run_git(workspace, "clean", "--quiet", "-fd")


def workspace_status(workspace: Path) -> str:
    return run_git(workspace, "status", "--porcelain")


def workspace_diff(workspace: Path) -> str:
    """Unified diff of all changes, new files included.

    New files only appear in a diff once staged, so everything is staged first;
    the index belongs to this throwaway clone, so that is safe.
    """
    run_git(workspace, "add", "--all")
    return run_git(workspace, "diff", "--cached", "--no-ext-diff")
