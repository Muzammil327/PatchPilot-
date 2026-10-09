import asyncio
import logging
from functools import lru_cache

from app.config import Settings, get_settings
from app.repo.service import RepoService
from app.sandbox.commands import CommandName, resolve_command
from app.sandbox.errors import SandboxBusyError
from app.sandbox.runner import CommandResult, DockerRunner

logger = logging.getLogger(__name__)


class SandboxService:
    """Runs one sandbox command at a time per repository, so two installs never race
    on the same node_modules."""

    def __init__(self, runner: DockerRunner):
        self.runner = runner
        self._busy: set[str] = set()

    async def run(self, repos: RepoService, repo_id: str, name: CommandName) -> CommandResult:
        record = repos.get_record(repo_id)
        command = resolve_command(record.workspace, record.summary.stack, name)
        if repo_id in self._busy:
            raise SandboxBusyError(f"repo {repo_id} already has a command running")
        self._busy.add(repo_id)
        try:
            result = await asyncio.to_thread(self.runner.run, record.workspace, command)
        finally:
            self._busy.discard(repo_id)
        logger.info(
            "sandbox %s repo=%s exit=%s timed_out=%s duration_ms=%d",
            name,
            repo_id,
            result.exit_code,
            result.timed_out,
            result.duration_ms,
        )
        return result


@lru_cache
def get_sandbox_service() -> SandboxService:
    return SandboxService(DockerRunner(get_settings()))


def build_sandbox_service(settings: Settings) -> SandboxService:
    return SandboxService(DockerRunner(settings))
