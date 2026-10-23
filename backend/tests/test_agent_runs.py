import asyncio
import json
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agent.orchestrator import parse_json_action
from app.agent.runs import RunStore, get_run_store
from app.agent.service import RunService
from app.agent.verification import Criterion, VerificationContract
from app.api.llm import get_llm_client
from app.api.runs import get_run_service
from app.config import Settings
from app.llm.client import LLMClient
from app.main import app
from app.repo.clone import GitHubRepoRef
from app.repo.service import RepoService, get_repo_service
from app.sandbox.commands import CommandName
from app.sandbox.errors import CommandUnavailableError, SandboxUnavailableError
from app.sandbox.runner import CommandResult

client = TestClient(app)

REPO_URL = "https://github.com/acme/shop"
CART = "export function total(items) {\n  return 0\n}\n"
LLM_SETTINGS: dict[str, Any] = {
    "nebius_api_key": "test-key",
    "nebius_base_url": "https://llm.test/v1",
    "model_planner": "planner-model",
    "model_worker": "worker-model",
    "llm_max_retries": 0,
}


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def git_clone(ref: GitHubRepoRef, destination: Path, timeout_seconds: float) -> None:
    (destination / "src").mkdir(parents=True)
    (destination / "src" / "cart.ts").write_text(CART, encoding="utf-8")
    git(destination, "init", "--quiet", "-b", "main")
    git(destination, "add", "--all")
    git(destination, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "--quiet", "-m", "i")


def tool_call_reply(*calls: tuple[str, dict[str, Any]]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "worker-model",
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": f"call_{index}",
                                "type": "function",
                                "function": {"name": name, "arguments": json.dumps(args)},
                            }
                            for index, (name, args) in enumerate(calls)
                        ],
                    }
                }
            ],
        },
    )


def text_reply(content: str) -> httpx.Response:
    return httpx.Response(
        200, json={"model": "worker-model", "choices": [{"message": {"content": content}}]}
    )


def command_result(name: str, *, passed: bool = True, output: str = "") -> CommandResult:
    return CommandResult(
        name=name,
        command=name,
        exit_code=0 if passed else 1,
        output=output or ("ok" if passed else "1 failed"),
        duration_ms=1,
        timed_out=False,
    )


class FakeSandbox:
    """A sandbox whose command results are scripted, so runs are deterministic and offline."""

    def __init__(
        self,
        *results: CommandResult,
        passed: bool = True,
        unavailable: tuple[str, ...] = (),
        is_down: bool = False,
    ):
        self.results = list(results)
        self.is_down = is_down
        self.passed = passed
        self.unavailable = set(unavailable)
        self.calls: list[str] = []

    async def run(self, repos: RepoService, repo_id: str, name: CommandName) -> CommandResult:
        self.calls.append(name)
        if self.is_down:
            raise SandboxUnavailableError("docker executable not found")
        if name in self.unavailable:
            raise CommandUnavailableError(f'This repository has no "{name}" command.')
        if self.results:
            return self.results.pop(0)
        return command_result(name, passed=self.passed)


class ScriptedModel:
    """Plays back canned provider responses and records every request body."""

    def __init__(self, *replies: httpx.Response):
        self.replies = list(replies)
        self.requests: list[dict[str, Any]] = []
        self.contract_requests: list[dict[str, Any]] = []
        self.review_requests: list[dict[str, Any]] = []
        self.review_replies: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        system = body["messages"][0]["content"]
        if "Create a concise issue-specific success checklist" in system:
            self.contract_requests.append(body)
            return text_reply(
                json.dumps(
                    {
                        "criteria": [
                            {
                                "id": "behavior",
                                "description": "The issue behavior is fixed",
                                "kind": "behavior",
                                "required": True,
                            }
                        ]
                    }
                )
            )
        if "independent senior code reviewer" in system:
            self.review_requests.append(body)
            if self.review_replies:
                return text_reply(json.dumps(self.review_replies.pop(0)))
            return text_reply(
                json.dumps(
                    {"verdict": "approved", "summary": "Patch meets the checklist", "findings": []}
                )
            )
        if "You summarize failing test output" in system:
            return text_reply(
                "The repository test failed; inspect the reported test and repair the cause."
            )
        self.requests.append(body)
        return self.replies.pop(0) if self.replies else text_reply("Done.")


@pytest.fixture
def repo_service(tmp_path: Path) -> RepoService:
    service = RepoService(Settings(_env_file=None, workspace_root=tmp_path), clone=git_clone)
    store = RunStore()
    app.dependency_overrides[get_repo_service] = lambda: service
    app.dependency_overrides[get_run_store] = lambda: store
    use_agent_settings(service)
    return service


