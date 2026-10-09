import json
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.llm import get_llm_client
from app.config import Settings
from app.llm.client import LLMClient
from app.main import app
from app.repo.clone import GitHubRepoRef
from app.repo.errors import RepoUnavailableError
from app.repo.service import RepoService, get_repo_service

client = TestClient(app)

REPO_URL = "https://github.com/acme/shop"


def fake_clone(ref: GitHubRepoRef, destination: Path, timeout_seconds: float) -> None:
    (destination / "src").mkdir(parents=True)
    (destination / "src" / "index.ts").write_text(
        'import { z } from "zod"\nexport function main() {}\nclass Shop { open() {} }\n',
        encoding="utf-8",
    )
    (destination / "package.json").write_text(
        json.dumps({"dependencies": {"express": "5"}, "scripts": {"test": "vitest"}}),
        encoding="utf-8",
    )


def use_service(
    workspace_root: Path,
    clone: Callable[[GitHubRepoRef, Path, float], None],
    **overrides: object,
) -> None:
    settings = Settings(_env_file=None, workspace_root=workspace_root, **overrides)
    service = RepoService(settings, clone=clone)
    app.dependency_overrides[get_repo_service] = lambda: service


@pytest.fixture(autouse=True)
def clear_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def test_connect_repo_returns_summary(tmp_path: Path) -> None:
    use_service(tmp_path, fake_clone)

    response = client.post("/api/repos", json={"url": REPO_URL})

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "acme/shop"
    assert body["url"] == REPO_URL
    assert body["stack"] == {
        "language": "typescript",
        "frameworks": ["Express"],
        "packageManager": "npm",
        "scripts": {"test": "vitest"},
    }
    assert body["fileCount"] == 2
    assert body["isTruncated"] is False
    assert [f["path"] for f in body["files"]] == ["package.json", "src/index.ts"]
    assert (body["functionCount"], body["classCount"]) == (1, 1)
    assert (body["routeCount"], body["testFileCount"]) == (0, 0)
    assert (tmp_path / body["repoId"] / "src" / "index.ts").is_file()


def test_get_repo_map_returns_symbols(tmp_path: Path) -> None:
    use_service(tmp_path, fake_clone)
    repo_id = client.post("/api/repos", json={"url": REPO_URL}).json()["repoId"]

    response = client.get(f"/api/repos/{repo_id}/map")

    assert response.status_code == 200
    assert response.json() == {
        "files": [
            {
                "path": "src/index.ts",
                "functions": [{"name": "main", "line": 2}],
                "classes": [{"name": "Shop", "line": 3, "methods": ["open"]}],
                "imports": [{"source": "zod", "names": ["z"]}],
                "exports": ["main"],
            }
        ],
        "parsedCount": 1,
        "failedCount": 0,
        "routes": [],
        "testLinks": [],
    }


def test_get_unknown_repo_map_returns_404(tmp_path: Path) -> None:
    use_service(tmp_path, fake_clone)

    response = client.get("/api/repos/does-not-exist/map")

    assert response.status_code == 404


def test_get_repo_returns_stored_summary(tmp_path: Path) -> None:
    use_service(tmp_path, fake_clone)
    repo_id = client.post("/api/repos", json={"url": REPO_URL}).json()["repoId"]

    response = client.get(f"/api/repos/{repo_id}")

    assert response.status_code == 200
    assert response.json()["repoId"] == repo_id


