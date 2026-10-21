"""The GitHub REST calls a pull request needs, made with the signed-in user's token."""

import asyncio
import base64
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

from app.pr.errors import ForkNotReadyError, GitHubAuthError, GitHubRequestError

logger = logging.getLogger(__name__)

API_URL = "https://api.github.com"
API_VERSION = "2022-11-28"
REQUEST_TIMEOUT_SECONDS = 30.0
# A new fork is created asynchronously; poll it for up to ~30s.
FORK_READY_ATTEMPTS = 10
FORK_READY_DELAY_SECONDS = 3.0

SleepFn = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class RepoInfo:
    full_name: str
    owner: str
    default_branch: str
    can_push: bool


@dataclass(frozen=True)
class TreeEntry:
    path: str
    mode: str
    blob_sha: str | None  # None deletes the path


class GitHubApi:
    def __init__(
        self,
        access_token: str,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: SleepFn = asyncio.sleep,
    ):
        self._access_token = access_token
        self._transport = transport
        self._sleep = sleep

    async def get_repo(self, full_name: str) -> RepoInfo:
        body = await self._request("GET", f"/repos/{full_name}")
        return _to_repo_info(body)

    async def create_fork(self, full_name: str) -> RepoInfo:
        """Fork into the user's account; returns the existing fork when there is one."""
        body = await self._request("POST", f"/repos/{full_name}/forks", json={})
        return _to_repo_info(body)

    async def wait_for_repo(self, full_name: str) -> None:
        for attempt in range(FORK_READY_ATTEMPTS):
            try:
                await self._request("GET", f"/repos/{full_name}/git/matching-refs/heads")
                return
            except GitHubRequestError:
                if attempt + 1 == FORK_READY_ATTEMPTS:
                    break
                await self._sleep(FORK_READY_DELAY_SECONDS)
        raise ForkNotReadyError(f"{full_name} was not ready after {FORK_READY_ATTEMPTS} checks")

    async def sync_fork(self, full_name: str, branch: str) -> None:
        """Bring the fork's default branch up to date so the upstream base commit is in it.

        Best effort: a fork that cannot fast-forward still works when the base is reachable.
        """
        try:
            await self._request(
                "POST", f"/repos/{full_name}/merge-upstream", json={"branch": branch}
            )
        except GitHubRequestError as exc:
            logger.info("fork sync skipped for %s: %s", full_name, exc)

    async def create_blob(self, full_name: str, content: bytes) -> str:
        body = await self._request(
            "POST",
            f"/repos/{full_name}/git/blobs",
            json={"content": base64.b64encode(content).decode("ascii"), "encoding": "base64"},
        )
        return _string(body, "sha")

    async def create_tree(self, full_name: str, base_tree: str, entries: list[TreeEntry]) -> str:
        body = await self._request(
            "POST",
            f"/repos/{full_name}/git/trees",
            json={
                "base_tree": base_tree,
                "tree": [
                    {"path": entry.path, "mode": entry.mode, "type": "blob", "sha": entry.blob_sha}
                    for entry in entries
                ],
            },
        )
        return _string(body, "sha")

    async def create_commit(
        self, full_name: str, message: str, tree: str, parent: str, author: dict[str, str]
    ) -> str:
        body = await self._request(
            "POST",
            f"/repos/{full_name}/git/commits",
            json={"message": message, "tree": tree, "parents": [parent], "author": author},
        )
        return _string(body, "sha")

    async def create_branch(self, full_name: str, branch: str, sha: str) -> None:
        await self._request(
            "POST",
            f"/repos/{full_name}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": sha},
        )

    async def create_pull(
        self, full_name: str, head: str, base: str, title: str, body: str, draft: bool
    ) -> str:
        response = await self._request(
            "POST",
            f"/repos/{full_name}/pulls",
            json={"title": title, "head": head, "base": base, "body": body, "draft": draft},
        )
        return _string(response, "html_url")

    async def _request(
        self, method: str, path: str, json: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(
            base_url=API_URL,
            timeout=REQUEST_TIMEOUT_SECONDS,
            transport=self._transport,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._access_token}",
                "X-GitHub-Api-Version": API_VERSION,
            },
        ) as client:
            try:
                response = await client.request(method, path, json=json)
            except httpx.HTTPError as exc:
                raise GitHubRequestError(f"{method} {path} failed: {type(exc).__name__}") from exc
        if response.status_code == httpx.codes.UNAUTHORIZED:
            raise GitHubAuthError(f"{method} {path} returned 401")
        if response.status_code >= httpx.codes.BAD_REQUEST:
            # GitHub's message names the problem (e.g. "Reference already exists"); log only.
            raise GitHubRequestError(
                f"{method} {path} returned {response.status_code}: {_message(response)}"
            )
        body = response.json()
        # A few list endpoints answer with an array; nothing here reads them.
        return body if isinstance(body, dict) else {}


def _message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return ""
    return str(body.get("message", "")) if isinstance(body, dict) else ""


def _string(body: dict[str, Any], key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value:
        raise GitHubRequestError(f"GitHub response has no {key!r}")
    return value


def _to_repo_info(body: dict[str, Any]) -> RepoInfo:
    owner = body.get("owner")
    permissions = body.get("permissions")
    return RepoInfo(
        full_name=_string(body, "full_name"),
        owner=_string(owner, "login") if isinstance(owner, dict) else "",
        default_branch=_string(body, "default_branch"),
        can_push=isinstance(permissions, dict) and permissions.get("push") is True,
    )
