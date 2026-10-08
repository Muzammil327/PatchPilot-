class ToolError(Exception):
    """A tool call the agent made could not be completed.

    The message is returned to the model so it can correct itself, so it must be
    actionable and must not leak host details (absolute paths, stack traces).
    """
