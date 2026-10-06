import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.repo.errors import (
    CloneFailedError,
    CloneTimeoutError,
    InvalidRepoUrlError,
    RepoUnavailableError,
)

GITHUB_URL_PATTERN = re.compile(
    r"^https://github\.com/"
    r"(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/"
    r"(?P<name>[A-Za-z0-9._-]{1,100}?)"
    r"(?:\.git)?/?$"
)

# Phrases git prints when a repository does not exist or needs credentials.
UNAVAILABLE_MARKERS = ("not found", "could not read username", "authentication failed")


@dataclass(frozen=True)
class GitHubRepoRef:
    owner: str
    name: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"

    @property
    def clone_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.name}.git"


def parse_github_url(url: str) -> GitHubRepoRef:
    match = GITHUB_URL_PATTERN.match(url.strip())
    if not match or match["name"] in {".", ".."}:
        raise InvalidRepoUrlError(f"Rejected repository URL: {url!r}")
    return GitHubRepoRef(owner=match["owner"], name=match["name"])


def clone_repository(ref: GitHubRepoRef, destination: Path, timeout_seconds: float) -> None:
    """Shallow-clone a public repository. Blocking — call it from a worker thread."""
    command = [
        "git",
        "-c",
        "core.symlinks=false",  # check symlinks out as plain files so nothing points outside
        "clone",
        "--depth",
        "1",
        "--single-branch",
        "--no-tags",
        ref.clone_url,
        str(destination),
    ]
    # Never prompt for credentials: a private or missing repo must fail, not hang.
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}

    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout_seconds, env=env
        )
    except subprocess.TimeoutExpired as exc:
        raise CloneTimeoutError(f"Clone of {ref.full_name} timed out") from exc

    if result.returncode != 0:
        stderr = result.stderr.lower()
        if any(marker in stderr for marker in UNAVAILABLE_MARKERS):
            raise RepoUnavailableError(f"{ref.full_name} is missing or private")
        raise CloneFailedError(f"git clone {ref.full_name} exited {result.returncode}")
