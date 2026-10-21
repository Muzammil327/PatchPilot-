import base64
import json
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agent.runs import RunStatus, RunStore, get_run_store
from app.agent.service import RunService
from app.api.runs import get_run_service
from app.config import Settings
from app.main import app
from app.pr.service import PullRequestService, get_pull_request_service, pull_request_title
from app.repo.clone import GitHubRepoRef
from app.repo.service import RepoService, get_repo_service

client = TestClient(app)

REPO_URL = "https://github.com/acme/shop"
CART = "export function total(items) {\n  return 0\n}\n"


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout


def git_clone(ref: GitHubRepoRef, destination: Path, timeout_seconds: float) -> None:
    (destination / "src").mkdir(parents=True)
    (destination / "src" / "cart.ts").write_text(CART, encoding="utf-8")
    (destination / "OLD.md").write_text("old\n", encoding="utf-8")
    git(destination, "init", "--quiet", "-b", "main")
    git(destination, "add", "--all")
    git(destination, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "--quiet", "-m", "i")


class FakeGitHub:
    def __init__(self, can_push: bool = False, fail_with: int | None = None):
        self.can_push = can_push
        self.fail_with = fail_with
        self.calls: list[tuple[str, str]] = []
        self.blobs: dict[str, bytes] = {}
        self.tree: dict[str, Any] = {}
        self.commit: dict[str, Any] = {}
        self.ref: dict[str, Any] = {}
        self.pull: dict[str, Any] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path))
        assert request.headers["Authorization"] == "Bearer test-token"
        if self.fail_with:
            return httpx.Response(self.fail_with, json={"message": "Bad credentials"})
        body = json.loads(request.content) if request.content else {}
        if path == "/repos/acme/shop" and request.method == "GET":
            return httpx.Response(200, json=repo("acme/shop", "acme", push=self.can_push))
        if path == "/repos/acme/shop/forks":
            return httpx.Response(202, json=repo("octocat/shop", "octocat", push=True))
        if path.endswith("/git/matching-refs/heads"):
            return httpx.Response(200, json=[])
        if path.endswith("/merge-upstream"):
            return httpx.Response(200, json={"merge_type": "fast-forward"})
        if path.endswith("/git/blobs"):
            sha = f"blob{len(self.blobs) + 1}"
            self.blobs[sha] = base64.b64decode(body["content"])
            return httpx.Response(201, json={"sha": sha})
        if path.endswith("/git/trees"):
            self.tree = {"repo": path, **body}
            return httpx.Response(201, json={"sha": "tree1"})
        if path.endswith("/git/commits"):
            self.commit = body
            return httpx.Response(201, json={"sha": "commit1"})
        if path.endswith("/git/refs"):
            self.ref = {"repo": path, **body}
            return httpx.Response(201, json={"ref": body["ref"]})
        if path == "/repos/acme/shop/pulls":
            self.pull = body
            return httpx.Response(201, json={"html_url": "https://github.com/acme/shop/pull/7"})
        return httpx.Response(404, json={"message": "Not Found"})


def repo(full_name: str, owner: str, push: bool) -> dict[str, Any]:
    return {
        "full_name": full_name,
        "owner": {"login": owner},
        "default_branch": "main",
        "permissions": {"push": push},
    }


async def no_sleep(seconds: float) -> None:
    return None


@pytest.fixture
def repo_service(tmp_path: Path) -> Iterator[RepoService]:
    service = RepoService(Settings(_env_file=None, workspace_root=tmp_path), clone=git_clone)
    store = RunStore()
    app.dependency_overrides[get_repo_service] = lambda: service
    app.dependency_overrides[get_run_store] = lambda: store
    app.dependency_overrides[get_run_service] = lambda: RunService(
        service, store, Settings(_env_file=None)
    )
    yield service
    app.dependency_overrides.clear()


def use_github(github: FakeGitHub) -> None:
    service = PullRequestService(transport=httpx.MockTransport(github), sleep=no_sleep)
    app.dependency_overrides[get_pull_request_service] = lambda: service


def finished_run(repo_service: RepoService, status: RunStatus = "unverified") -> tuple[str, str]:
    """Connect the repo and record a finished run whose diff edits, adds and deletes files."""
    repo_id = client.post("/api/repos", json={"url": REPO_URL}).json()["repoId"]
    workspace = repo_service.get_record(repo_id).workspace
    (workspace / "src" / "cart.ts").write_text(CART.replace("0", "items.length"), "utf-8")
    (workspace / "src" / "cart.test.ts").write_text("test('total')\n", encoding="utf-8")
    (workspace / "OLD.md").unlink()
    git(workspace, "add", "--all")
    diff = git(workspace, "diff", "--cached")
    # Later runs reset the working tree, so the PR must come from the stored diff alone.
    git(workspace, "reset", "--quiet", "--hard")
    store: RunStore = app.dependency_overrides[get_run_store]()
    run = store.create(repo_id, "- The `total` function returns 0\n- It should count items")
    run.finish(status, diff=diff, summary="Total now counts the items.")
    return repo_id, run.run_id