@pytest.fixture(autouse=True)
def clear_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def connect() -> str:
    return client.post("/api/repos", json={"url": REPO_URL}).json()["repoId"]


def use_model(model: ScriptedModel | None, **overrides: Any) -> None:
    settings = Settings(_env_file=None, **{**LLM_SETTINGS, **overrides})
    transport = httpx.MockTransport(model) if model else None
    app.dependency_overrides[get_llm_client] = lambda: LLMClient(settings, transport=transport)


def use_agent_settings(
    repo_service: RepoService, sandbox: FakeSandbox | None = None, **overrides: Any
) -> FakeSandbox:
    # Planning is off unless a test asks for it, so scripted replies map to agent steps.
    settings = Settings(_env_file=None, **{"agent_planning": False, **overrides})
    store = app.dependency_overrides[get_run_store]()
    fake = sandbox or FakeSandbox()
    app.dependency_overrides[get_run_service] = lambda: RunService(
        repo_service, store, settings, fake
    )
    return fake


def start_run(
    repo_id: str,
    issue: str = "Total should count the items",
    contract_edit: tuple[str, str] | None = None,
) -> dict[str, Any]:
    contract = client.post(f"/api/repos/{repo_id}/runs/contract", json={"issue": issue})
    assert contract.status_code == 200, contract.text
    contract_body = contract.json()
    if contract_edit:
        criterion = next(
            item for item in contract_body["criteria"] if item["id"] == contract_edit[0]
        )
        criterion["description"] = contract_edit[1]
    created = client.post(
        f"/api/repos/{repo_id}/runs",
        json={"issue": issue, "verificationContract": contract_body},
    )
    assert created.status_code == 202, created.text
    # TestClient finishes background tasks before returning, so the run is complete here.
    run_id = created.json()["runId"]
    return client.get(f"/api/repos/{repo_id}/runs/{run_id}").json()


def test_native_run_edits_code_and_returns_diff(repo_service: RepoService) -> None:
    repo_id = connect()
    model = ScriptedModel(
        tool_call_reply(("read_file", {"path": "src/cart.ts"})),
        tool_call_reply(
            (
                "replace_code",
                {"path": "src/cart.ts", "old": "return 0", "new": "return items.length"},
            )
        ),
        text_reply("Total now returns the number of items."),
    )
    use_model(model)

    run = start_run(repo_id, contract_edit=("behavior", "The cart total reflects item count"))

    assert run["status"] == "succeeded", (
        run["status"],
        [
            (r["model"], r["messages"][0]["content"][:80], r["messages"][1]["content"][:150])
            for r in model.requests
        ],
    )
    assert run["summary"] == "Total now returns the number of items."
    assert "-  return 0" in run["diff"] and "+  return items.length" in run["diff"]
    assert run["steps"] == 3
    assert run["review"]["verdict"] == "approved"
    assert (
        next(item for item in run["contract"]["criteria"] if item["id"] == "behavior")[
            "description"
        ]
        == "The cart total reflects item count"
    )
    assert {item["status"] for item in run["criterionResults"]} == {"pass"}
    assert model.review_requests[0]["messages"][0]["content"].startswith("You are an independent")
    assert not any(
        "root cause" in message.get("content", "").lower()
        for message in model.review_requests[0]["messages"]
    )
    assert [event["type"] for event in run["events"]] == [
        "started",
        "contract",
        "baseline",
        "attempt",
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_result",
        "tests_passed",
        "review",
        "finished",
    ]
    first = model.requests[0]
    assert first["model"] == "worker-model"
    assert {tool["function"]["name"] for tool in first["tools"]} >= {"read_file", "replace_code"}
    system, user = first["messages"]
    assert "untrusted" in system["content"]
    assert "plain text" in system["content"]
    assert user["content"].startswith("Issue:\nTotal should count the items")
    tool_message = model.requests[1]["messages"][-1]
    assert tool_message["role"] == "tool" and "1| export function total" in tool_message["content"]


