"""GitHub OAuth App web flow: authorize URL, code exchange and the signed-in user."""

from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlencode

import httpx

from app.auth.errors import OAuthExchangeError, OAuthNotConfiguredError
from app.config import Settings, get_settings

AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
USER_URL = "https://api.github.com/user"
# public_repo now so the later "Create PR" step (fork, push, open PR) needs no second consent.
OAUTH_SCOPE = "public_repo"
REQUEST_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True)
class GitHubUser:
    login: str
    name: str | None
    avatar_url: str


class GitHubOAuthClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self._transport = transport

    def ensure_configured(self) -> None:
        if not self.settings.is_github_oauth_configured:
            raise OAuthNotConfiguredError("GITHUB_CLIENT_ID/SECRET/CALLBACK_URL are not set")

    def authorize_url(self, state: str) -> str:
        self.ensure_configured()
        query = urlencode(
            {
                "client_id": self.settings.github_client_id,
                "redirect_uri": self.settings.github_callback_url,
                "scope": OAUTH_SCOPE,
                "state": state,
                "allow_signup": "true",
            }
        )
        return f"{AUTHORIZE_URL}?{query}"

    async def exchange_code(self, code: str) -> str:
        """Swap the callback code for the user's access token."""
        self.ensure_configured()
        async with self._client() as client:
            response = await client.post(
                TOKEN_URL,
                data={
                    "client_id": self.settings.github_client_id,
                    "client_secret": self.settings.github_client_secret,
                    "code": code,
                    "redirect_uri": self.settings.github_callback_url,
                },
            )
        if response.status_code != httpx.codes.OK:
            raise OAuthExchangeError(f"token exchange returned HTTP {response.status_code}")
        body = response.json()
        # GitHub reports a bad or expired code as 200 with an "error" field.
        token = body.get("access_token") if isinstance(body, dict) else None
        if not isinstance(token, str) or not token:
            error = body.get("error") if isinstance(body, dict) else None
            raise OAuthExchangeError(f"token exchange failed: {error or 'no access_token'}")
        return token

    async def fetch_user(self, access_token: str) -> GitHubUser:
        async with self._client() as client:
            response = await client.get(
                USER_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
        if response.status_code != httpx.codes.OK:
            raise OAuthExchangeError(f"user lookup returned HTTP {response.status_code}")
        body = response.json()
        login = body.get("login") if isinstance(body, dict) else None
        if not isinstance(login, str) or not login:
            raise OAuthExchangeError("user lookup returned no login")
        name = body.get("name")
        avatar_url = body.get("avatar_url")
        return GitHubUser(
            login=login,
            name=name if isinstance(name, str) and name else None,
            avatar_url=avatar_url if isinstance(avatar_url, str) else "",
        )

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT_SECONDS,
            transport=self._transport,
            headers={"Accept": "application/json"},
        )


@lru_cache
def get_github_oauth_client() -> GitHubOAuthClient:
    return GitHubOAuthClient(get_settings())
