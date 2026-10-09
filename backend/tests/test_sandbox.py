import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.config import Settings
from app.repo.stack import Stack
from app.sandbox.commands import resolve_command
from app.sandbox.errors import CommandUnavailableError, SandboxUnavailableError
from app.sandbox.runner import (
    MAX_OUTPUT_CHARS,
    TRIMMED_MARKER,
    DockerRunner,
    exclude_dependency_folders,
    trim_output,
)

NPM_STACK = Stack(language="typescript", package_manager="npm", scripts={"test": "vitest run"})


def write(root: Path, files: dict[str, str]) -> Path:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


# --- command resolution ---------------------------------------------------------------


def test_npm_install_uses_ci_with_a_lockfile(tmp_path: Path) -> None:
    write(tmp_path, {"package.json": "{}", "package-lock.json": "{}"})

    command = resolve_command(tmp_path, NPM_STACK, "install")

    assert command.script == "npm ci --no-audit --no-fund"
    assert command.needs_network is True and command.runtime == "node"


def test_npm_install_without_lockfile(tmp_path: Path) -> None:
    write(tmp_path, {"package.json": "{}"})

    assert resolve_command(tmp_path, NPM_STACK, "install").script == (
        "npm install --no-audit --no-fund"
    )


def test_scripts_run_offline_and_must_exist(tmp_path: Path) -> None:
    write(tmp_path, {"package.json": "{}"})

    test = resolve_command(tmp_path, NPM_STACK, "test")

    assert test.script == "npm run test" and test.needs_network is False
    with pytest.raises(CommandUnavailableError, match='no "build" script'):
        resolve_command(tmp_path, NPM_STACK, "build")


def test_pnpm_goes_through_corepack(tmp_path: Path) -> None:
    write(tmp_path, {"package.json": "{}"})
    stack = Stack(language="javascript", package_manager="pnpm", scripts={"lint": "eslint"})

    assert resolve_command(tmp_path, stack, "install").script.startswith("corepack enable && pnpm")
    assert resolve_command(tmp_path, stack, "lint").script == "corepack enable && pnpm run lint"


def test_unsupported_manager_and_unknown_project(tmp_path: Path) -> None:
    write(tmp_path / "bun", {"package.json": "{}"})
    bun = Stack(language="javascript", package_manager="bun")
    with pytest.raises(CommandUnavailableError, match="bun"):
        resolve_command(tmp_path / "bun", bun, "install")

    (tmp_path / "empty").mkdir()
    with pytest.raises(CommandUnavailableError, match="no package.json"):
        resolve_command(tmp_path / "empty", Stack(language="unknown"), "test")


def test_python_commands_use_a_workspace_virtualenv(tmp_path: Path) -> None:
    write(tmp_path, {"requirements.txt": "requests\n"})
    stack = Stack(language="unknown")

    install = resolve_command(tmp_path, stack, "install")
    test = resolve_command(tmp_path, stack, "test")

    assert install.script.startswith("python -m venv .venv && .venv/bin/python -m pip install")
    assert "-r requirements.txt" in install.script and install.runtime == "python"
    assert test.script == ".venv/bin/python -m pytest -q" and not test.needs_network
    with pytest.raises(CommandUnavailableError):
        resolve_command(tmp_path, stack, "lint")


# --- runner -------------------------------------------------------------------------


def test_docker_args_isolate_the_command(tmp_path: Path) -> None:
    write(tmp_path, {"package.json": "{}"})
    runner = DockerRunner(Settings(_env_file=None))
    test = resolve_command(tmp_path, NPM_STACK, "test")
    install = resolve_command(tmp_path, NPM_STACK, "install")

    args = runner.build_args(tmp_path, test, "patchpilot-x")

    assert args[:3] == ["docker", "run", "--rm"]
    assert args[args.index("--network") + 1] == "none"
    assert args[args.index("--memory") + 1] == "2g"
    assert args[args.index("--pids-limit") + 1] == "512"
    assert "--cap-drop" in args and "no-new-privileges" in args
    assert args[args.index("-v") + 1] == f"{tmp_path.resolve()}:/workspace"
    assert args[-4:] == ["node:22-slim", "sh", "-c", "npm run test"]
    install_args = runner.build_args(tmp_path, install, "patchpilot-y")
    assert install_args[install_args.index("--network") + 1] == "bridge"
    # Dependencies go to one Docker volume per repo, shared by install and later commands.
    volume = f"patchpilot-deps-{tmp_path.name}:/workspace/node_modules"
    assert volume in args and volume in install_args


def test_python_dependencies_use_a_volume_for_the_virtualenv(tmp_path: Path) -> None:
    write(tmp_path, {"requirements.txt": ""})
    runner = DockerRunner(Settings(_env_file=None))

    args = runner.build_args(
        tmp_path, resolve_command(tmp_path, Stack(language="unknown"), "test"), "c"
    )

    assert f"patchpilot-deps-{tmp_path.name}:/workspace/.venv" in args
    assert "python:3.12-slim" in args


def test_timeout_kills_the_container(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write(tmp_path, {"package.json": "{}"})
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[1] == "run":
            raise subprocess.TimeoutExpired(args, kwargs["timeout"], output="partial output")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    runner = DockerRunner(Settings(_env_file=None, sandbox_command_timeout_seconds=1))

    result = runner.run(tmp_path, resolve_command(tmp_path, NPM_STACK, "test"))

    assert result.timed_out and not result.passed and result.exit_code == -1
    assert "partial output" in result.output and "timed out after 1s" in result.output
    container = calls[0][calls[0].index("--name") + 1]
    assert calls[1] == ["docker", "kill", container]


def test_missing_docker_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write(tmp_path, {"package.json": "{}"})

    def no_docker(*args, **kwargs):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(subprocess, "run", no_docker)

    with pytest.raises(SandboxUnavailableError):
        DockerRunner(Settings(_env_file=None)).run(
            tmp_path, resolve_command(tmp_path, NPM_STACK, "test")
        )


def test_output_keeps_the_end() -> None:
    long = "start\n" + "x" * (MAX_OUTPUT_CHARS + 100) + "\nFAIL: the important part"

    trimmed = trim_output(long)

    assert trimmed.startswith(TRIMMED_MARKER) and trimmed.endswith("the important part")
    assert trim_output("short") == "short"


def test_dependency_folders_are_excluded_from_git(tmp_path: Path) -> None:
    (tmp_path / ".git" / "info").mkdir(parents=True)
    (tmp_path / ".git" / "info" / "exclude").write_text("# existing", encoding="utf-8")

    exclude_dependency_folders(tmp_path)
    exclude_dependency_folders(tmp_path)  # idempotent

    lines = (tmp_path / ".git" / "info" / "exclude").read_text(encoding="utf-8").splitlines()
    assert lines == ["# existing", "node_modules/", ".venv/"]


# --- real container (skipped without Docker) -------------------------------------------


@pytest.mark.skipif(not docker_available(), reason="Docker is not running")
def test_real_container_runs_offline_and_reports_failure(tmp_path: Path) -> None:
    script = (
        "node -e \"console.log('hello from sandbox');"
        "require('dns').lookup('github.com', e => { console.log(e ? 'offline' : 'online');"
        ' process.exit(3) })"'
    )
    write(tmp_path, {"package.json": json.dumps({"scripts": {"test": script}})})
    runner = DockerRunner(Settings(_env_file=None))

    result = runner.run(tmp_path, resolve_command(tmp_path, NPM_STACK, "test"))

    assert result.exit_code == 3 and not result.passed and not result.timed_out
    assert "hello from sandbox" in result.output
    assert "offline" in result.output
