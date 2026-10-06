import os
from dataclasses import dataclass
from pathlib import Path

SKIPPED_DIRS = frozenset(
    {".git", "node_modules", "dist", "build", ".next", "out", "coverage", ".turbo", ".cache"}
)

LANGUAGE_BY_EXTENSION = {
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
}
OTHER_LANGUAGE = "other"

BINARY_EXTENSIONS = frozenset(
    {
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".svgz",
        ".pdf", ".zip", ".gz", ".tgz", ".tar", ".7z", ".rar",
        ".woff", ".woff2", ".ttf", ".otf", ".eot",
        ".mp3", ".mp4", ".mov", ".avi", ".webm", ".wav",
        ".exe", ".dll", ".so", ".dylib", ".bin", ".wasm", ".lockb",
    }
)  # fmt: skip


@dataclass(frozen=True)
class ScannedFile:
    path: str  # POSIX-style, relative to the workspace root
    language: str
    size_bytes: int


@dataclass(frozen=True)
class ScanResult:
    files: list[ScannedFile]
    skipped_count: int  # files skipped as binary, symlink, or too large
    is_truncated: bool  # stopped at the file limit


def scan_workspace(root: Path, max_files: int, max_file_size_bytes: int) -> ScanResult:
    files: list[ScannedFile] = []
    skipped_count = 0

    for dirpath, dirnames, filenames in os.walk(root):
        # Prune in place so os.walk never descends; sort for a deterministic order.
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name not in SKIPPED_DIRS and not os.path.islink(os.path.join(dirpath, name))
        )
        for filename in sorted(filenames):
            file_path = os.path.join(dirpath, filename)
            extension = os.path.splitext(filename)[1].lower()
            if os.path.islink(file_path) or extension in BINARY_EXTENSIONS:
                skipped_count += 1
                continue
            size = os.path.getsize(file_path)
            if size > max_file_size_bytes:
                skipped_count += 1
                continue
            if len(files) >= max_files:
                return ScanResult(files=files, skipped_count=skipped_count, is_truncated=True)
            files.append(
                ScannedFile(
                    path=Path(file_path).relative_to(root).as_posix(),
                    language=LANGUAGE_BY_EXTENSION.get(extension, OTHER_LANGUAGE),
                    size_bytes=size,
                )
            )

    return ScanResult(files=files, skipped_count=skipped_count, is_truncated=False)
