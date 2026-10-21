import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

from app.auth.github import GitHubUser

SESSION_MAX_AGE_SECONDS = 7 * 24 * 60 * 60


@dataclass(frozen=True)
class Session:
    session_id: str
    user: GitHubUser
    # The user's GitHub OAuth token. Server-side only: never logged, never sent to a client.
    access_token: str
    expires_at: float


class SessionStore:
    """In-memory sign-in sessions keyed by a random cookie value. Resets when the backend
    restarts, so everyone signs in again after a deploy."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._sessions: dict[str, Session] = {}
        self._clock = clock

    def create(self, user: GitHubUser, access_token: str) -> Session:
        session = Session(
            session_id=secrets.token_urlsafe(32),
            user=user,
            access_token=access_token,
            expires_at=self._clock() + SESSION_MAX_AGE_SECONDS,
        )
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if session.expires_at <= self._clock():
            del self._sessions[session_id]
            return None
        return session

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)


@lru_cache
def get_session_store() -> SessionStore:
    return SessionStore()
