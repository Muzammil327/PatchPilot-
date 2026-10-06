from pathlib import Path

from tree_sitter import Parser

from app.repo.repo_map import JAVASCRIPT, TSX, TYPESCRIPT, build_repo_map, extract_file_map
from app.repo.scan import ScannedFile


def extract(source: str, grammar=JAVASCRIPT, path: str = "file.js"):
    return extract_file_map(path, Parser(grammar), source.encode())


def test_extracts_each_function_style_with_lines() -> None:
    file_map = extract(
        "function a() {}\n"
        "const b = () => 1\n"
        "let c = function () {}\n"
        "const d = async function* () {}\n"
        "const notAFunction = 42\n"
    )

    assert [(f.name, f.line) for f in file_map.functions] == [
        ("a", 1),
        ("b", 2),
        ("c", 3),
        ("d", 4),
    ]


def test_extracts_classes_with_methods() -> None:
    file_map = extract(
        "export abstract class Repo {\n  private load(): void {}\n  save() {}\n}\n",
        TYPESCRIPT,
        "repo.ts",
    )

    assert len(file_map.classes) == 1
    repo = file_map.classes[0]
    assert (repo.name, repo.line, repo.methods) == ("Repo", 1, ["load", "save"])
    assert file_map.exports == ["Repo"]


def test_extracts_import_forms() -> None:
    file_map = extract(
        'import React, { useState, useEffect as onMount } from "react"\n'
        'import * as api from "./lib/api"\n'
        "import './globals.css'\n"
    )

    assert [(i.source, i.names) for i in file_map.imports] == [
        ("react", ["React", "useState", "onMount"]),
        ("./lib/api", ["* as api"]),
        ("./globals.css", []),
    ]


def test_extracts_export_forms() -> None:
    file_map = extract(
        "export function helper() {}\n"
        "export const VALUE = 1, other = () => 2\n"
        "const a = 1, b = 2\n"
        "export { a, b as renamed }\n"
        'export * from "./all"\n'
        'export * as ns from "./ns"\n'
        "export default function Home() {}\n"
    )

    assert file_map.exports == ["helper", "VALUE", "other", "a", "renamed", "*", "ns", "default"]
    assert [f.name for f in file_map.functions] == ["helper", "other", "Home"]


def test_anonymous_default_export() -> None:
    file_map = extract("export default () => null\n")

    assert file_map.exports == ["default"]
    assert file_map.functions == []


def test_tsx_component_file() -> None:
    file_map = extract(
        'import { Card } from "@/components/Card"\n'
        "export function RiskCard({ level }: { level: string }) {\n"
        "  return <Card>{level}</Card>\n"
        "}\n",
        TSX,
        "RiskCard.tsx",
    )

    assert [f.name for f in file_map.functions] == ["RiskCard"]
    assert file_map.exports == ["RiskCard"]
    assert file_map.imports[0].source == "@/components/Card"


def test_syntax_errors_keep_what_parsed() -> None:
    file_map = extract("function ok() {}\nconst broken = (\nfunction alsoOk() {}\n")

    assert "ok" in [f.name for f in file_map.functions]


def test_build_repo_map_survives_many_files(tmp_path: Path) -> None:
    # One parser reused across many files. Note: this does not reproduce the
    # tree-sitter 0.26.0 heap corruption seen on a real repo; the version pin does.
    files = []
    for index in range(60):
        name = f"component{index}.tsx"
        (tmp_path / name).write_text(
            f'import {{ a, b as c }} from "./lib{index}"\n'
            f'import * as ns from "./ns"\n'
            f"export const Component{index} = () => <div>{{a}}</div>\n"
            f"export function helper{index}() {{}}\n"
            f"export {{ c }}\n",
            encoding="utf-8",
        )
        files.append(ScannedFile(path=name, language="typescript", size_bytes=1))

    repo_map = build_repo_map(tmp_path, files)

    assert repo_map.parsed_count == 60
    assert repo_map.function_count == 120


def test_build_repo_map_parses_only_js_ts_files(tmp_path: Path) -> None:
    (tmp_path / "a.ts").write_text("export function a() {}", encoding="utf-8")
    (tmp_path / "b.jsx").write_text("export class B {}", encoding="utf-8")
    (tmp_path / "README.md").write_text("# hi", encoding="utf-8")
    files = [
        ScannedFile(path="a.ts", language="typescript", size_bytes=1),
        ScannedFile(path="b.jsx", language="javascript", size_bytes=1),
        ScannedFile(path="README.md", language="other", size_bytes=1),
        ScannedFile(path="missing.ts", language="typescript", size_bytes=1),
    ]

    repo_map = build_repo_map(tmp_path, files)

    assert [file.path for file in repo_map.files] == ["a.ts", "b.jsx"]
    assert (repo_map.parsed_count, repo_map.failed_count) == (2, 1)
    assert (repo_map.function_count, repo_map.class_count) == (1, 1)
