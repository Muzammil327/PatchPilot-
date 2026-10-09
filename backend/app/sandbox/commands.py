from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.repo.stack import Stack
from app.sandbox.errors import CommandUnavailableError

CommandName = Literal["install", "test", "lint", "build"]
SCRIPT_COMMANDS: tuple[CommandName, ...] = ("test", "lint", "build")

NPM_FLAGS = "--no-audit --no-fund"
# Package managers other than npm ship with Node through corepack.
INSTALL_BY_MANAGER = {
    "npm": f"npm install {NPM_FLAGS}",
    "pnpm": "corepack enable && pnpm install --frozen-lockfile",
    "yarn": "corepack enable && yarn install --frozen-lockfile",
}
RUN_BY_MANAGER = {
    "npm": "npm run {script}",
    "pnpm": "corepack enable && pnpm run {script}",
    "yarn": "corepack enable && yarn run {script}",
}
PYTHON_VENV = ".venv"


@dataclass(frozen=True)
class SandboxCommand:
    name: CommandName
    script: str  # shell script run inside the container; built only from fixed templates
    runtime: Literal["node", "python"]
    needs_network: bool


def resolve_command(workspace: Path, stack: Stack, name: CommandName) -> SandboxCommand:
    """Map a command name to a fixed script for this repo.

    Nothing here comes from the model or the request body except the name, which is
    one of four literals, so no caller can inject an arbitrary shell command.
    """
    if (workspace / "package.json").is_file():
        return resolve_node_command(workspace, stack, name)
    if (workspace / "requirements.txt").is_file() or (workspace / "pyproject.toml").is_file():
        return resolve_python_command(workspace, name)
    raise CommandUnavailableError(
        "This repository has no package.json, requirements.txt or pyproject.toml at its root."
    )


def resolve_node_command(workspace: Path, stack: Stack, name: CommandName) -> SandboxCommand:
    manager = stack.package_manager or "npm"
    if manager not in INSTALL_BY_MANAGER:
        raise CommandUnavailableError(f"The {manager} package manager is not supported yet.")

    if name == "install":
        script = INSTALL_BY_MANAGER[manager]
        if manager == "npm" and (workspace / "package-lock.json").is_file():
            script = f"npm ci {NPM_FLAGS}"
        return SandboxCommand(name=name, script=script, runtime="node", needs_network=True)

    if name not in stack.scripts:
        raise CommandUnavailableError(f'This repository has no "{name}" script in package.json.')
    script = RUN_BY_MANAGER[manager].format(script=name)
    return SandboxCommand(name=name, script=script, runtime="node", needs_network=False)


def resolve_python_command(workspace: Path, name: CommandName) -> SandboxCommand:
    # Containers are thrown away after each command, so dependencies live in a
    # virtualenv inside the (persistent) workspace.
    python = f"{PYTHON_VENV}/bin/python"
    if name == "install":
        target = "-r requirements.txt" if (workspace / "requirements.txt").is_file() else "-e ."
        script = f"python -m venv {PYTHON_VENV} && {python} -m pip install -q {target} pytest"
        return SandboxCommand(name=name, script=script, runtime="python", needs_network=True)
    if name == "test":
        return SandboxCommand(
            name=name, script=f"{python} -m pytest -q", runtime="python", needs_network=False
        )
    raise CommandUnavailableError(f'"{name}" is not available for Python repositories yet.')