def test_get_unknown_repo_returns_404(tmp_path: Path) -> None:
    use_service(tmp_path, fake_clone)

    response = client.get("/api/repos/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {"detail": "Repository not found"}


def test_connect_rejects_non_github_url(tmp_path: Path) -> None:
    use_service(tmp_path, fake_clone)

    response = client.post("/api/repos", json={"url": "https://gitlab.com/acme/shop"})

    assert response.status_code == 422
    assert list(tmp_path.iterdir()) == []


def test_connect_reports_missing_repo_and_cleans_up(tmp_path: Path) -> None:
    def failing_clone(ref: GitHubRepoRef, destination: Path, timeout_seconds: float) -> None:
        destination.mkdir()
        raise RepoUnavailableError("missing")

    use_service(tmp_path, failing_clone)

    response = client.post("/api/repos", json={"url": REPO_URL})

    assert response.status_code == 422
    assert response.json() == {"detail": "Repository not found or not public"}
    assert list(tmp_path.iterdir()) == []


def test_connect_rejects_oversized_repo_and_cleans_up(tmp_path: Path) -> None:
    def large_clone(ref: GitHubRepoRef, destination: Path, timeout_seconds: float) -> None:
        destination.mkdir()
        (destination / "blob.txt").write_bytes(b"x" * (1024 * 1024 + 1))

    use_service(tmp_path, large_clone, max_repo_size_mb=1)

    response = client.post("/api/repos", json={"url": REPO_URL})

    assert response.status_code == 413
    assert list(tmp_path.iterdir()) == []


def connect(tmp_path: Path) -> str:
    use_service(tmp_path, fake_clone)
    return client.post("/api/repos", json={"url": REPO_URL}).json()["repoId"]


def use_llm(handler: Callable[[httpx.Request], httpx.Response] | None, **overrides: object) -> None:
    values: dict[str, object] = {
        "nebius_api_key": "test-key",
        "nebius_base_url": "https://llm.test/v1",
        "model_planner": "planner-model",
        "model_worker": "worker-model",
        "llm_max_retries": 0,
    }
    values.update(overrides)
    transport = httpx.MockTransport(handler) if handler else None
    app.dependency_overrides[get_llm_client] = lambda: LLMClient(
        Settings(_env_file=None, **values), transport=transport
    )


def test_search_returns_matching_lines(tmp_path: Path) -> None:
    repo_id = connect(tmp_path)

    response = client.get(f"/api/repos/{repo_id}/search", params={"q": "SHOP"})

    assert response.status_code == 200
    assert response.json() == {
        "matches": [{"path": "src/index.ts", "line": 3, "text": "class Shop { open() {} }"}],
        "isTruncated": False,
    }


def test_relevant_ranks_files_with_reasons(tmp_path: Path) -> None:
    repo_id = connect(tmp_path)

    response = client.get(f"/api/repos/{repo_id}/relevant", params={"q": "shop"})

    assert response.status_code == 200
    files = response.json()["files"]
    assert files[0]["path"] == "src/index.ts"
    assert "symbol: Shop" in files[0]["reasons"]


@pytest.mark.parametrize("query", ["", "   ", "x" * 201])
def test_search_rejects_bad_queries(tmp_path: Path, query: str) -> None:
    repo_id = connect(tmp_path)

    response = client.get(f"/api/repos/{repo_id}/search", params={"q": query})

    assert response.status_code == 422


def test_search_unknown_repo_returns_404(tmp_path: Path) -> None:
    use_service(tmp_path, fake_clone)

    response = client.get("/api/repos/missing/search", params={"q": "shop"})

    assert response.status_code == 404


def test_ask_sends_ranked_files_as_untrusted_context(tmp_path: Path) -> None:
    repo_id = connect(tmp_path)
    sent: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "worker-model",
                # Leading/trailing newlines, as Nemotron sends them, are trimmed.
                "choices": [{"message": {"content": "\n\nShop lives in src/index.ts.\n"}}],
            },
        )

    use_llm(handler)

    response = client.post(f"/api/repos/{repo_id}/ask", json={"question": "Where is the shop?"})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Shop lives in src/index.ts."
    assert body["model"] == "worker-model"
    assert [f["path"] for f in body["files"]] == ["src/index.ts"]
    system, user = sent["messages"]
    assert system["role"] == "system" and "untrusted" in system["content"]
    assert "plain text only" in system["content"]
    assert user["role"] == "user"
    assert '<file path="src/index.ts">' in user["content"]
    assert "3| class Shop { open() {} }" in user["content"]
    assert sent["model"] == "worker-model"


def test_ask_reports_unconfigured_provider(tmp_path: Path) -> None:
    repo_id = connect(tmp_path)
    use_llm(None, nebius_api_key="")

    response = client.post(f"/api/repos/{repo_id}/ask", json={"question": "Where is the shop?"})

    assert response.status_code == 503
    assert response.json() == {"detail": "The model provider is not configured"}


def test_ask_unknown_repo_returns_404(tmp_path: Path) -> None:
    use_service(tmp_path, fake_clone)
    use_llm(None)

    response = client.post("/api/repos/missing/ask", json={"question": "anything"})

    assert response.status_code == 404
