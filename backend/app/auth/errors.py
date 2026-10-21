class AuthError(Exception):
    """Base sign-in error. `public_message` is safe for clients; the message is for logs."""

    public_message = "GitHub sign-in failed"


class OAuthNotConfiguredError(AuthError):
    public_message = "GitHub sign-in is not configured on the server"


class OAuthExchangeError(AuthError):
    """GitHub rejected the code exchange or the user lookup."""