def test_reviewer_rejection_is_fed_into_a_repair_attempt(repo_service: RepoService) -> None:
    repo_id = connect()
    model = ScriptedModel(
        tool_call_reply(
            (
                "replace_code",
                {"path": "src/cart.ts", "old": "return 0", "new": "return items.length"},
            )
        ),
        text_reply("Fixed the total."),
        tool_call_reply(("read_file", {"path": "src/cart.ts"})),
        tool_call_reply(
            (
                "replace_code",
                {"path": "src/cart.ts", "old": "return 0", "new": "return items.length || 0"},
            )
        ),
        text_reply("Confirmed the corrected behavior."),
    )
    model.review_replies = [
        {
            "verdict": "changes_requested",
            "summary": "Check empty input",
            "findings": [
                {
                    "category": "edge_case",
                    "severity": "medium",
                    "file": "src/cart.ts",
                    "line": 2,
                    "message": "Handle empty input explicitly.",
                }
            ],
        },
        {"verdict": "approved", "summary": "The revised patch is safe", "findings": []},
    ]
    use_model(model)

    run = start_run(repo_id)

    assert run["status"] == "succeeded", run
    assert len(model.review_requests) == 2
    assert len(run["attempts"]) == 2
    assert any(
        "Handle empty input explicitly" in event["detail"]
        for event in run["events"]
        if event["type"] == "hypothesis_rejected"
    )


def test_tool_errors_go_back_to_the_model(repo_service: RepoService) -> None:
    repo_id = connect()
    model = ScriptedModel(
        tool_call_reply(("delete_everything", {})),
        tool_call_reply(("read_file", {"path": "../../etc/passwd"})),
        tool_call_reply(("read_file", {"wrong": 1})),
        text_reply("Nothing to change."),
    )
    use_model(model)

    run = start_run(repo_id)

    assert run["status"] == "no_changes"
    results = [event for event in run["events"] if event["type"] == "tool_result"]
    assert all("failed" in event["message"] for event in results)
    sent = [m["content"] for m in model.requests[3]["messages"] if m["role"] == "tool"]
    assert sent[0].startswith("Error: Unknown tool 'delete_everything'")
    assert "outside the repository" in sent[1]
    assert "Invalid arguments for read_file" in sent[2]


def test_auto_mode_falls_back_to_json_actions(repo_service: RepoService) -> None:
    repo_id = connect()
    replace = {"path": "src/cart.ts", "old": "return 0", "new": "return 1"}
    model = ScriptedModel(
        httpx.Response(400, json={"error": "tools not supported"}),
        text_reply(
            "I'll fix it.\n```json\n"
            + json.dumps({"tool": "replace_code", "arguments": replace})
            + "\n```"
        ),
        text_reply("not json at all"),
        text_reply('{"final": "Returned 1."}'),
    )
    use_model(model)

    run = start_run(repo_id)

    assert run["status"] == "succeeded", run
    assert "+  return 1" in run["diff"]
    assert any("using JSON mode" in event["message"] for event in run["events"])
    assert any("not a valid JSON action" in event["message"] for event in run["events"])
    assert "tools" in model.requests[0] and "tools" not in model.requests[1]
    assert "Reply with exactly one JSON object" in model.requests[1]["messages"][0]["content"]


def test_step_limit_fails_the_run(repo_service: RepoService) -> None:
    repo_id = connect()
    use_agent_settings(repo_service, agent_max_steps=2)
    use_model(
        ScriptedModel(
            tool_call_reply(("list_files", {"depth": 1})),
            tool_call_reply(("list_files", {"depth": 2})),
            tool_call_reply(("list_files", {"depth": 3})),
        )
    )

    run = start_run(repo_id)

    assert run["status"] == "failed"
    assert run["error"] == "Step limit of 2 reached before finishing"


def test_stuck_model_is_stopped(repo_service: RepoService) -> None:
    repo_id = connect()
    same_call = ("read_file", {"path": "src/cart.ts"})
    use_model(ScriptedModel(*[tool_call_reply(same_call) for _ in range(5)]))

    run = start_run(repo_id)

    assert run["status"] == "failed"
    assert run["error"] == "Agent is stuck repeating the same read_file call"


def test_model_failure_mid_run_is_reported(repo_service: RepoService) -> None:
    repo_id = connect()
    use_model(ScriptedModel(httpx.Response(500, json={"error": "boom"})))

    run = start_run(repo_id)

    assert run["status"] == "failed"
    assert run["error"] == "The model provider request failed"
    assert "boom" not in json.dumps(run)


