import posixpath
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from tree_sitter import Node

RouteKind = Literal["page", "api"]

ANY_METHOD = "*"
PAGE_METHOD = "GET"
HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})

# `router.get("/x", ...)` style calls. Only trusted in files that load a server framework,
# so client calls such as `axios.get("/api/x")` are not mistaken for routes.
ROUTER_CALL_METHODS = {
    "get": "GET",
    "post": "POST",
    "put": "PUT",
    "patch": "PATCH",
    "delete": "DELETE",
    "options": "OPTIONS",
    "head": "HEAD",
    "all": ANY_METHOD,
}
SERVER_FRAMEWORKS = ("express", "fastify", "koa", "@koa/router", "koa-router", "hono")

APP_ROUTER_DIR = "app"
PAGES_ROUTER_DIR = "pages"
NEXT_CONFIG_FILES = (
    "next.config.js",
    "next.config.mjs",
    "next.config.cjs",
    "next.config.ts",
    "next.config.mts",
)
STRING_QUOTES = "\"'`"

TextOf = Callable[[Node | None], str]


@dataclass(frozen=True)
class Route:
    method: str
    path: str
    file: str
    line: int
    kind: RouteKind


def is_server_framework(module: str) -> bool:
    return any(module == name or module.startswith(f"{name}/") for name in SERVER_FRAMEWORKS)


def mentions_server_framework(source: bytes) -> bool:
    """Cheap pre-check so the full-tree walk only runs on likely server files."""
    return any(name.encode() in source for name in SERVER_FRAMEWORKS)


def find_router_calls(root: Node, file: str, text_of: TextOf) -> tuple[list[Route], bool]:
    """Return candidate `x.method("/path")` routes and whether `require(<framework>)` appears."""
    routes: list[Route] = []
    requires_framework = False
    stack = [root]
    while stack:
        node = stack.pop()
        stack.extend(node.named_children)
        if node.type != "call_expression":
            continue
        function = node.child_by_field_name("function")
        first_arg = first_argument(node)
        if function is None or first_arg is None:
            continue
        if function.type == "identifier" and text_of(function) == "require":
            requires_framework |= is_server_framework(literal_text(first_arg, text_of) or "")
        elif function.type == "member_expression":
            method = ROUTER_CALL_METHODS.get(text_of(function.child_by_field_name("property")))
            path = literal_text(first_arg, text_of)
            if method and path and path.startswith("/"):
                line = node.start_point.row + 1
                routes.append(Route(method=method, path=path, file=file, line=line, kind="api"))
    routes.sort(key=lambda route: route.line)
    return routes, requires_framework


def first_argument(call: Node) -> Node | None:
    arguments = call.child_by_field_name("arguments")
    if arguments is None or not arguments.named_children:
        return None
    return arguments.named_children[0]


def literal_text(node: Node, text_of: TextOf) -> str | None:
    """Value of a plain string or a template string without `${}` substitutions."""
    if node.type == "string":
        return text_of(node).strip(STRING_QUOTES)
    if node.type == "template_string" and not any(
        child.type == "template_substitution" for child in node.named_children
    ):
        return text_of(node).strip(STRING_QUOTES)
    return None


def find_next_routes(
    file: str, exports: list[str], function_lines: dict[str, int], all_paths: set[str]
) -> list[Route]:
    """File-based Next.js routes, only inside a project that has a next.config file."""
    parts = file.split("/")
    stem = posixpath.splitext(parts[-1])[0]
    folders = parts[:-1]

    if APP_ROUTER_DIR in folders:
        index = folders.index(APP_ROUTER_DIR)
        if has_next_config(folders[:index], all_paths) and stem in {"page", "route"}:
            segments = app_router_segments(folders[index + 1 :])
            if segments is None:
                return []
            url = to_url(segments)
            if stem == "page":
                return [Route(method=PAGE_METHOD, path=url, file=file, line=1, kind="page")]
            return [
                Route(
                    method=name, path=url, file=file, line=function_lines.get(name, 1), kind="api"
                )
                for name in exports
                if name in HTTP_METHODS
            ]

    if PAGES_ROUTER_DIR in folders:
        index = folders.index(PAGES_ROUTER_DIR)
        segments = folders[index + 1 :] + ([] if stem == "index" else [stem])
        is_private = any(segment.startswith("_") for segment in segments)
        if has_next_config(folders[:index], all_paths) and not is_private:
            if segments and segments[0] == "api":
                return [
                    Route(method=ANY_METHOD, path=to_url(segments), file=file, line=1, kind="api")
                ]
            return [
                Route(method=PAGE_METHOD, path=to_url(segments), file=file, line=1, kind="page")
            ]

    return []


def app_router_segments(folders: list[str]) -> list[str] | None:
    """URL segments for an App Router folder path, or None for private (`_x`) folders."""
    segments = []
    for folder in folders:
        if folder.startswith("_"):
            return None
        is_group = folder.startswith("(") and folder.endswith(")")
        is_slot = folder.startswith("@")
        if not (is_group or is_slot):
            segments.append(folder)
    return segments


def has_next_config(project_folders: list[str], all_paths: set[str]) -> bool:
    candidates = [project_folders]
    if project_folders and project_folders[-1] == "src":
        candidates.append(project_folders[:-1])
    return any(
        posixpath.join(*folders, config) in all_paths if folders else config in all_paths
        for folders in candidates
        for config in NEXT_CONFIG_FILES
    )


def to_url(segments: list[str]) -> str:
    return "/" + "/".join(segments)
