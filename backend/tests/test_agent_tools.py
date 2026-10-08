import os
import subprocess
from pathlib import Path

import pytest

from app.agent.errors import ToolError
from app.agent.tools import MAX_READ_LINES, MAX_WRITE_BYTES, WorkspaceTools
from app.agent.workspace_git import reset_workspace, start_run_branch, workspace_status

RUN_ID = "abc123def456"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "cart.ts").write_text(
        "export function total(items) {\n  return 0\n}\n", encoding="utf-8"
    )
    (root / "src" / "dup.ts").write_text("x = 1\nx = 1\n", encoding="utf-8")
    (root / "README.md").write_text("# Shop\n", encoding="utf-8")
    git(root, "init", "--quiet", "-b", "main")
    git(root, "-c", "user.name=t", "-c", "user.email=t@t", "add", "--all")
    git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "--quiet", "-m", "init")
    return root


@pytest.fixture
def tools(repo: Path) -> WorkspaceTools:
    return WorkspaceTools(repo)


@pytest.mark.parametrize(
    "path",
    ["../outside.txt", "src/../../outside.txt", ".git/config", ".git", "", "a\x00b"],
)
def test_resolve_rejects_paths_outside_or_protected(tools: WorkspaceTools, path: str) -> None:
    with pytest.raises(ToolError):
        tools.resolve(path)


def test_resolve_rejects_absolute_paths(tools: WorkspaceTools, tmp_path: Path) -> None:
    with pytest.raises(ToolError, match="outside the repository"):
        tools.resolve(str(tmp_path / "outside.txt"))


def test_resolve_rejects_symlink_escaping_workspace(tools: WorkspaceTools, tmp_path: Path) -> None:
    outside = tmp_path / "secret"
    outside.mkdir()
    try:
        os.symlink(outside, tools.root / "link", target_is_directory=True)
    except OSError:
        pytest.skip("creating symlinks needs extra privileges on this machine")

    with pytest.raises(ToolError, match="outside the repository"):
        tools.resolve("link/key.txt")


def test_read_file_numbers_lines_and_pages(tools: WorkspaceTools) -> None:
    assert tools.read_file("src/cart.ts") == (
        "1| export function total(items) {\n2|   return 0\n3| }"
    )
    assert tools.read_file("src/cart.ts", start_line=2, end_line=2) == "2|   return 0"

    (tools.root / "big.txt").write_text("line\n" * (MAX_READ_LINES + 10), encoding="utf-8")
    page = tools.read_file("big.txt")
    assert f"start_line={MAX_READ_LINES + 1}" in page

    (tools.root / "wide.txt").write_text(("y" * 500 + "\n") * 200, encoding="utf-8")
    assert tools.read_file("wide.txt").endswith("request a smaller line range)")


def test_read_file_errors(tools: WorkspaceTools) -> None:
    (tools.root / "blob.bin").write_bytes(b"\x00\x01")
    with pytest.raises(ToolError, match="binary"):
        tools.read_file("blob.bin")
    with pytest.raises(ToolError, match="does not exist"):
        tools.read_file("missing.ts")
    with pytest.raises(ToolError):
        tools.read_file("src/cart.ts", start_line=0)


def test_list_files_respects_depth_and_skips(tools: WorkspaceTools) -> None:
    (tools.root / "node_modules" / "lib").mkdir(parents=True)
    (tools.root / "src" / "deep").mkdir()
    (tools.root / "src" / "deep" / "x.ts").write_text("", encoding="utf-8")

    shallow = tools.list_files(".", depth=1).splitlines()
    deep = tools.list_files(".", depth=3).splitlines()

    assert shallow == ["src/", "README.md"]
    assert "src/deep/x.ts" in deep
    assert not any("node_modules" in entry or ".git" in entry for entry in deep)


def test_search_code_reports_matches(tools: WorkspaceTools) -> None:
    assert tools.search_code("return 0") == "src/cart.ts:2: return 0"
    assert "No lines contain" in tools.search_code("absent")


def test_write_file_creates_and_updates(tools: WorkspaceTools) -> None:
    assert tools.write_file("src/new/util.ts", "export {}\n").startswith("Created src/new/util.ts")
    assert tools.write_file("README.md", "# New\n").startswith("Updated README.md")
    assert (tools.root / "README.md").read_text(encoding="utf-8") == "# New\n"
    with pytest.raises(ToolError, match="larger than"):
        tools.write_file("big.txt", "x" * (MAX_WRITE_BYTES + 1))
    with pytest.raises(ToolError, match="off-limits"):
        tools.write_file(".git/hooks/pre-commit", "evil")


def test_replace_code_requires_exactly_one_match(tools: WorkspaceTools) -> None:
    assert tools.replace_code("src/cart.ts", "return 0", "return items.length") == (
        "Replaced 1 occurrence in src/cart.ts."
    )
    assert "items.length" in (tools.root / "src" / "cart.ts").read_text(encoding="utf-8")

    with pytest.raises(ToolError, match="not found"):
        tools.replace_code("src/cart.ts", "no such text", "y")
    with pytest.raises(ToolError, match="matches 2 places"):
        tools.replace_code("src/dup.ts", "x = 1", "x = 2")
    with pytest.raises(ToolError, match="must not be empty"):
        tools.replace_code("src/cart.ts", "", "y")


def test_replace_code_handles_crlf_files(tools: WorkspaceTools) -> None:
    (tools.root / "win.ts").write_bytes(b"a = 1\r\nb = 2\r\n")

    tools.replace_code("win.ts", "a = 1\nb = 2", "a = 1\nb = 3")

    assert (tools.root / "win.ts").read_bytes() == b"a = 1\r\nb = 3\r\n"


def test_git_status_and_diff_include_new_files(tools: WorkspaceTools) -> None:
    assert tools.git_status() == "(no changes)"

    tools.replace_code("src/cart.ts", "return 0", "return 1")
    tools.write_file("src/added.ts", "export const added = true\n")
    diff = tools.git_diff()

    assert "-  return 0" in diff and "+  return 1" in diff
    assert "+export const added = true" in diff
    assert "src/added.ts" in tools.git_status()


def test_run_branch_and_reset(repo: Path) -> None:
    branch = start_run_branch(repo, RUN_ID)
    assert git(repo, "branch", "--show-current").strip() == f"patchpilot/{RUN_ID}"

    tools = WorkspaceTools(repo)
    tools.write_file("src/cart.ts", "changed\n")
    tools.write_file("src/untracked.ts", "new\n")
    reset_workspace(repo, branch.base_commit)

    assert workspace_status(repo) == ""
    assert not (repo / "src" / "untracked.ts").exists()


def test_run_branch_rejects_unsafe_ids(repo: Path) -> None:
    with pytest.raises(ValueError):
        start_run_branch(repo, "--force; rm")
