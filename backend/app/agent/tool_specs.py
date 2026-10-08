import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agent.errors import ToolError
from app.agent.tools import WorkspaceTools


class ToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReadFileArgs(ToolArgs):
    path: str = Field(description="File path relative to the repository root.")
    start_line: int = Field(default=1, ge=1, description="First line to read (1-based).")
    end_line: int | None = Field(default=None, ge=1, description="Last line to read.")


class ListFilesArgs(ToolArgs):
    path: str = Field(default=".", description="Directory relative to the repository root.")
    depth: int = Field(default=2, ge=1, le=4, description="How many folder levels to show.")


class SearchCodeArgs(ToolArgs):
    query: str = Field(description="Exact text to find, case-insensitive.")


class WriteFileArgs(ToolArgs):
    path: str = Field(description="File path relative to the repository root.")
    content: str = Field(description="The complete new file content.")


class ReplaceCodeArgs(ToolArgs):
    path: str = Field(description="File path relative to the repository root.")
    old: str = Field(description="Exact existing text; must occur exactly once in the file.")
    new: str = Field(description="Replacement text.")


class NoArgs(ToolArgs):
    pass


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[ToolArgs]
    handler: Callable[[WorkspaceTools, Any], str]


TOOL_SPECS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        ToolSpec(
            "read_file",
            "Read a file with line numbers. Read before you edit.",
            ReadFileArgs,
            lambda tools, a: tools.read_file(a.path, a.start_line, a.end_line),
        ),
        ToolSpec(
            "list_files",
            "List files and folders.",
            ListFilesArgs,
            lambda tools, a: tools.list_files(a.path, a.depth),
        ),
        ToolSpec(
            "search_code",
            "Find lines containing exact text across the repository.",
            SearchCodeArgs,
            lambda tools, a: tools.search_code(a.query),
        ),
        ToolSpec(
            "write_file",
            "Create a file or replace a whole file. Prefer replace_code for small edits.",
            WriteFileArgs,
            lambda tools, a: tools.write_file(a.path, a.content),
        ),
        ToolSpec(
            "replace_code",
            "Replace one exact occurrence of `old` with `new` in a file.",
            ReplaceCodeArgs,
            lambda tools, a: tools.replace_code(a.path, a.old, a.new),
        ),
        ToolSpec(
            "git_status",
            "List files you have changed.",
            NoArgs,
            lambda tools, _: tools.git_status(),
        ),
        ToolSpec(
            "git_diff",
            "Show the diff of all your changes.",
            NoArgs,
            lambda tools, _: tools.git_diff(),
        ),
    )
}


def openai_tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.args_model.model_json_schema(),
            },
        }
        for spec in TOOL_SPECS.values()
    ]


def json_mode_tool_docs() -> str:
    """Tool reference for providers without native tool calling."""
    lines = []
    for spec in TOOL_SPECS.values():
        fields = spec.args_model.model_fields
        params = ", ".join(
            f"{name}{'' if field.is_required() else '?'}" for name, field in fields.items()
        )
        lines.append(f"- {spec.name}({params}): {spec.description}")
    return "\n".join(lines)


def parse_arguments(raw: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise ToolError("Tool arguments must be a JSON object.") from exc
    if not isinstance(value, dict):
        raise ToolError("Tool arguments must be a JSON object.")
    return value


def execute_tool(tools: WorkspaceTools, name: str, raw_arguments: str | dict[str, Any]) -> str:
    """Run one tool call. Raises ToolError with a message meant for the model."""
    spec = TOOL_SPECS.get(name)
    if spec is None:
        raise ToolError(f"Unknown tool {name!r}. Available: {', '.join(TOOL_SPECS)}.")
    try:
        args = spec.args_model.model_validate(parse_arguments(raw_arguments))
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or 'arguments'}: {error['msg']}"
            for error in exc.errors()
        )
        raise ToolError(f"Invalid arguments for {name}: {problems}") from exc
    return spec.handler(tools, args)