def test_each_run_starts_from_a_clean_workspace(repo_service: RepoService) -> None:
    repo_id = connect()
    use_model(
        ScriptedModel(
            tool_call_reply(("write_file", {"path": "src/cart.ts", "content": "broken\n"})),
            text_reply("Rewrote it."),
        )
    )
    first = start_run(repo_id)
    use_model(ScriptedModel(text_reply("Looks fine already.")))

    second = start_run(repo_id)

    assert first["status"] == "succeeded"
    assert second["status"] == "no_changes"
    workspace = repo_service.get_record(repo_id).workspace
    assert (workspace / "src" / "cart.ts").read_text(encoding="utf-8") == CART


def test_second_run_while_one_is_active_conflicts(repo_service: RepoService) -> None:
    repo_id = connect()
    use_model(ScriptedModel())
    app.dependency_overrides[get_run_store]().create(repo_id, "already running")

    response = client.post(f"/api/repos/{repo_id}/runs", json={"issue": "another"})

    assert response.status_code == 409
    assert response.json() == {"detail": "This repository already has a run in progress"}


def test_run_requires_configured_model(repo_service: RepoService) -> None:
    repo_id = connect()
    use_model(None, nebius_api_key="")

    response = client.post(f"/api/repos/{repo_id}/runs", json={"issue": "fix it"})

    assert response.status_code == 503


def test_unknown_repo_and_run_return_404(repo_service: RepoService) -> None:
    repo_id = connect()
    use_model(ScriptedModel())

    assert client.post("/api/repos/missing/runs", json={"issue": "x"}).status_code == 404
    assert client.get(f"/api/repos/{repo_id}/runs/missing").status_code == 404


@pytest.mark.parametrize("issue", ["", "   ", "x" * 4001])
def test_run_rejects_bad_issue(repo_service: RepoService, issue: str) -> None:
    repo_id = connect()
    use_model(ScriptedModel())

    assert client.post(f"/api/repos/{repo_id}/runs", json={"issue": issue}).status_code == 422


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ('{"final": "done"}', ("final", "done")),
        ('```json\n{"tool": "git_diff"}\n```', ("tool", "git_diff")),
        ('{"tool": "read_file", "arguments": "oops"}', ("tool", "read_file")),
        ("no json here", None),
        ('{"something": "else"}', None),
        ("[1, 2]", None),
    ],
)
def test_parse_json_action(content: str, expected: tuple[str, str] | None) -> None:
    action = parse_json_action(content)

    if expected is None:
        assert action is None
    else:
        kind, value = expected
        assert action is not None
        assert getattr(action, kind) == value


PLAN_JSON = json.dumps(
    {
        "rootCause": "total() in src/cart.ts returns 0 without summing",
        "filesToInspect": ["src/cart.ts"],
        "steps": ["Read src/cart.ts", "Return the item count from total()"],
        "testsToAdd": ["total([a, b]) returns 2"],
    }
)


def test_planner_plan_reaches_the_agent_and_the_run(repo_service: RepoService) -> None:
    repo_id = connect()
    use_agent_settings(repo_service, agent_planning=True)
    model = ScriptedModel(
        text_reply("Here is the plan:\n```json\n" + PLAN_JSON + "\n```"),
        tool_call_reply(
            (
                "replace_code",
                {"path": "src/cart.ts", "old": "return 0", "new": "return items.length"},
            )
        ),
        text_reply("Total now counts items."),
    )
    use_model(model)

    run = start_run(repo_id)

    assert run["status"] == "succeeded"
    assert run["plan"] == {
        "rootCause": "total() in src/cart.ts returns 0 without summing",
        "filesToInspect": ["src/cart.ts"],
        "steps": ["Read src/cart.ts", "Return the item count from total()"],
        "testsToAdd": ["total([a, b]) returns 2"],
    }
    assert [event["type"] for event in run["events"]][:5] == [
        "started",
        "contract",
        "baseline",
        "attempt",
        "plan",
    ]
    planner_request, first_agent_request = model.requests[0], model.requests[1]
    assert planner_request["model"] == "planner-model" and "tools" not in planner_request
    assert "untrusted" in planner_request["messages"][0]["content"]
    assert '<file path="src/cart.ts">' in planner_request["messages"][1]["content"]
    assert first_agent_request["model"] == "worker-model"
    agent_context = first_agent_request["messages"][1]["content"]
    assert "Plan from the planner" in agent_context
    assert "1. Read src/cart.ts" in agent_context


