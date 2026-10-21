class PullRequestError(Exception):
    """Base pull request error. `public_message` is safe for clients; the message is for logs."""

    public_message = "Could not open the pull request on GitHub"


class NothingToPublishError(PullRequestError):
    public_message = "This run has no finished changes to open a pull request for"


class PullRequestInProgressError(PullRequestError):
    public_message = "A pull request is already being opened for this run"


class GitHubAuthError(PullRequestError):
    public_message = "GitHub did not accept your sign-in. Sign out and sign in with GitHub again."


class ForkNotReadyError(PullRequestError):
    public_message = "GitHub is still creating your fork. Try again in a minute."


class PatchApplyError(PullRequestError):
    public_message = "The run's changes could not be turned into a commit"


class GitHubRequestError(PullRequestError):
    """Any other GitHub API failure."""
