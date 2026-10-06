import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import tree_sitter_javascript
import tree_sitter_typescript
from tree_sitter import Language, Node, Parser, Tree

from app.repo.routes import (
    Route,
    find_next_routes,
    find_router_calls,
    is_server_framework,
    mentions_server_framework,
)
from app.repo.scan import ScannedFile
from app.repo.tests_map import TestLink, link_tests

logger = logging.getLogger(__name__)

JAVASCRIPT = Language(tree_sitter_javascript.language())
TYPESCRIPT = Language(tree_sitter_typescript.language_typescript())
TSX = Language(tree_sitter_typescript.language_tsx())

# The JavaScript grammar already understands JSX, so .jsx needs no separate grammar.
GRAMMAR_BY_EXTENSION = {
    ".js": JAVASCRIPT,
    ".jsx": JAVASCRIPT,
    ".mjs": JAVASCRIPT,
    ".cjs": JAVASCRIPT,
    ".ts": TYPESCRIPT,
    ".mts": TYPESCRIPT,
    ".cts": TYPESCRIPT,
    ".tsx": TSX,
}

FUNCTION_DECLARATIONS = frozenset({"function_declaration", "generator_function_declaration"})
FUNCTION_VALUES = frozenset({"arrow_function", "function_expression", "generator_function"})
CLASS_DECLARATIONS = frozenset({"class_declaration", "abstract_class_declaration"})
VARIABLE_DECLARATIONS = frozenset({"lexical_declaration", "variable_declaration"})

DEFAULT_EXPORT = "default"
NAMESPACE_EXPORT = "*"
STRING_QUOTES = "\"'`"


@dataclass(frozen=True)
class FunctionSymbol:
    name: str
    line: int  # 1-based


@dataclass(frozen=True)
class ClassSymbol:
    name: str
    line: int
    methods: list[str]


@dataclass(frozen=True)
class ImportRef:
    source: str
    names: list[str]  # local names; "* as x" for namespace imports; empty for side effects


@dataclass
class FileMap:
    path: str
    functions: list[FunctionSymbol] = field(default_factory=list)
    classes: list[ClassSymbol] = field(default_factory=list)
    imports: list[ImportRef] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)
    routes: list[Route] = field(default_factory=list)


@dataclass(frozen=True)
class RepoMap:
    files: list[FileMap]
    parsed_count: int
    failed_count: int
    test_links: list[TestLink] = field(default_factory=list)

    @property
    def function_count(self) -> int:
        return sum(len(file.functions) for file in self.files)

    @property
    def class_count(self) -> int:
        return sum(len(file.classes) for file in self.files)

    @property
    def routes(self) -> list[Route]:
        return [route for file in self.files for route in file.routes]


def build_repo_map(root: Path, files: list[ScannedFile]) -> RepoMap:
    # Parsers are not thread-safe, so each build (one per connect) gets its own.
    parsers: dict[int, Parser] = {}
    file_maps: list[FileMap] = []
    failed_count = 0

    for scanned in files:
        grammar = GRAMMAR_BY_EXTENSION.get(os.path.splitext(scanned.path)[1].lower())
        if grammar is None:
            continue
        parser = parsers.get(id(grammar))
        if parser is None:
            parser = parsers[id(grammar)] = Parser(grammar)
        try:
            source = (root / scanned.path).read_bytes()
            file_maps.append(extract_file_map(scanned.path, parser, source))
        except (OSError, ValueError) as exc:
            failed_count += 1
            logger.warning("map failed for %s: %s", scanned.path, type(exc).__name__)

    all_paths = {scanned.path for scanned in files}
    for file_map in file_maps:
        function_lines = {function.name: function.line for function in file_map.functions}
        file_map.routes.extend(
            find_next_routes(file_map.path, file_map.exports, function_lines, all_paths)
        )
    test_links = link_tests(
        {file_map.path: [ref.source for ref in file_map.imports] for file_map in file_maps},
        all_paths,
    )

    return RepoMap(
        files=file_maps,
        parsed_count=len(file_maps),
        failed_count=failed_count,
        test_links=test_links,
    )


def extract_file_map(path: str, parser: Parser, source: bytes) -> FileMap:
    """Extract top-level symbols. Syntax errors still yield whatever parsed cleanly."""
    return FileExtractor(path, source).extract(parser.parse(source))


