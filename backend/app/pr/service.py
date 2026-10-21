"""Open a GitHub pull request from a finished run, as the signed-in user.

Repos the user can push to get a branch directly; any other public repo is forked into
the user's account first. The commit is built through the Git Data API (blobs -> tree ->
commit -> branch), so nothing is pushed from PatchPilot's shallow clone.
"""

import asyncio
import logging
from functools import lru_cache
from pathlib import Path

import httpx

from app.agent.runs import Run
from app.agent.workspace_git import RUN_BRANCH_PREFIX
from app.auth.sessions import Session
from app.pr.changes import RunChanges, collect_changes
from app.pr.errors import NothingToPublishError, PullRequestInProgressError
from app.pr.github_api import GitHubApi, SleepFn, TreeEntry

logger = logging.getLogger(__name__)

PUBLISHABLE_STATUSES = frozenset({"succeeded", "unverified"})
MAX_TITLE_CHARS = 72
TITLE_PREFIX = "Fix: "
STATUS_SYMBOL = {"pass": "x", "fail": " ", "blocked": " "}


class PullRequestService:
    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: SleepFn = asyncio.sleep,
    ):
        self._transport = transport
        self._sleep = sleep
        self._in_progress: set[str] = set()

    async def open(self, run: Run, workspace: Path, repo_full_name: str, session: Session) -> str:
        """Return the pull request URL; a run that already has one returns it unchanged."""
        if run.pull_request_url:
            return run.pull_request_url
        if run.status not in PUBLISHABLE_STATUSES or not run.diff.strip():
            raise NothingToPublishError(f"run {run.run_id} is {run.status}")
        if run.run_id in self._in_progress:
            raise PullRequestInProgressError(f"run {run.run_id} is already being published")
        self._in_progress.add(run.run_id)
        try:
            changes = await asyncio.to_thread(collect_changes, workspace, run.diff)
            url = await self._publish(run, changes, repo_full_name, session)
        finally:
            self._in_progress.discard(run.run_id)
        run.pull_request_url = url
        logger.info("pull request opened run=%s user=%s", run.run_id, session.user.login)
        return url

    async def _publish(
        self, run: Run, changes: RunChanges, upstream_name: str, session: Session
    ) -> str:
        api = GitHubApi(session.access_token, transport=self._transport, sleep=self._sleep)
        upstream = await api.get_repo(upstream_name)
        if upstream.can_push:
            head_repo = upstream
        else:
            head_repo = await api.create_fork(upstream.full_name)
            await api.wait_for_repo(head_repo.full_name)
            await api.sync_fork(head_repo.full_name, head_repo.default_branch)

        entries = [
            TreeEntry(
                path=file.path,
                mode=file.mode,
                blob_sha=(
                    await api.create_blob(head_repo.full_name, file.content)
                    if file.content is not None
                    else None
                ),
            )
            for file in changes.files
        ]
        tree = await api.create_tree(head_repo.full_name, changes.base_commit, entries)
        user = session.user
        commit = await api.create_commit(
            head_repo.full_name,
            message=pull_request_title(run.issue),
            tree=tree,
            parent=changes.base_commit,
            author={
                "name": user.name or user.login,
                "email": f"{user.id}+{user.login}@users.noreply.github.com",
            },
        )
        branch = f"{RUN_BRANCH_PREFIX}{run.run_id}"
        await api.create_branch(head_repo.full_name, branch, commit)

        head = branch if head_repo is upstream else f"{head_repo.owner}:{branch}"
        return await api.create_pull(
            upstream.full_name,
            head=head,
            base=upstream.default_branch,
            title=pull_request_title(run.issue),
            body=pull_request_body(run, user.login),
            # Unverified fixes open as drafts so maintainers see they still need checking.
            draft=run.status != "succeeded",
        )


def pull_request_title(issue: str) -> str:
    first_line = next((line.strip() for line in issue.splitlines() if line.strip()), "")
    text = first_line.lstrip("-*# ").replace("**", "").replace("`", "")
    limit = MAX_TITLE_CHARS - len(TITLE_PREFIX)
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return f"{TITLE_PREFIX}{text or 'PatchPilot change'}"


def pull_request_body(run: Run, login: str) -> str:
    verified = run.status == "succeeded"
    lines = [
        run.summary.strip() or "Automated fix proposed by PatchPilot.",
        "",
        "### Issue",
        run.issue.strip(),
        "",
        "### Verification",
        (
            "The repository's tests passed in PatchPilot's sandbox."
            if verified
            else "**Not verified.** The tests did not pass or could not run, so review this "
            "change carefully before merging."
        ),
    ]
    results = {result.criterion_id: result.status for result in run.criterion_results}
    for criterion in run.contract.criteria if run.contract else []:
        status = results.get(criterion.id, "blocked")
        lines.append(f"- [{STATUS_SYMBOL[status]}] {criterion.description} ({status})")
    lines += ["", "---", f"Opened with PatchPilot by @{login}."]
    return "\n".join(lines)


@lru_cache
def get_pull_request_service() -> PullRequestService:
    return PullRequestService()
