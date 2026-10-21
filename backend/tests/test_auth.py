from collections.abc import Iterator
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.auth import SESSION_COOKIE, STATE_COOKIE, require_session
from app.auth.github import GitHubOAuthClient, GitHubUser, get_github_oauth_client
from app.auth.sessions import SessionStore, get_session_store
from app.config import Settings
from app.main import app

FRONTEND = "http://localhost:3000"


def github(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/login/oauth/access_token":
        code = parse_qs(request.content.decode())["code"][0]
        if code != "good-code":
            return httpx.Response(200, json={"error": "bad_verification_code"})
        return httpx.Response(200, json={"access_token": "gho_user", "scope": "public_repo"})
    if request.url.path == "/user":
        assert request.headers["Authorization"] == "Bearer gho_user"
        return httpx.Response(
            200, json={"login": "octocat", "name": "The Octocat", "avatar_url": "https://a/x.png"}
        )
    return httpx.Response(404)


@pytest.fixture
def store() -> SessionStore:
    return SessionStore()


@pytest.fixture
def client(store: SessionStore) -> Iterator[TestClient]:
    settings = Settings(
        _env_file=None,
        github_client_id="client-id",
        github_client_secret="client-secret",
        github_callback_url="http://testserver/api/auth/github/callback",
    )
    app.dependency_overrides.pop(require_session, None)
    app.dependency_overrides[get_github_oauth_client] = lambda: GitHubOAuthClient(
        settings, transport=httpx.MockTransport(github)
    )
    app.dependency_overrides[get_session_store] = lambda: store
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.clear()


def start_login(client: TestClient) -> str:
    response = client.get("/api/auth/github/login")
    assert response.status_code == 303
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert query["scope"] == ["public_repo"]
    assert query["client_id"] == ["client-id"]
    return query["state"][0]


def test_login_signs_the_user_in_and_redirects_to_the_frontend(client: TestClient) -> None:
    state = start_login(client)

    response = client.get(f"/api/auth/github/callback?code=good-code&state={state}")

    assert response.status_code == 303
    assert response.headers["location"] == f"{FRONTEND}/"
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json() == {
        "login": "octocat",
        "name": "The Octocat",
        "avatarUrl": "https://a/x.png",
    }
    assert "gho_user" not in me.text


def test_callback_with_a_wrong_state_does_not_sign_in(
    client: TestClient, store: SessionStore
) -> None:
    start_login(client)

    response = client.get("/api/auth/github/callback?code=good-code&state=forged")

    assert response.headers["location"] == f"{FRONTEND}/?auth=failed"
    assert SESSION_COOKIE not in response.cookies
    assert client.get("/api/auth/me").status_code == 401


def test_callback_without_the_state_cookie_does_not_sign_in(client: TestClient) -> None:
    state = start_login(client)
    client.cookies.delete(STATE_COOKIE, path="/api/auth/github/callback")

    response = client.get(f"/api/auth/github/callback?code=good-code&state={state}")

    assert response.headers["location"] == f"{FRONTEND}/?auth=failed"


def test_rejected_code_redirects_with_a_failure(client: TestClient) -> None:
    state = start_login(client)

    response = client.get(f"/api/auth/github/callback?code=bad-code&state={state}")

    assert response.headers["location"] == f"{FRONTEND}/?auth=failed"
    assert client.get("/api/auth/me").status_code == 401


def test_denied_consent_redirects_with_a_failure(client: TestClient) -> None:
    state = start_login(client)

    response = client.get(f"/api/auth/github/callback?error=access_denied&state={state}")

    assert response.headers["location"] == f"{FRONTEND}/?auth=failed"


def test_api_routes_require_a_session(client: TestClient) -> None:
    assert client.post("/api/repos", json={"url": "https://github.com/a/b"}).status_code == 401
    assert client.get("/api/repos/abc/runs/xyz").status_code == 401
    assert client.get("/health").status_code == 200


def test_write_from_another_origin_is_rejected(client: TestClient) -> None:
    state = start_login(client)
    client.get(f"/api/auth/github/callback?code=good-code&state={state}")

    response = client.post(
        "/api/repos",
        json={"url": "https://github.com/a/b"},
        headers={"Origin": "https://evil.example"},
    )

    assert response.status_code == 403


def test_logout_ends_the_session(client: TestClient) -> None:
    state = start_login(client)
    client.get(f"/api/auth/github/callback?code=good-code&state={state}")

    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_login_without_oauth_config_is_unavailable() -> None:
    app.dependency_overrides.pop(require_session, None)
    app.dependency_overrides[get_github_oauth_client] = lambda: GitHubOAuthClient(
        Settings(_env_file=None)
    )
    try:
        response = TestClient(app, follow_redirects=False).get("/api/auth/github/login")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"detail": "GitHub sign-in is not configured on the server"}


def test_expired_session_is_rejected() -> None:
    now = [1000.0]
    store = SessionStore(clock=lambda: now[0])
    session = store.create(GitHubUser(login="octocat", name=None, avatar_url=""), "token")
    now[0] += 8 * 24 * 60 * 60

    assert store.get(session.session_id) is None
