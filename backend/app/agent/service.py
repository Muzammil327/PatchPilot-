import asyncio
import logging

from app.agent.errors import ToolError
from app.agent.orchestrator import AgentLimits, AgentRunner
from app.agent.runs import Run, RunStore
from app.agent.tools import WorkspaceTools
from app.agent.workspace_git import reset_workspace, run_git, start_run_branch
from app.config import Settings
from app.llm.client import LLMClient
from app.repo.search import RankedFile
from app.repo.service import BYTES_PER_KB, RepoService, RepoSummary

logger = logging.getLogger(__name__)

CONTEXT_FILE_COUNT = 8


def build_run_context(summary: RepoSummary, issue: str, ranked: list[RankedFile]) -> str:
    stack = summary.stack
    stack_parts = [stack.language, *stack.frameworks]
    if stack.package_manager:
        stack_parts.append(stack.package_manager)
    lines = [
        "Issue:",
        issue,
        "",
        f"Repository: {summary.name} ({', '.join(stack_parts)}; {summary.file_count} files)",
    ]
    if ranked:
        lines += ["", "Likely relevant files (keyword ranking; confirm by reading them):"]
        lines += [
            f"- {file.path} — {', '.join(file.reasons[:3])}" for file in ranked[:CONTEXT_FILE_COUNT]
        ]
    return "\n".join(lines)


class RunService:
    def __init__(self, repos: RepoService, store: RunStore, settings: Settings):
        self.repos = repos
        self.store = store
        self.settings = settings

    def start(self, repo_id: str, issue: str) -> Run:
        self.repos.get_record(repo_id)  # 404 before anything is created
        return self.store.create(repo_id, issue)

    def get(self, repo_id: str, run_id: str) -> Run:
        self.repos.get_record(repo_id)
        return self.store.get(repo_id, run_id)

    async def execute(self, run: Run, llm: LLMClient) -> None:
        """Run the agent to completion. Never raises: every outcome is recorded on the run."""
        try:
            record = self.repos.get_record(run.repo_id)
            workspace = record.workspace
            # The agent never commits, so HEAD is still the clean base the repo was cloned at.
            base_commit = (await asyncio.to_thread(run_git, workspace, "rev-parse", "HEAD")).strip()
            await asyncio.to_thread(reset_workspace, workspace, base_commit)
            await asyncio.to_thread(start_run_branch, workspace, run.run_id)
            ranked = await self.repos.rank(run.repo_id, run.issue)
            context = build_run_context(record.summary, run.issue, ranked)
        except ToolError as exc:
            logger.error("run %s setup failed: %s", run.run_id, exc)
            run.fail("Could not prepare the repository workspace")
            return
        except Exception:
            logger.exception("run %s setup crashed", run.run_id)
            run.fail("Internal error while preparing the run")
            return

        tools = WorkspaceTools(
            workspace,
            max_scan_files=self.settings.max_scan_files,
            max_scan_file_bytes=self.settings.max_file_size_kb * BYTES_PER_KB,
        )
        limits = AgentLimits(
            max_steps=self.settings.agent_max_steps,
            timeout_seconds=self.settings.agent_timeout_seconds,
        )
        runner = AgentRunner(llm, tools, limits, tool_mode=self.settings.agent_tool_mode)
        await runner.run(run, context)
        logger.info("run %s finished status=%s steps=%d", run.run_id, run.status, run.steps)
