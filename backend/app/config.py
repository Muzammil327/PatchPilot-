from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Single .env at the repository root, shared by every backend module.
ROOT_ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_ENV_FILE, extra="ignore")

    nebius_api_key: str = ""
    nebius_base_url: str = ""
    model_planner: str = ""
    model_worker: str = ""

    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = Field(default=2, ge=0, le=5)

    # Cloned repositories. On a server, point this at a persistent data disk.
    workspace_root: Path = PROJECT_ROOT / "workspaces"
    clone_timeout_seconds: float = Field(default=120.0, gt=0)
    max_repo_size_mb: int = Field(default=200, ge=1)
    max_scan_files: int = Field(default=5000, ge=1)
    max_file_size_kb: int = Field(default=1024, ge=1)

    # Coding agent. "auto" tries native tool calls and falls back to JSON-in-text.
    agent_max_steps: int = Field(default=25, ge=1, le=100)
    agent_timeout_seconds: float = Field(default=300.0, gt=0)
    agent_tool_mode: Literal["auto", "native", "json"] = "auto"
    # Ask the planner model (MODEL_PLANNER) for a plan before the agent edits code.
    agent_planning: bool = True

    # Sandbox: allow-listed commands run in throwaway Docker containers.
    sandbox_node_image: str = "node:22-slim"
    sandbox_python_image: str = "python:3.12-slim"
    sandbox_cpus: float = Field(default=2.0, gt=0)
    sandbox_memory: str = "2g"
    sandbox_pids_limit: int = Field(default=512, ge=32)
    sandbox_install_timeout_seconds: float = Field(default=600.0, gt=0)
    sandbox_command_timeout_seconds: float = Field(default=300.0, gt=0)

    frontend_origin: str = "http://localhost:3000"
    log_level: str = "INFO"

    @property
    def is_llm_configured(self) -> bool:
        required = (
            self.nebius_api_key,
            self.nebius_base_url,
            self.model_planner,
            self.model_worker,
        )
        return all(required)


@lru_cache
def get_settings() -> Settings:
    return Settings()
