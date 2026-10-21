"""Turn a run's diff into the file contents a commit needs, without touching the workspace.

The diff is applied to a temporary index built from HEAD, so the working tree and the
real index (which an active run may be using) are never modified.
"""

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.agent.errors import ToolError
from app.agent.workspace_git import GIT_TIMEOUT_SECONDS, run_git
from app.pr.errors import PatchApplyError

DIFF_FILE_NAME = "run.diff"
INDEX_FILE_NAME = "index"
# The tree API ignores the mode of a deleted entry, but it must still be a valid one.
DELETED_MODE = "100644"


@dataclass(frozen=True)
class ChangedFile:
    path: str
    mode: str  # git file mode, e.g. "100644"
    content: bytes | None  # None when the file was deleted


@dataclass(frozen=True)
class RunChanges:
    base_commit: str
    files: list[ChangedFile]


def collect_changes(workspace: Path, diff: str) -> RunChanges:
    """Blocking; call from a worker thread."""
    try:
        return _collect(workspace, diff)
    except ToolError as exc:
        raise PatchApplyError(str(exc)) from exc


def _collect(workspace: Path, diff: str) -> RunChanges:
    base_commit = run_git(workspace, "rev-parse", "HEAD").strip()
    with tempfile.TemporaryDirectory(prefix="patchpilot-pr-") as scratch:
        diff_path = Path(scratch) / DIFF_FILE_NAME
        # Bytes, so Windows newline translation cannot corrupt the patch.
        diff_path.write_bytes(diff.encode("utf-8"))
        env = {"GIT_INDEX_FILE": str(Path(scratch) / INDEX_FILE_NAME)}
        run_git(workspace, "read-tree", base_commit, extra_env=env)
        run_git(
            workspace, "apply", "--cached", "--whitespace=nowarn", str(diff_path), extra_env=env
        )
        changed = run_git(
            workspace,
            "diff",
            "--cached",
            "--no-renames",
            "--name-status",
            "-z",
            base_commit,
            extra_env=env,
        )
        files = [
            _changed_file(workspace, status, path, env)
            for status, path in _pairs(changed.split("\0"))
        ]
    return RunChanges(base_commit=base_commit, files=files)


def _pairs(fields: list[str]) -> list[tuple[str, str]]:
    # `-z --name-status` output is "STATUS\0PATH\0" repeated, with a trailing empty field.
    items = [field for field in fields if field]
    return list(zip(items[0::2], items[1::2], strict=True))


def _changed_file(workspace: Path, status: str, path: str, env: dict[str, str]) -> ChangedFile:
    if status == "D":
        return ChangedFile(path=path, mode=DELETED_MODE, content=None)
    # "<mode> <blob> <stage><TAB><path>"
    mode, blob, _ = run_git(workspace, "ls-files", "--stage", "--", path, extra_env=env).split(
        maxsplit=2
    )
    return ChangedFile(path=path, mode=mode, content=_read_blob(workspace, blob))


def _read_blob(workspace: Path, blob: str) -> bytes:
    # run_git decodes output as text; file contents must stay byte-exact.
    try:
        result = subprocess.run(
            ["git", "cat-file", "blob", blob],
            cwd=workspace,
            capture_output=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise PatchApplyError(f"git cat-file {blob} timed out") from exc
    if result.returncode != 0:
        raise PatchApplyError(f"git cat-file {blob} failed")
    return result.stdout
