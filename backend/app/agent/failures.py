import logging
import re

from app.llm.client import LLMClient, LLMError

logger = logging.getLogger(__name__)

MAX_FAILURE_ITEMS = 20
MAX_FAILURE_SUMMARY_CHARS = 4000
MAX_MODEL_INPUT_CHARS = 8000
MAX_MODEL_SUMMARY_CHARS = 1200
MODEL_SUMMARY_WORDS = 120

# pytest prints failing tests as "FAILED tests/test_x.py::test_name - AssertionError: ...".
PYTEST_FAILURE = re.compile(r"^(?:FAILED|ERROR)\s+(.+)$", re.MULTILINE)
# vitest/jest print failing tests with a leading cross or "●", and a per-suite summary.
JS_FAILURE = re.compile(r"^\s*(?:[✕×✗]|FAIL|●)\s+(.+)$", re.MULTILINE)
JS_SUMMARY = re.compile(r"^\s*(?:Tests?|Test Suites?):\s*(.+)$", re.MULTILINE)
# A line that names an exception or a file:line is usually the useful part.
ERROR_LINE = re.compile(
    r"^.*(?:[A-Za-z_][\w.]*(?:Error|Exception)\b|[^\s]+\.\w+:\d+).*$", re.MULTILINE
)

SUMMARIZER_SYSTEM = (
    "You summarize failing test output for an engineer fixing the bug. State which tests "
    "failed and the most likely cause. Plain text only: no Markdown, no headings, no code "
    f"fences. At most {MODEL_SUMMARY_WORDS} words."
)


def collect_failures(output: str) -> list[str]:
    """The lines that name failing tests or errors, de-duplicated and clipped."""
    items: list[str] = []
    for pattern in (PYTEST_FAILURE, JS_FAILURE, JS_SUMMARY, ERROR_LINE):
        for match in pattern.finditer(output):
            line = match.group(1).strip()
            if line and line not in items:
                items.append(line)
    return items


def summarize_failures(output: str, max_chars: int = MAX_FAILURE_SUMMARY_CHARS) -> str:
    """A short, rule-based description of what failed. Pure and deterministic."""
    trimmed = output.strip()
    if not trimmed:
        return "The command failed but produced no output."
    items = collect_failures(trimmed)
    if items:
        body = "\n".join(f"- {item}" for item in items[:MAX_FAILURE_ITEMS])
    else:
        body = "\n".join(trimmed.splitlines()[-MAX_FAILURE_ITEMS:])
    return body[:max_chars]


async def summarize_with_model(llm: LLMClient, output: str, fallback: str) -> str:
    """Ask the worker model for a concise failure summary; fall back to the rule-based one."""
    excerpt = output.strip()[:MAX_MODEL_INPUT_CHARS]
    if not excerpt:
        return fallback
    try:
        completion = await llm.complete(excerpt, role="worker", system=SUMMARIZER_SYSTEM)
    except LLMError as exc:
        logger.warning("failure summarization failed: %s", exc)
        return fallback
    summary = completion.output.strip()
    return summary[:MAX_MODEL_SUMMARY_CHARS] if summary else fallback
