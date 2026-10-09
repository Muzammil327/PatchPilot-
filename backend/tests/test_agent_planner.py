import json

import pytest

from app.agent.planner import MAX_PLAN_ITEM_CHARS, MAX_PLAN_ITEMS, format_plan, parse_plan


def test_parse_plan_accepts_fenced_json_and_clips_items() -> None:
    raw = {
        "rootCause": "  off-by-one in loop  ",
        "filesToInspect": ["a.ts", "  ", "b.ts"],
        "steps": ["x" * (MAX_PLAN_ITEM_CHARS + 50)] + [f"step {n}" for n in range(12)],
        "unknownField": "ignored",
    }

    plan = parse_plan("Plan:\n```json\n" + json.dumps(raw) + "\n```")

    assert plan is not None
    assert plan.root_cause == "off-by-one in loop"
    assert plan.files_to_inspect == ["a.ts", "b.ts"]
    assert len(plan.steps) == MAX_PLAN_ITEMS
    assert len(plan.steps[0]) == MAX_PLAN_ITEM_CHARS
    assert plan.tests_to_add == []


@pytest.mark.parametrize(
    "content",
    [
        "no json at all",
        '{"rootCause": "x"}',
        '{"rootCause": "", "steps": ["a"]}',
        '{"rootCause": "x", "steps": []}',
        "[1, 2, 3]",
        "{not valid json}",
    ],
)
def test_parse_plan_rejects_unusable_replies(content: str) -> None:
    assert parse_plan(content) is None


def test_format_plan_is_plain_text() -> None:
    plan = parse_plan(
        json.dumps(
            {
                "rootCause": "qty is overwritten",
                "filesToInspect": ["lib/cart.ts"],
                "steps": ["Sum the quantities", "Keep other fields"],
                "testsToAdd": ["Pen x2 then x1 gives x3"],
            }
        )
    )
    assert plan is not None

    assert format_plan(plan) == (
        "Likely root cause: qty is overwritten\n"
        "Files to inspect: lib/cart.ts\n"
        "Steps:\n1. Sum the quantities\n2. Keep other fields\n"
        "Tests to add:\n- Pen x2 then x1 gives x3"
    )
