import os
from pathlib import Path

from app.agent.errors import ToolError
from app.agent.workspace_git import workspace_diff, workspace_status
from app.repo.scan import SKIPPED_DIRS, scan_workspace
from app.repo.search import search_code as search_repo

MAX_READ_LINES = 400
MAX_READ_CHARS = 40_000
MAX_WRITE_BYTES = 512 * 1024
MAX_LIST_ENTRIES = 500
MAX_LIST_DEPTH = 4
MAX_DIFF_CHARS = 60_000
DEFAULT_SCAN_FILES = 5000
DEFAULT_SCAN_FILE_BYTES = 1024 * 1024
PROTECTED_TOP_LEVEL = frozenset({".git"})
CRLF = "\r\n"


class WorkspaceTools:
    """The file and git operations an agent may perform, confined to one workspace.

    Every path argument comes from the model, so each one is resolved (following
    symlinks) and must land inside the workspace and outside `.git/`.
    """

    def __init__(
        self,
        workspace: Path,
        max_scan_files: int = DEFAULT_SCAN_FILES,
        max_scan_file_bytes: int = DEFAULT_SCAN_FILE_BYTES,
    ):
        self.root = workspace.resolve()
        self.max_scan_files = max_scan_files
        self.max_scan_file_bytes = max_scan_file_bytes

    def resolve(self, path: str) -> Path:
        if not path or "\x00" in path:
            raise ToolError("Provide a file path relative to the repository root.")
        candidate = (self.root / path).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ToolError(f"Path {path!r} is outside the repository.")
        parts = candidate.relative_to(self.root).parts
        if parts and parts[0] in PROTECTED_TOP_LEVEL:
            raise ToolError("The .git directory is off-limits.")
        return candidate

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix() or "."

    def read_file(self, path: str, start_line: int = 1, end_line: int | None = None) -> str:
        target = self.resolve(path)
        text = self.read_text(target, path)
        lines = text.splitlines()
        if start_line < 1 or (end_line is not None and end_line < start_line):
            raise ToolError("start_line must be >= 1 and end_line >= start_line.")
        requested_last = len(lines) if end_line is None else min(end_line, len(lines))
        last = min(requested_last, start_line + MAX_READ_LINES - 1)
        numbered = "\n".join(
            f"{number}| {lines[number - 1]}" for number in range(start_line, last + 1)
        )
        if len(numbered) > MAX_READ_CHARS:
            return numbered[:MAX_READ_CHARS] + (
                "\n… (output cut at the size limit; request a smaller line range)"
            )
        if last < requested_last:
            numbered += (
                f"\n… ({len(lines)} lines in total; call read_file with "
                f"start_line={last + 1} to continue)"
            )
        return numbered or f"(empty file: {self.relative(target)})"

    def list_files(self, path: str = ".", depth: int = 2) -> str:
        top = self.resolve(path)
        if not top.is_dir():
            raise ToolError(f"{path!r} is not a directory.")
        depth = max(1, min(depth, MAX_LIST_DEPTH))
        entries: list[str] = []
        for dirpath, dirnames, filenames in os.walk(top):
            current = Path(dirpath)
            level = len(current.relative_to(top).parts)
            dirnames[:] = sorted(
                name
                for name in dirnames
                if name not in SKIPPED_DIRS and not (current / name).is_symlink()
            )
            if level + 1 >= depth:
                entries.extend(f"{self.relative(current / name)}/" for name in dirnames)
                dirnames.clear()
            entries.extend(self.relative(current / name) for name in sorted(filenames))
            if len(entries) >= MAX_LIST_ENTRIES:
                return "\n".join(entries[:MAX_LIST_ENTRIES]) + "\n… (listing truncated)"
        return "\n".join(entries) or "(empty directory)"

    def search_code(self, query: str) -> str:
        if not query.strip():
            raise ToolError("Provide text to search for.")
        files = scan_workspace(
            self.root, max_files=self.max_scan_files, max_file_size_bytes=self.max_scan_file_bytes
        ).files
        result = search_repo(self.root, files, query)
        if not result.matches:
            return f"No lines contain {query!r}."
        lines = [f"{match.path}:{match.line}: {match.text}" for match in result.matches]
        if result.is_truncated:
            lines.append("… (more matches; refine the query)")
        return "\n".join(lines)

    def write_file(self, path: str, content: str) -> str:
        target = self.resolve(path)
        if target.is_dir():
            raise ToolError(f"{path!r} is a directory.")
        data = content.encode("utf-8")
        if len(data) > MAX_WRITE_BYTES:
            raise ToolError(f"Content is larger than {MAX_WRITE_BYTES} bytes.")
        existed = target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        action = "Updated" if existed else "Created"
        return f"{action} {self.relative(target)} ({len(data)} bytes)."

    def replace_code(self, path: str, old: str, new: str) -> str:
        """Replace one exact occurrence of `old`, so an edit never lands in the wrong place."""
        target = self.resolve(path)
        if not old:
            raise ToolError("`old` must not be empty; use write_file to create a file.")
        text = self.read_text(target, path)
        count = text.count(old)
        if count == 0 and CRLF in text and "\n" in old:
            # The model writes "\n"; Windows-checked-out files use "\r\n".
            old, new = old.replace("\n", CRLF), new.replace("\n", CRLF)
            count = text.count(old)
        if count == 0:
            raise ToolError(f"`old` was not found in {path!r}; read the file and copy it exactly.")
        if count > 1:
            raise ToolError(
                f"`old` matches {count} places in {path!r}; include more surrounding lines."
            )
        target.write_bytes(text.replace(old, new, 1).encode("utf-8"))
        return f"Replaced 1 occurrence in {self.relative(target)}."

    def git_status(self) -> str:
        return workspace_status(self.root) or "(no changes)"

    def git_diff(self) -> str:
        diff = workspace_diff(self.root)
        if len(diff) > MAX_DIFF_CHARS:
            return diff[:MAX_DIFF_CHARS] + "\n… (diff truncated)"
        return diff or "(no changes)"

    def read_text(self, target: Path, path: str) -> str:
        if not target.is_file():
            raise ToolError(f"{path!r} does not exist or is not a file.")
        data = target.read_bytes()
        if b"\x00" in data:
            raise ToolError(f"{path!r} looks like a binary file.")
        # Decoding raw bytes keeps "\r\n" intact, so edits write back the same line endings.
        return data.decode("utf-8", errors="replace")