class FileExtractor:
    """Walks one parsed file. Text is sliced from `source` by byte offsets."""

    def __init__(self, path: str, source: bytes):
        self.source = source
        self.file_map = FileMap(path=path)

    def extract(self, tree: Tree) -> FileMap:
        for node in tree.root_node.named_children:
            if node.type == "import_statement":
                self.file_map.imports.append(self.read_import(node))
            elif node.type == "export_statement":
                self.read_export(node)
            else:
                self.read_declaration(node)
        if mentions_server_framework(self.source):
            self.read_server_routes(tree)
        return self.file_map

    def read_server_routes(self, tree: Tree) -> None:
        candidates, requires_framework = find_router_calls(
            tree.root_node, self.file_map.path, self.text_of
        )
        imports_framework = any(is_server_framework(ref.source) for ref in self.file_map.imports)
        if requires_framework or imports_framework:
            self.file_map.routes.extend(candidates)

    def read_declaration(self, node: Node) -> list[str]:
        """Record a function/class/variable declaration; return the names it declares."""
        if node.type in FUNCTION_DECLARATIONS:
            name = self.field_text(node, "name")
            if name:
                self.file_map.functions.append(FunctionSymbol(name=name, line=line_of(node)))
                return [name]
        elif node.type in CLASS_DECLARATIONS:
            name = self.field_text(node, "name")
            if name:
                self.file_map.classes.append(self.read_class(node, name))
                return [name]
        elif node.type in VARIABLE_DECLARATIONS:
            names = []
            for declarator in node.named_children:
                if declarator.type != "variable_declarator":
                    continue
                name = self.field_text(declarator, "name")
                if not name:  # destructuring patterns have no single name
                    continue
                names.append(name)
                value = declarator.child_by_field_name("value")
                if value is not None and value.type in FUNCTION_VALUES:
                    self.file_map.functions.append(
                        FunctionSymbol(name=name, line=line_of(declarator))
                    )
            return names
        return []

    def read_class(self, node: Node, name: str) -> ClassSymbol:
        methods: list[str] = []
        body = node.child_by_field_name("body")
        if body is not None:
            for member in body.named_children:
                if member.type == "method_definition":
                    method_name = self.field_text(member, "name")
                    if method_name:
                        methods.append(method_name)
        return ClassSymbol(name=name, line=line_of(node), methods=methods)

    def read_import(self, node: Node) -> ImportRef:
        source = self.text_of(node.child_by_field_name("source")).strip(STRING_QUOTES)
        names: list[str] = []
        clause = next((c for c in node.named_children if c.type == "import_clause"), None)
        if clause is not None:
            for part in clause.named_children:
                if part.type == "identifier":
                    names.append(self.text_of(part))
                elif part.type == "namespace_import":
                    alias = next((c for c in part.named_children if c.type == "identifier"), None)
                    names.append(f"* as {self.text_of(alias)}" if alias else NAMESPACE_EXPORT)
                elif part.type == "named_imports":
                    names.extend(self.specifier_names(part, "import_specifier"))
        return ImportRef(source=source, names=names)

    def read_export(self, node: Node) -> None:
        exports = self.file_map.exports
        is_default = any(child.type == "default" for child in node.children)
        declaration = node.child_by_field_name("declaration")

        if declaration is not None:
            declared = self.read_declaration(declaration)
            exports.extend([DEFAULT_EXPORT] if is_default else declared)
            return
        if is_default:
            # `export default <expression>`: record a named function/class expression.
            value = node.child_by_field_name("value")
            if value is not None and value.type in FUNCTION_VALUES | {"class"}:
                name = self.field_text(value, "name")
                if name and value.type == "class":
                    self.file_map.classes.append(self.read_class(value, name))
                elif name:
                    self.file_map.functions.append(FunctionSymbol(name=name, line=line_of(value)))
            exports.append(DEFAULT_EXPORT)
            return

        namespace = next((c for c in node.named_children if c.type == "namespace_export"), None)
        if namespace is not None:  # export * as name from "..."
            exports.append(self.text_of(namespace.named_children[0]) or NAMESPACE_EXPORT)
            return
        clause = next((c for c in node.named_children if c.type == "export_clause"), None)
        if clause is None:
            exports.append(NAMESPACE_EXPORT)  # export * from "..."
            return
        exports.extend(self.specifier_names(clause, "export_specifier"))

    def specifier_names(self, node: Node, specifier_type: str) -> list[str]:
        """Names from `{ a, b as c }`: the alias when present, otherwise the name."""
        names = []
        for specifier in node.named_children:
            if specifier.type == specifier_type:
                name = self.field_text(specifier, "alias") or self.field_text(specifier, "name")
                if name:
                    names.append(name)
        return names

    def text_of(self, node: Node | None) -> str:
        if node is None:
            return ""
        return self.source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")

    def field_text(self, node: Node, field_name: str) -> str:
        return self.text_of(node.child_by_field_name(field_name))


def line_of(node: Node) -> int:
    return node.start_point.row + 1
