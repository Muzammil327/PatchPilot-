import asyncio
import logging
import time
from pathlib import Path

from app.agent.commands import CommandSandbox, RepoCommands
from app.agent.errors import ToolError
from app.agent.failures import summarize_failures, summarize_with_model
from app.agent.orchestrator import AgentLimits, AgentRunner, AgentStopped
from app.agent.planner import PlanningFailedError, create_plan, format_plan
from app.agent.runs import Run, RunStore
from app.agent.tools import WorkspaceTools
from app.agent.verification import (
    VerificationContract,
    create_contract,
    ensure_core_criteria,
    result_for,
    review_patch,
)
from app.agent.workspace_git import reset_workspace, run_git, start_run_branch
from app.config import Settings
from app.llm.client import LLMClient, LLMError
from app.repo.search import RankedFile
from app.repo.service import BYTES_PER_KB, RepoService, RepoSummary
from app.sandbox.commands import CommandName
from app.sandbox.errors import CommandUnavailableError, SandboxError
from app.sandbox.runner import CommandResult

logger = logging.getLogger(__name__)

CONTEXT_FILE_COUNT = 8
INSTALL_COMMAND: CommandName = "install"
VERIFY_COMMAND: CommandName = "test"
FEEDBACK_DIFF_CHARS = 2000
NO_TESTS_REASON = "The fix could not be verified: no test command ran in the sandbox."


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


def build_attempt_feedback(run: Run) -> str:
    """What earlier attempts tried and why they failed, for the next plan and edit."""
    blocks: list[str] = []
    for attempt in run.attempts:
        block = [f"Attempt {attempt.n} hypothesis: {attempt.hypothesis}"]
        if attempt.failure_summary:
            block.append(f"Attempt {attempt.n} failure:\n{attempt.failure_summary}")
        if attempt.diff:
            diff = attempt.diff[:FEEDBACK_DIFF_CHARS]
            block.append(f"Attempt {attempt.n} diff (do not repeat this):\n{diff}")
        blocks.append("\n".join(block))
    return "\n\n".join(blocks)


