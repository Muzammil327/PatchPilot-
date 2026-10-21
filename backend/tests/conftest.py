from collections.abc import Iterator

import pytest

from app.api.auth import require_session
from app.auth.github import GitHubUser
from app.auth.sessions import Session
from app.main import app

TEST_SESSION = Session(
    session_id="test-session",
    user=GitHubUser(login="octocat", name="The Octocat", avatar_url=""),
    access_token="test-token",
    expires_at=float("inf"),
)


@pytest.fixture(autouse=True)
def signed_in() -> Iterator[None]:
    """Every API test runs signed in; tests/test_auth.py removes this to test the guard."""
    app.dependency_overrides[require_session] = lambda: TEST_SESSION
    yield
    app.dependency_overrides.pop(require_session, None)