def open_pull_request(repo_id: str, run_id: str) -> httpx.Response:
    return client.post(f"/api/repos/{repo_id}/runs/{run_id}/pull-request")


def test_pull_request_from_a_fork_carries_the_run_changes(repo_service: RepoService) -> None:
    github = FakeGitHub(can_push=False)
    use_github(github)
    repo_id, run_id = finished_run(repo_service)

    response = open_pull_request(repo_id, run_id)

    assert response.status_code == 200, response.text
    assert response.json() == {"url": "https://github.com/acme/shop/pull/7"}
    assert ("POST", "/repos/acme/shop/forks") in github.calls
    assert ("POST", "/repos/octocat/shop/merge-upstream") in github.calls
    entries = {entry["path"]: entry for entry in github.tree["tree"]}
    assert set(entries) == {"src/cart.ts", "src/cart.test.ts", "OLD.md"}
    assert entries["OLD.md"]["sha"] is None
    assert github.blobs[entries["src/cart.ts"]["sha"]] == CART.replace("0", "items.length").encode()
    assert github.tree["repo"] == "/repos/octocat/shop/git/trees"
    assert github.commit["parents"] == [github.tree["base_tree"]]
    assert github.commit["author"]["email"] == "583231+octocat@users.noreply.github.com"
    assert github.ref == {
        "repo": "/repos/octocat/shop/git/refs",
        "ref": f"refs/heads/patchpilot/{run_id}",
        "sha": "commit1",
    }
    assert github.pull["head"] == f"octocat:patchpilot/{run_id}"
    assert github.pull["base"] == "main"
    assert github.pull["draft"] is True
    assert github.pull["title"] == "Fix: The total function returns 0"
    assert "Not verified" in github.pull["body"]
    run = client.get(f"/api/repos/{repo_id}/runs/{run_id}").json()
    assert run["pullRequestUrl"] == "https://github.com/acme/shop/pull/7"


def test_opening_twice_returns_the_same_pull_request(repo_service: RepoService) -> None:
    github = FakeGitHub()
    use_github(github)
    repo_id, run_id = finished_run(repo_service)
    open_pull_request(repo_id, run_id)
    calls = len(github.calls)

    response = open_pull_request(repo_id, run_id)

    assert response.json() == {"url": "https://github.com/acme/shop/pull/7"}
    assert len(github.calls) == calls


def test_repo_the_user_can_push_to_gets_a_branch_not_a_fork(repo_service: RepoService) -> None:
    github = FakeGitHub(can_push=True)
    use_github(github)
    repo_id, run_id = finished_run(repo_service, status="succeeded")

    response = open_pull_request(repo_id, run_id)

    assert response.status_code == 200, response.text
    assert ("POST", "/repos/acme/shop/forks") not in github.calls
    assert github.ref["repo"] == "/repos/acme/shop/git/refs"
    assert github.pull["head"] == f"patchpilot/{run_id}"
    assert github.pull["draft"] is False


def test_run_without_changes_cannot_open_a_pull_request(repo_service: RepoService) -> None:
    github = FakeGitHub()
    use_github(github)
    repo_id = client.post("/api/repos", json={"url": REPO_URL}).json()["repoId"]
    store: RunStore = app.dependency_overrides[get_run_store]()
    run = store.create(repo_id, "nothing to do")
    run.finish("no_changes")

    response = open_pull_request(repo_id, run.run_id)

    assert response.status_code == 409
    assert github.calls == []


def test_rejected_github_token_asks_the_user_to_sign_in_again(repo_service: RepoService) -> None:
    use_github(FakeGitHub(fail_with=401))
    repo_id, run_id = finished_run(repo_service)

    response = open_pull_request(repo_id, run_id)

    assert response.status_code == 401
    assert "sign in with GitHub again" in response.json()["detail"]


def test_github_failure_is_a_bad_gateway_without_details(repo_service: RepoService) -> None:
    use_github(FakeGitHub(fail_with=422))
    repo_id, run_id = finished_run(repo_service)

    response = open_pull_request(repo_id, run_id)

    assert response.status_code == 502
    assert response.json() == {"detail": "Could not open the pull request on GitHub"}


def test_title_uses_the_first_line_and_is_capped() -> None:
    assert pull_request_title("**Cart** total is wrong\nmore") == "Fix: Cart total is wrong"
    long_title = pull_request_title("x" * 200)
    assert len(long_title) == 72
    assert long_title.endswith("…")