class RunService:
    def __init__(
        self,
        repos: RepoService,
        store: RunStore,
        settings: Settings,
        sandbox: CommandSandbox | None = None,
    ):
        self.repos = repos
        self.store = store
        self.settings = settings
        self.sandbox = sandbox

    def start(self, repo_id: str, issue: str, contract: VerificationContract | None = None) -> Run:
        self.repos.get_record(repo_id)  # 404 before anything is created
        run = self.store.create(repo_id, issue)
        if contract is not None:
            run.contract = ensure_core_criteria(contract)
        return run

    def get(self, repo_id: str, run_id: str) -> Run:
        self.repos.get_record(repo_id)
        return self.store.get(repo_id, run_id)

    def active(self, repo_id: str) -> Run | None:
        self.repos.get_record(repo_id)
        return self.store.active_for(repo_id)

    def cancel(self, repo_id: str, run_id: str) -> Run:
        self.repos.get_record(repo_id)
        return self.store.cancel(repo_id, run_id)

    async def plan_run(
        self,
        run: Run,
        llm: LLMClient,
        context: str,
        workspace: Path,
        ranked: list[RankedFile],
        attempt_n: int,
        feedback: str = "",
    ) -> str:
        """Ask the planner for a plan and add it to the agent's context.

        A failed plan is not fatal: the worker agent can still explore on its own.
        """
        agent_context = context
        if feedback:
            agent_context = (
                f"{context}\n\nPrevious failed attempts (do not repeat these):\n{feedback}"
            )
        try:
            plan = await create_plan(llm, context, workspace, ranked, run.issue, feedback)
        except (PlanningFailedError, LLMError) as exc:
            logger.warning("run %s planning failed: %s", run.run_id, exc)
            run.add_event("model_message", "Planning failed; continuing without a plan")
            return agent_context
        run.plan = plan
        plan_text = format_plan(plan)
        run.add_event("plan", f"Plan ready (attempt {attempt_n})", plan_text)
        return (
            f"{agent_context}\n\nPlan from the planner (verify it against the code):\n{plan_text}"
        )

    async def execute(self, run: Run, llm: LLMClient) -> None:
        """Run the agent to completion. Never raises: every outcome is recorded on the run."""
        if not run.is_active:  # cancelled before it started
            return
        # A separate task, so a cancel interrupts the agent without cancelling the caller.
        task = asyncio.create_task(self._execute(run, llm))
        self.store.attach_task(run.run_id, task)
        try:
            await task
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                raise  # the server is shutting down, not a user cancel
            await self._discard_changes(run)
        finally:
            self.store.detach_task(run.run_id)

    async def _discard_changes(self, run: Run) -> None:
        """Drop a cancelled run's half-made edits; the agent never commits, so HEAD is the base."""
        try:
            workspace = self.repos.get_record(run.repo_id).workspace
            await asyncio.to_thread(reset_workspace, workspace, "HEAD")
        except Exception:
            logger.warning("run %s: could not clean the workspace after cancel", run.run_id)

    async def _execute(self, run: Run, llm: LLMClient) -> None:
        try:
            record = self.repos.get_record(run.repo_id)
            workspace = record.workspace
            # The agent never commits, so HEAD is still the clean base the repo was cloned at.
            base_commit = (await asyncio.to_thread(run_git, workspace, "rev-parse", "HEAD")).strip()
            await asyncio.to_thread(reset_workspace, workspace, base_commit)
            await asyncio.to_thread(start_run_branch, workspace, run.run_id)
            ranked = await self.repos.rank(run.repo_id, run.issue)
            context = build_run_context(record.summary, run.issue, ranked)
            run.add_event("started", "Agent started", context)
        except ToolError as exc:
            logger.error("run %s setup failed: %s", run.run_id, exc)
            run.fail("Could not prepare the repository workspace")
            return
        except Exception:
            logger.exception("run %s setup crashed", run.run_id)
            run.fail("Internal error while preparing the run")
            return

        commands = (
            RepoCommands(self.sandbox, self.repos, run.repo_id)
            if self.sandbox is not None
            else None
        )
        try:
            if run.contract is None:
                run.contract = await create_contract(llm, run.issue)
            run.contract = ensure_core_criteria(run.contract)
            run.add_event(
                "contract",
                "Issue success checklist created",
                run.contract.model_dump_json(by_alias=True),
            )
        except Exception as exc:
            logger.warning("run %s contract generation failed: %s", run.run_id, exc)
            run.error = "Could not create the issue verification checklist."
            run.finish("unverified")
            return
        await self._install(run, commands)
        await self._baseline(run, commands)
        await self._attempt_loop(run, llm, context, workspace, ranked, base_commit, commands)

    async def _install(self, run: Run, commands: RepoCommands | None) -> None:
        if commands is None:
            return
        result = await self._run_command(run, commands, INSTALL_COMMAND)
        if result is not None and not result.passed:
            run.add_event("model_message", "Dependency install failed", result.output)

    async def _baseline(self, run: Run, commands: RepoCommands | None) -> None:
        """Record the tests' state before any edit, so pre-existing failures are not blamed."""
        if commands is None:
            return
        result = await self._run_command(run, commands, VERIFY_COMMAND)
        if result is None:
            return
        run.baseline_output = result.output
        run.add_event(
            "baseline", f"Baseline tests {'passed' if result.passed else 'failed'}", result.output
        )

    async def _attempt_loop(
        self,
        run: Run,
        llm: LLMClient,
        context: str,
        workspace: Path,
        ranked: list[RankedFile],
        base_commit: str,
        commands: RepoCommands | None,
    ) -> None:
        """Patch, test, and retry: up to `agent_max_attempts` or the run time budget."""
        attempt_limit = self.settings.agent_max_attempts
        deadline = time.monotonic() + self.settings.agent_run_timeout_seconds
        last_diff = ""
        last_summary = ""
        last_failure = ""
        review_rounds = 0

        for attempt_n in range(1, attempt_limit + 1):
            run.criterion_results.clear()
            run.review = None
            if time.monotonic() >= deadline:
                run.error = "The run time budget was reached before the tests passed."
                run.finish("unverified", diff=last_diff, summary=last_summary)
                return
            run.add_event("attempt", f"Attempt {attempt_n} of {attempt_limit}")
            feedback = self._feedback(run, attempt_n)
            if self.settings.agent_planning:
                attempt_context = await self.plan_run(
                    run, llm, context, workspace, ranked, attempt_n, feedback
                )
            elif feedback:
                attempt_context = (
                    f"{context}\n\nPrevious failed attempts (do not repeat these):\n{feedback}"
                )
            else:
                attempt_context = context

            tools = WorkspaceTools(
                workspace,
                max_scan_files=self.settings.max_scan_files,
                max_scan_file_bytes=self.settings.max_file_size_kb * BYTES_PER_KB,
            )
            limits = AgentLimits(
                max_steps=self.settings.agent_max_steps,
                timeout_seconds=self.settings.agent_timeout_seconds,
            )
            runner = AgentRunner(
                llm, tools, limits, tool_mode=self.settings.agent_tool_mode, commands=commands
            )
            try:
                outcome = await runner.run(run, attempt_context)
            except AgentStopped as exc:
                run.fail(str(exc))
                return
            except LLMError as exc:
                logger.error("run %s model error: %s", run.run_id, exc)
                run.fail("The model provider request failed")
                return
            except Exception:
                logger.exception("run %s crashed", run.run_id)
                run.fail("Internal error while running the agent")
                return

            if not outcome.has_changes:
                run.finish("no_changes", summary=outcome.summary)
                return
            last_diff, last_summary = outcome.diff, outcome.summary
            hypothesis = run.plan.root_cause if run.plan else outcome.summary

            result = await self._run_command(run, commands, VERIFY_COMMAND)
            if result is None:
                for criterion in run.contract.criteria if run.contract else []:
                    run.criterion_results.append(
                        result_for(
                            criterion.id,
                            "blocked",
                            "The repository test command was unavailable, so this criterion "
                            "was not verified.",
                        )
                    )
                run.record_attempt(attempt_n, hypothesis, outcome.diff, False, NO_TESTS_REASON)
                run.error = NO_TESTS_REASON
                run.finish("unverified", diff=outcome.diff, summary=outcome.summary)
                return
            if result.passed:
                run.add_event("tests_passed", f"Tests passed on attempt {attempt_n}", result.output)
                evidence_parts = [f"Tests passed: {result.output[:1500]}"]
                check_failures: list[str] = []
                for criterion in run.contract.criteria if run.contract else []:
                    if criterion.kind == "tests_pass":
                        run.criterion_results.append(
                            result_for(criterion.id, "pass", result.output)
                        )
                    elif criterion.kind == "test":
                        has_test = any(
                            line.startswith("+++ b/")
                            and any(token in line.lower() for token in ("test", "spec"))
                            for line in outcome.diff.splitlines()
                        )
                        state = "pass" if has_test else "fail"
                        run.criterion_results.append(
                            result_for(
                                criterion.id,
                                state,
                                "Regression test file detected in diff"
                                if has_test
                                else "No test/spec file detected in diff",
                            )
                        )
                        if not has_test and criterion.required:
                            check_failures.append(
                                f"Required regression test missing: {criterion.description}"
                            )
                    elif criterion.kind in ("lint_pass", "build_pass"):
                        command_name: CommandName = (
                            "lint" if criterion.kind == "lint_pass" else "build"
                        )
                        checked = await self._run_command(run, commands, command_name)
                        if checked is None:
                            state, evidence = (
                                "blocked",
                                f"The repository has no runnable {command_name} command.",
                            )
                        else:
                            state, evidence = ("pass" if checked.passed else "fail"), checked.output
                            evidence_parts.append(f"{command_name}: {evidence[:1000]}")
                        run.criterion_results.append(result_for(criterion.id, state, evidence))
                        if state != "pass" and criterion.required:
                            check_failures.append(
                                f"{command_name} check {state}: {criterion.description}\n"
                                f"{evidence[:1000]}"
                            )
                if not check_failures and review_rounds >= self.settings.agent_max_review_rounds:
                    check_failures.append(
                        "Independent reviewer round limit reached without approval."
                    )
                elif not check_failures:
                    try:
                        review_rounds += 1
                        run.review = await review_patch(
                            llm, run.issue, run.contract, outcome.diff, "\n".join(evidence_parts)
                        )
                        run.add_event(
                            "review",
                            f"Independent reviewer: {run.review.verdict}",
                            run.review.model_dump_json(by_alias=True),
                        )
                    except Exception as exc:
                        logger.warning("run %s reviewer failed: %s", run.run_id, exc)
                        check_failures.append(
                            "Independent reviewer did not provide a valid approval."
                        )
                    if run.review and run.review.verdict != "approved":
                        check_failures.extend(
                            f"Reviewer {item.severity}: {item.message}"
                            for item in run.review.findings
                        )
                        if not run.review.findings:
                            check_failures.append(
                                run.review.summary or "Reviewer requested changes."
                            )
                    if run.review and run.review.verdict == "approved":
                        for criterion in run.contract.criteria if run.contract else []:
                            if criterion.kind in ("behavior", "unchanged_api"):
                                run.criterion_results.append(
                                    result_for(
                                        criterion.id,
                                        "pass",
                                        f"Reviewer approved: {run.review.summary}",
                                    )
                                )
                if not check_failures and run.review and run.review.verdict == "approved":
                    run.record_attempt(attempt_n, hypothesis, outcome.diff, True)
                    run.finish("succeeded", diff=outcome.diff, summary=outcome.summary)
                    return
                failure = (
                    "\n".join(check_failures) or "Required checklist criteria remain unresolved."
                )
                last_failure = failure
                for criterion in run.contract.criteria if run.contract else []:
                    if criterion.kind in ("behavior", "unchanged_api") and not any(
                        x.criterion_id == criterion.id for x in run.criterion_results
                    ):
                        run.criterion_results.append(
                            result_for(criterion.id, "fail", failure[:1000])
                        )
                run.record_attempt(attempt_n, hypothesis, outcome.diff, False, failure)
                run.add_event(
                    "verification_failed",
                    f"Verification/review rejected attempt {attempt_n}",
                    failure,
                )
                if attempt_n < attempt_limit:
                    run.add_event("hypothesis_rejected", f"Attempt {attempt_n} rejected", failure)
                    await asyncio.to_thread(reset_workspace, workspace, base_commit)
                    continue
                break

            failure = summarize_failures(result.output)
            failure = await summarize_with_model(llm, result.output, failure)
            last_failure = failure
            for criterion in run.contract.criteria if run.contract else []:
                if criterion.kind == "tests_pass":
                    run.criterion_results.append(result_for(criterion.id, "fail", result.output))
            run.add_event("tests_failed", f"Tests failed on attempt {attempt_n}", result.output)
            run.record_attempt(attempt_n, hypothesis, outcome.diff, False, failure)
            run.plan = None
            if attempt_n < attempt_limit:
                run.add_event("hypothesis_rejected", f"Attempt {attempt_n} rejected", failure)
                await asyncio.to_thread(reset_workspace, workspace, base_commit)

        run.error = (
            last_failure or f"Verification did not pass after {len(run.attempts)} attempt(s)."
        )
        run.finish("unverified", diff=last_diff, summary=last_summary)

    def _feedback(self, run: Run, attempt_n: int) -> str:
        return build_attempt_feedback(run) if attempt_n > 1 else ""

    async def _run_command(
        self, run: Run, commands: RepoCommands | None, name: CommandName
    ) -> CommandResult | None:
        """Run an allow-listed command; None when it cannot run for this repository."""
        if commands is None:
            return None
        try:
            return await commands.run(name)
        except CommandUnavailableError:
            return None
        except SandboxError as exc:
            logger.warning("run %s sandbox %s: %s", run.run_id, name, exc)
            run.add_event("model_message", f"Sandbox could not run {name}: {exc.public_message}")
            return None
