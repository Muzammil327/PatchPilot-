import posixpath
import re
from dataclasses import dataclass

TEST_FILE_PATTERN = re.compile(r"\.(test|spec)\.[cm]?[jt]sx?$")
TEST_NAME_SUFFIX = re.compile(r"\.(test|spec)$")
TEST_DIRS = frozenset({"__tests__", "test", "tests"})
SOURCE_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts")
RELATIVE_PREFIXES = ("./", "../")


@dataclass(frozen=True)
class TestLink:
    test_file: str
    source_files: list[str]


def is_test_file(path: str) -> bool:
    parts = path.split("/")
    return bool(TEST_FILE_PATTERN.search(parts[-1])) or any(
        part in TEST_DIRS for part in parts[:-1]
    )


def link_tests(imports_by_file: dict[str, list[str]], all_paths: set[str]) -> list[TestLink]:
    """Link each JS/TS test file to the source files it covers.

    Uses the test's relative imports first; falls back to the naming convention
    (`foo.test.ts` -> `foo.ts`, also one folder up from `__tests__/`).
    """
    links = []
    for test_file, modules in imports_by_file.items():
        if not is_test_file(test_file):
            continue
        sources = []
        for module in modules:
            resolved = resolve_relative_import(test_file, module, all_paths)
            if resolved and not is_test_file(resolved) and resolved not in sources:
                sources.append(resolved)
        if not sources:
            sources = find_by_naming(test_file, all_paths)
        links.append(TestLink(test_file=test_file, source_files=sources))
    return links


def resolve_relative_import(importer: str, module: str, all_paths: set[str]) -> str | None:
    if not module.startswith(RELATIVE_PREFIXES):
        return None
    base = posixpath.normpath(posixpath.join(posixpath.dirname(importer), module))
    if base.startswith(".."):
        return None
    candidates = [base] if base.endswith(SOURCE_EXTENSIONS) else []
    candidates += [base + extension for extension in SOURCE_EXTENSIONS]
    candidates += [f"{base}/index{extension}" for extension in SOURCE_EXTENSIONS]
    return next((candidate for candidate in candidates if candidate in all_paths), None)


def find_by_naming(test_file: str, all_paths: set[str]) -> list[str]:
    folder, name = posixpath.split(test_file)
    stem = TEST_NAME_SUFFIX.sub("", posixpath.splitext(name)[0])
    if stem == posixpath.splitext(name)[0]:
        return []  # a file inside tests/ without a .test/.spec suffix; no name to match
    folders = [folder]
    if posixpath.basename(folder) in TEST_DIRS:
        folders.append(posixpath.dirname(folder))
    for candidate_folder in folders:
        for extension in SOURCE_EXTENSIONS:
            candidate = posixpath.join(candidate_folder, stem + extension)
            if candidate in all_paths:
                return [candidate]
    return []
