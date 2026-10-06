class RepoError(Exception):
    """Base repository error. `public_message` is safe to show to clients; the
    exception message is internal detail for logs only."""

    public_message = "The repository request failed"


class InvalidRepoUrlError(RepoError):
    public_message = "Enter a public GitHub repository URL like https://github.com/owner/repo"


class RepoUnavailableError(RepoError):
    public_message = "Repository not found or not public"


class RepoTooLargeError(RepoError):
    public_message = "Repository is larger than the allowed size"


class CloneTimeoutError(RepoError):
    public_message = "Cloning the repository took too long"


class CloneFailedError(RepoError):
    public_message = "Cloning the repository failed"


class RepoNotFoundError(RepoError):
    public_message = "Repository not found"
