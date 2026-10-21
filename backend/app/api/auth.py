"""Continue with GitHub: OAuth login, the session cookie and the signed-in guard."""

import hmac
import logging
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse

from app.api.repos import CamelModel
from app.auth.errors import AuthError, OAuthNotConfiguredError
from app.auth.github import GitHubOAuthClient, get_github_oauth_client
from app.auth.sessions import SESSION_MAX_AGE_SECONDS, Session, SessionStore, get_session_store
from app.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth")

SESSION_COOKIE = "patchpilot_session"
# Binds the OAuth callback to the browser that started the login (login CSRF).
STATE_COOKIE = "patchpilot_oauth_state"
STATE_MAX_AGE_SECONDS = 10 * 60
CALLBACK_PATH = "/api/auth/github/callback"
LOGIN_FAILED_QUERY = "?auth=failed"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

OAuthClientDep = Annotated[GitHubOAuthClient, Depends(get_github_oauth_client)]
SessionStoreDep = Annotated[SessionStore, Depends(get_session_store)]


class UserResponse(CamelModel):
    login: str
    name: str | None
    avatar_url: str


def set_session_cookie(response: Response, session: Session) -> None:
    is_cross_site = get_settings().session_cookie_cross_site
    response.set_cookie(
        SESSION_COOKIE,
        session.session_id,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        secure=is_cross_site,
        samesite="none" if is_cross_site else "lax",
    )


def clear_session_cookie(response: Response) -> None:
    is_cross_site = get_settings().session_cookie_cross_site
    response.delete_cookie(
        SESSION_COOKIE,
        httponly=True,
        secure=is_cross_site,
        samesite="none" if is_cross_site else "lax",
    )


def frontend_redirect(query: str = "") -> RedirectResponse:
    return RedirectResponse(f"{get_settings().frontend_origin}/{query}", status.HTTP_303_SEE_OTHER)


def ensure_allowed_origin(request: Request) -> None:
    # The cookie may be SameSite=None, so reject writes another site's page triggers.
    origin = request.headers.get("origin")
    if request.method not in SAFE_METHODS and origin and origin != get_settings().frontend_origin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Request origin is not allowed")


def require_session(request: Request, sessions: SessionStoreDep) -> Session:
    """Guard for every API route that needs a signed-in GitHub user."""
    ensure_allowed_origin(request)
    session_id = request.cookies.get(SESSION_COOKIE)
    session = sessions.get(session_id) if session_id else None
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in with GitHub to continue")
    return session


@router.get("/github/login")
async def github_login(oauth: OAuthClientDep) -> RedirectResponse:
    state = secrets.token_urlsafe(32)
    try:
        url = oauth.authorize_url(state)
    except OAuthNotConfiguredError as exc:
        logger.error("github login unavailable: %s", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, exc.public_message) from exc
    response = RedirectResponse(url, status.HTTP_303_SEE_OTHER)
    # Lax is enough: GitHub returns to the callback with a top-level navigation.
    response.set_cookie(
        STATE_COOKIE,
        state,
        max_age=STATE_MAX_AGE_SECONDS,
        httponly=True,
        secure=get_settings().session_cookie_cross_site,
        samesite="lax",
        path=CALLBACK_PATH,
    )
    return response


@router.get("/github/callback")
async def github_callback(
    request: Request,
    oauth: OAuthClientDep,
    sessions: SessionStoreDep,
    code: str = "",
    state: str = "",
    error: str = "",
) -> RedirectResponse:
    expected_state = request.cookies.get(STATE_COOKIE, "")
    if error or not code or not state or not hmac.compare_digest(state, expected_state):
        logger.warning("github callback rejected: error=%s has_code=%s", error, bool(code))
        response = frontend_redirect(LOGIN_FAILED_QUERY)
    else:
        try:
            access_token = await oauth.exchange_code(code)
            user = await oauth.fetch_user(access_token)
        except AuthError as exc:
            logger.warning("github login failed: %s", exc)
            response = frontend_redirect(LOGIN_FAILED_QUERY)
        else:
            session = sessions.create(user, access_token)
            logger.info("github login user=%s", user.login)
            response = frontend_redirect()
            set_session_cookie(response, session)
    response.delete_cookie(STATE_COOKIE, path=CALLBACK_PATH)
    return response


@router.get("/me", response_model=UserResponse, response_model_by_alias=True)
async def get_me(session: Annotated[Session, Depends(require_session)]) -> UserResponse:
    user = session.user
    return UserResponse(login=user.login, name=user.name, avatar_url=user.avatar_url)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, sessions: SessionStoreDep) -> None:
    ensure_allowed_origin(request)
    session_id = request.cookies.get(SESSION_COOKIE)
    if session_id:
        sessions.delete(session_id)
    clear_session_cookie(response)