def test_invalid_plan_is_retried_then_run_continues_without_plan(
    repo_service: RepoService,
) -> None:
    repo_id = connect()
    use_agent_settings(repo_service, agent_planning=True)
    model = ScriptedModel(
        text_reply("I think the bug is in the cart."),
        text_reply('{"rootCause": "", "steps": []}'),
        text_reply("Nothing to change."),
    )
    use_model(model)

    run = start_run(repo_id)

    assert run["status"] == "no_changes"
    assert run["plan"] is None
    assert "That reply was not a valid plan" in model.requests[1]["messages"][-1]["content"]
    assert any("continuing without a plan" in event["message"] for event in run["events"])
    assert "Plan from the planner" not in model.requests[2]["messages"][1]["content"]


def test_planner_error_does_not_fail_the_run(repo_service: RepoService) -> None:
    repo_id = connect()
    use_agent_settings(repo_service, agent_planning=True)
    use_model(ScriptedModel(httpx.Response(500), text_reply("Nothing to change.")))

    run = start_run(repo_id)

    assert run["status"] == "no_changes"
    assert any("continuing without a plan" in event["message"] for event in run["events"])


FIX_CART = {
    "path": "src/cart.ts",
    "old": "return 0",
    "new": "return items.length",
}


def test_run_self_repairs_after_a_failing_test(repo_service: RepoService) -> None:
    repo_id = connect()
    sandbox = FakeSandbox(
        command_result("install"),
        command_result("test"),  # baseline
        command_result("test", passed=False, output="FAILED src/cart.test.ts::total"),
        command_result("test"),  # attempt 2 passes
    )
    use_agent_settings(repo_service, sandbox=sandbox, agent_planning=True)
    model = ScriptedModel(
        text_reply("```json\n" + PLAN_JSON + "\n```"),
        tool_call_reply(("replace_code", FIX_CART)),
        text_reply("Counts items."),
        text_reply("```json\n" + PLAN_JSON + "\n```"),
        tool_call_reply(("replace_code", FIX_CART)),
        text_reply("Counts items, for real."),
    )
    use_model(model)

    run = start_run(repo_id)

    assert run["status"] == "succeeded", (
        run["status"],
        [
            (r["model"], r["messages"][0]["content"][:80], r["messages"][1]["content"][:150])
            for r in model.requests
        ],
    )
    assert [attempt["testPassed"] for attempt in run["attempts"]] == [False, True]
    assert any(event["type"] == "hypothesis_rejected" for event in run["events"])
    assert sandbox.calls == ["install", "test", "test", "test"]
    replan_context = model.requests[3]["messages"][1]["content"]
    assert "do not repeat" in replan_context


def test_run_gives_up_after_max_attempts(repo_service: RepoService) -> None:
    repo_id = connect()
    sandbox = FakeSandbox(
        command_result("install"),
        command_result("test", passed=False, output="FAILED baseline"),
        command_result("test", passed=False, output="FAILED attempt 1"),
        command_result("test", passed=False, output="FAILED attempt 2"),
    )
    use_agent_settings(repo_service, sandbox=sandbox, agent_max_attempts=2)
    use_model(
        ScriptedModel(
            tool_call_reply(("replace_code", FIX_CART)),
            text_reply("Attempt one."),
            tool_call_reply(("replace_code", FIX_CART)),
            text_reply("Attempt two."),
        )
    )

    run = start_run(repo_id)

    assert run["status"] == "unverified", run
    assert len(run["attempts"]) == 2
    assert all(not attempt["testPassed"] for attempt in run["attempts"])
    assert "repository test failed" in run["error"].lower()


def test_run_without_a_test_command_is_unverified(repo_service: RepoService) -> None:
    repo_id = connect()
    sandbox = FakeSandbox(unavailable=("test",))
    use_agent_settings(repo_service, sandbox=sandbox)
    use_model(
        ScriptedModel(
            tool_call_reply(("replace_code", FIX_CART)),
            text_reply("Changed it."),
        )
    )

    run = start_run(repo_id)

    assert run["status"] == "unverified"
    assert run["diff"]
    assert run["error"] == "The fix could not be verified: no test command ran in the sandbox."
    assert all("baseline" != event["type"] for event in run["events"])


def test_agent_can_run_a_command_with_the_tool(repo_service: RepoService) -> None:
    repo_id = connect()
    sandbox = FakeSandbox()
    use_agent_settings(repo_service, sandbox=sandbox)
    model = ScriptedModel(
        tool_call_reply(("run_command", {"name": "test"})),
        tool_call_reply(("replace_code", FIX_CART)),
        text_reply("Fixed."),
    )
    use_model(model)

    run = start_run(repo_id)

    assert run["status"] == "succeeded"
    tool_names = {tool["function"]["name"] for tool in model.requests[0]["tools"]}
    assert "run_command" in tool_names
    tool_message = model.requests[1]["messages"][-1]
    assert tool_message["role"] == "tool" and "run_command(test)" in tool_message["content"]


