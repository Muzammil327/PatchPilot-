import os
import shutil
import stat
from pathlib import Path


def directory_size_bytes(path: Path) -> int:
    total = 0
    for dirpath, _, filenames in os.walk(path):
        for filename in filenames:
            file_path = os.path.join(dirpath, filename)
            if not os.path.islink(file_path):
                total += os.path.getsize(file_path)
    return total


def remove_workspace(path: Path) -> None:
    """Delete a workspace. Git marks object files read-only, which blocks rmtree on Windows."""
    if not path.exists():
        return
    for dirpath, _, filenames in os.walk(path):
        for filename in filenames:
            file_path = os.path.join(dirpath, filename)
            if not os.path.islink(file_path):
                os.chmod(file_path, stat.S_IWRITE | stat.S_IREAD)
    shutil.rmtree(path)
