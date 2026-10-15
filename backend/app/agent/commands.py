from typing import Protocol

from app.repo.service import RepoService
from app.sandbox.commands import CommandName
from app.sandbox.runner import CommandResult


class CommandSandbox(Protocol):
    """The slice of the sandbox the agent needs: run one allow-listed command."""

    async def run(self, repos: RepoService, repo_id: str, name: CommandName) -> CommandResult: ...


def format_result(result: CommandResult) -> str:
    """The result as plain text for the model, with the command and exit code stated."""
    status = "timed out" if result.timed_out else f"exit {result.exit_code}"
    return f"run_command({result.name}) {status}: {result.command}\n{result.output}"


class RepoCommands:
    """Runs allow-listed commands for one repository through the sandbox."""

    def __init__(self, sandbox: CommandSandbox, repos: RepoService, repo_id: str):
        self.sandbox = sandbox
        self.repos = repos
        self.repo_id = repo_id
        self.last: CommandResult | None = None

    async def run(self, name: CommandName) -> CommandResult:
        result = await self.sandbox.run(self.repos, self.repo_id, name)
        self.last = result
        return result
