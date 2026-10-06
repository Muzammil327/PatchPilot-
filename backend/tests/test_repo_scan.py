import os
from pathlib import Path

import pytest

from app.repo.scan import scan_workspace

MAX_FILE_SIZE = 1024


def write(root: Path, relative: str, content: str | bytes = "x") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def test_scan_lists_source_files_and_skips_noise(tmp_path: Path) -> None:
    write(tmp_path, "src/index.ts")
    write(tmp_path, "src/app.jsx")
    write(tmp_path, "README.md")
    write(tmp_path, "node_modules/lib/index.js")
    write(tmp_path, ".git/config")
    write(tmp_path, ".next/server.js")
    write(tmp_path, "public/logo.png", b"\x89PNG")
    write(tmp_path, "data/huge.json", "x" * (MAX_FILE_SIZE + 1))

    result = scan_workspace(tmp_path, max_files=100, max_file_size_bytes=MAX_FILE_SIZE)

    assert [(f.path, f.language) for f in result.files] == [
        ("README.md", "other"),
        ("src/app.jsx", "javascript"),
        ("src/index.ts", "typescript"),
    ]
    assert result.skipped_count == 2  # logo.png (binary) + huge.json (too large)
    assert result.is_truncated is False


def test_scan_stops_at_file_limit(tmp_path: Path) -> None:
    for index in range(5):
        write(tmp_path, f"file{index}.ts")

    result = scan_workspace(tmp_path, max_files=3, max_file_size_bytes=MAX_FILE_SIZE)

    assert len(result.files) == 3
    assert result.is_truncated is True


def test_scan_does_not_follow_symlinks(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    write(outside, "secret.ts")
    workspace = tmp_path / "workspace"
    write(workspace, "index.ts")
    try:
        os.symlink(outside, workspace / "linked-dir", target_is_directory=True)
        os.symlink(outside / "secret.ts", workspace / "linked.ts")
    except OSError:
        pytest.skip("creating symlinks needs extra privileges on this machine")

    result = scan_workspace(workspace, max_files=100, max_file_size_bytes=MAX_FILE_SIZE)

    assert [f.path for f in result.files] == ["index.ts"]
