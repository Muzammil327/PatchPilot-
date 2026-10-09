import logging
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.sandbox.commands import SandboxCommand
from app.sandbox.errors import SandboxUnavailableError

logger = logging.getLogger(__name__)

MAX_OUTPUT_CHARS = 20_000
TRIMMED_MARKER = "… (earlier output trimmed)\n"
CONTAINER_WORKDIR = "/workspace"
DOCKER_DAEMON_ERROR_EXIT = 125  # `docker run` itself failed (daemon down, bad flag, image)
KILL_TIMEOUT_SECONDS = 30
# Dependency folders the sandbox creates; never part of the agent's diff.
GIT_EXCLUDES = ("node_modules/", ".venv/")
# Dependencies live in a Docker volume per repo instead of the bind-mounted folder:
# writing tens of thousands of small files through Windows folder sharing (and into
# OneDrive) made `npm ci` time out, while the volume stays on Docker's Linux storage.
DEPENDENCY_DIR_BY_RUNTIME = {"node": "node_modules", "python": ".venv"}
DEPENDENCY_VOLUME_PREFIX = "patchpilot-deps-"


@dataclass(frozen=True)
class CommandResult:
    name: str
    command: str
    exit_code: int
    output: str
    duration_ms: int
    timed_out: bool

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


def trim_output(output: str) -> str:
    """Keep the end: test failures and build errors are reported last."""
    if len(output) <= MAX_OUTPUT_CHARS:
        return output
    return TRIMMED_MARKER + output[-MAX_OUTPUT_CHARS:]


class DockerRunner:
    """Runs allow-listed commands in a throwaway container with the workspace mounted."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def image_for(self, command: SandboxCommand) -> str:
        if command.runtime == "python":
            return self.settings.sandbox_python_image
        return self.settings.sandbox_node_image

    def timeout_for(self, command: SandboxCommand) -> float:
        if command.name == "install":
            return self.settings.sandbox_install_timeout_seconds
        return self.settings.sandbox_command_timeout_seconds

    def build_args(self, workspace: Path, command: SandboxCommand, container: str) -> list[str]:
        settings = self.settings
        return [
            "docker", "run", "--rm",
            "--name", container,
            # Network only while installing dependencies; tests and builds run offline.
            "--network", "bridge" if command.needs_network else "none",
            "--cpus", str(settings.sandbox_cpus),
            "--memory", settings.sandbox_memory,
            "--pids-limit", str(settings.sandbox_pids_limit),
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "-v", f"{workspace.resolve()}:{CONTAINER_WORKDIR}",
            "-v", f"{dependency_volume(workspace)}:{dependency_mount(command)}",
            "-w", CONTAINER_WORKDIR,
            "-e", "CI=true",
            "-e", "npm_config_update_notifier=false",
            self.image_for(command),
            "sh", "-c", command.script,
        ]  # fmt: skip

    def run(self, workspace: Path, command: SandboxCommand) -> CommandResult:
        """Blocking; call from a worker thread."""
        exclude_dependency_folders(workspace)
        container = f"patchpilot-{uuid.uuid4().hex[:12]}"
        args = self.build_args(workspace, command, container)
        timeout = self.timeout_for(command)
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            raise SandboxUnavailableError("docker executable not found") from exc
        except subprocess.TimeoutExpired as exc:
            # Killing the CLI does not stop the container, so stop it by name.
            self.kill(container)
            partial = exc.stdout or ""
            if isinstance(partial, bytes):
                partial = partial.decode("utf-8", errors="replace")
            return CommandResult(
                name=command.name,
                command=command.script,
                exit_code=-1,
                output=trim_output(partial + f"\n… timed out after {timeout:.0f}s"),
                duration_ms=int((time.perf_counter() - started) * 1000),
                timed_out=True,
            )

        output = completed.stdout or ""
        if completed.returncode == DOCKER_DAEMON_ERROR_EXIT and "docker" in output.lower():
            logger.error("docker run failed to start: %s", output[:300])
            raise SandboxUnavailableError("docker run could not start the container")
        return CommandResult(
            name=command.name,
            command=command.script,
            exit_code=completed.returncode,
            output=trim_output(output),
            duration_ms=int((time.perf_counter() - started) * 1000),
            timed_out=False,
        )

    def kill(self, container: str) -> None:
        try:
            subprocess.run(
                ["docker", "kill", container],
                capture_output=True,
                timeout=KILL_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired):
            logger.warning("could not kill timed-out container %s", container)


def dependency_volume(workspace: Path) -> str:
    """One volume per workspace (the folder name is the repo id), shared by all its commands."""
    return f"{DEPENDENCY_VOLUME_PREFIX}{workspace.name}"


def dependency_mount(command: SandboxCommand) -> str:
    return f"{CONTAINER_WORKDIR}/{DEPENDENCY_DIR_BY_RUNTIME[command.runtime]}"


def exclude_dependency_folders(workspace: Path) -> None:
    """Keep installed dependencies out of `git status`/`git diff` even if the repo's
    own .gitignore forgets them."""
    exclude = workspace / ".git" / "info" / "exclude"
    if not exclude.parent.is_dir():
        return
    existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    missing = [entry for entry in GIT_EXCLUDES if entry not in existing.splitlines()]
    if missing:
        with exclude.open("a", encoding="utf-8") as handle:
            handle.write(
                ("\n" if existing and not existing.endswith("\n") else "")
                + "\n".join(missing)
                + "\n"
            )
