class SandboxError(Exception):
    """Base sandbox error. `public_message` is safe for clients; the message is for logs."""

    public_message = "The sandbox command failed to start"


class CommandUnavailableError(SandboxError):
    def __init__(self, public_message: str):
        super().__init__(public_message)
        self.public_message = public_message


class SandboxUnavailableError(SandboxError):
    public_message = "The sandbox is not available. Is Docker running?"


class SandboxBusyError(SandboxError):
    public_message = "Another command is already running for this repository"