def test_run_without_docker_is_unverified_not_crashed(repo_service: RepoService) -> None:
    repo_id = connect()
    use_agent_settings(repo_service, sandbox=FakeSandbox(is_down=True))
    model = ScriptedModel(
        tool_call_reply(("run_command", {"name": "test"})),
        tool_call_reply(("replace_code", FIX_CART)),
        text_reply("Fixed without running tests."),
    )
    use_model(model)

    run = start_run(repo_id)

    assert run["status"] == "unverified", run
    assert run["diff"]
    assert run["error"] == "The fix could not be verified: no test command ran in the sandbox."
    tool_message = model.requests[1]["messages"][-1]
    assert tool_message["role"] == "tool"
    assert "The sandbox is not available" in tool_message["content"]


def test_run_command_rejects_a_command_outside_the_allow_list(
    repo_service: RepoService,
) -> None:
    repo_id = connect()
    use_agent_settings(repo_service, sandbox=FakeSandbox())
    model = ScriptedModel(
        tool_call_reply(("run_command", {"name": "rm -rf /"})),
        text_reply("Nothing to change."),
    )
    use_model(model)

    run = start_run(repo_id)

    assert run["status"] == "no_changes"
    tool_message = model.requests[1]["messages"][-1]
    assert "Invalid arguments for run_command" in tool_message["content"]


def test_active_run_is_reported_until_it_is_cancelled(repo_service: RepoService) -> None:
    repo_id = connect()
    active_url = f"/api/repos/{repo_id}/runs/active"
    assert client.get(active_url).json() == {"runId": None}
    run = app.dependency_overrides[get_run_store]().create(repo_id, "already running")
    assert client.get(active_url).json() == {"runId": run.run_id}

    response = client.post(f"/api/repos/{repo_id}/runs/{run.run_id}/cancel")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled" and body["finishedAt"] is not None
    assert body["events"][-1]["type"] == "cancelled"
    assert client.get(active_url).json() == {"runId": None}


def test_only_a_run_in_progress_can_be_cancelled(repo_service: RepoService) -> None:
    repo_id = connect()
    run = app.dependency_overrides[get_run_store]().create(repo_id, "done already")
    run.finish("succeeded")

    finished = client.post(f"/api/repos/{repo_id}/runs/{run.run_id}/cancel")

    assert finished.status_code == 409
    assert finished.json() == {"detail": "This run is not in progress"}
    assert run.status == "succeeded"
    assert client.post(f"/api/repos/{repo_id}/runs/missing/cancel").status_code == 404
    assert client.get("/api/repos/missing/runs/active").status_code == 404


class HangingSandbox(FakeSandbox):
    """Edits the workspace, then blocks inside its first command until cancelled."""

    def __init__(self, workspace: Path):
        super().__init__()
        self.workspace = workspace
        self.started: asyncio.Event | None = None

    async def run(self, repos: RepoService, repo_id: str, name: CommandName) -> CommandResult:
        self.calls.append(name)
        (self.workspace / "half-done.txt").write_text("partial edit", encoding="utf-8")
        assert self.started is not None
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("the command should have been cancelled")


def test_cancel_interrupts_the_agent_and_discards_its_edits(repo_service: RepoService) -> None:
    repo_id = connect()
    workspace = repo_service.get_record(repo_id).workspace
    store = app.dependency_overrides[get_run_store]()
    sandbox = HangingSandbox(workspace)
    service = RunService(
        repo_service, store, Settings(_env_file=None, agent_planning=False), sandbox
    )
    contract = VerificationContract(
        criteria=[Criterion(id="behavior", description="Totals are right", kind="behavior")]
    )
    run = service.start(repo_id, "Total should count the items", contract)
    llm = LLMClient(
        Settings(_env_file=None, **LLM_SETTINGS), transport=httpx.MockTransport(ScriptedModel())
    )

    async def cancel_mid_command() -> None:
        sandbox.started = asyncio.Event()
        execution = asyncio.create_task(service.execute(run, llm))
        await sandbox.started.wait()
        service.cancel(repo_id, run.run_id)
        await execution

    asyncio.run(cancel_mid_command())

    assert run.status == "cancelled"
    assert run.events[-1].type == "cancelled"
    assert sandbox.calls == ["install"]
    assert not (workspace / "half-done.txt").exists()
    assert store.active_for(repo_id) is None
