from pathlib import Path

import pytest

from app.repo.repo_map import build_repo_map
from app.repo.scan import ScannedFile
from app.repo.search import MAX_MATCHES, query_terms, rank_files, search_code


def write_repo(root: Path, files: dict[str, str]) -> list[ScannedFile]:
    scanned = []
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        language = "typescript" if relative.endswith((".ts", ".tsx")) else "other"
        scanned.append(ScannedFile(path=relative, language=language, size_bytes=len(content)))
    return scanned


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Which files are related to authentication?", ["authentication"]),
        ("AuthProvider", ["auth", "provider"]),
        ("parseHTTPResponse", ["parse", "http", "response"]),
        ("heat_risk score", ["heat", "risk", "score"]),
        ("heat heat HEAT", ["heat"]),
        (
            "The total() function in lib/cart.ts returns 0",
            ["total", "function", "lib", "cart", "returns"],
        ),
        ("fix app.module.json and style.css", ["fix", "app", "module", "style"]),
        ("a is to", []),
    ],
)
def test_query_terms(query: str, expected: list[str]) -> None:
    assert query_terms(query) == expected


def test_search_is_case_insensitive_and_literal(tmp_path: Path) -> None:
    files = write_repo(
        tmp_path,
        {
            "a.ts": "const x = 1\nexport function HeatRisk() {}\n",
            "b.md": "heat risk notes\nunrelated\n",
            "c.ts": "heat  risk with two spaces\n",
        },
    )

    result = search_code(tmp_path, files, "  Heat Risk ")

    assert [(m.path, m.line, m.text) for m in result.matches] == [("b.md", 1, "heat risk notes")]
    assert result.is_truncated is False


def test_search_caps_matches_per_file_and_total(tmp_path: Path) -> None:
    files = write_repo(
        tmp_path, {f"f{index:02}.ts": "token\n" * 10 for index in range(MAX_MATCHES)}
    )

    result = search_code(tmp_path, files, "token")

    assert len(result.matches) == MAX_MATCHES
    assert {m.path for m in result.matches} == {f"f{index:02}.ts" for index in range(10)}
    assert result.is_truncated is True


def test_search_skips_binary_looking_files(tmp_path: Path) -> None:
    files = write_repo(tmp_path, {"data.bin.txt": "token\x00token"})

    assert search_code(tmp_path, files, "token").matches == []


def test_rank_prefers_symbols_and_paths_with_reasons(tmp_path: Path) -> None:
    files = write_repo(
        tmp_path,
        {
            "src/auth/session.ts": 'import { hash } from "./crypto"\nexport function login() {}\n',
            "src/auth/crypto.ts": "export function hash() {}\n",
            "src/AuthProvider.tsx": "export function AuthProvider() {}\n",
            "src/cart.ts": "// auth is handled elsewhere\nexport function addItem() {}\n",
            "README.md": "nothing relevant\n",
        },
    )
    repo_map = build_repo_map(tmp_path, files)

    ranked = rank_files(tmp_path, files, repo_map, "auth")

    paths = [r.path for r in ranked]
    assert paths[0] == "src/AuthProvider.tsx"  # symbol + path + content
    assert set(paths[:3]) == {"src/AuthProvider.tsx", "src/auth/session.ts", "src/auth/crypto.ts"}
    assert paths.index("src/cart.ts") > paths.index("src/auth/crypto.ts")
    assert "README.md" not in paths
    top = ranked[0]
    assert "symbol: AuthProvider" in top.reasons
    assert "path: auth" in top.reasons


def test_rank_gives_neighbour_bonus_to_imported_files(tmp_path: Path) -> None:
    files = write_repo(
        tmp_path,
        {
            "irrigation.ts": 'import { balance } from "./water"\nexport function irrigation() {}\n',
            "water.ts": "export function balance() {}\n",
            "other.ts": "export function other() {}\n",
        },
    )
    repo_map = build_repo_map(tmp_path, files)

    ranked = rank_files(tmp_path, files, repo_map, "irrigation")

    water = next(r for r in ranked if r.path == "water.ts")
    assert water.reasons == ["imported by: irrigation.ts"]
    assert "other.ts" not in [r.path for r in ranked]


def test_rank_lists_a_reason_once_but_scores_every_term(tmp_path: Path) -> None:
    files = write_repo(tmp_path, {"risk.ts": "export function heatRiskLevel() {}\n"})
    repo_map = build_repo_map(tmp_path, files)

    both = rank_files(tmp_path, files, repo_map, "heat risk")[0]
    one = rank_files(tmp_path, files, repo_map, "heat")[0]

    assert both.reasons.count("symbol: heatRiskLevel") == 1
    assert both.score > one.score


def test_rank_skips_lockfiles_and_finds_the_named_file(tmp_path: Path) -> None:
    lockfile = '{"name": "mini-shop", "lockfileVersion": 3, "lib": "ts ts ts total cart"}\n' * 50
    files = write_repo(
        tmp_path,
        {
            "package-lock.json": lockfile,
            "frontend/yarn.lock": "total cart lib\n" * 50,
            "lib/cart.ts": "export function total(cart) {\n  return 0\n}\n",
            "app/page.tsx": (
                'import { total } from "@/lib/cart"\nexport default function Home() {}\n'
            ),
        },
    )
    repo_map = build_repo_map(tmp_path, files)
    issue = (
        "The total() function in lib/cart.ts returns 0 instead of summing item prices. "
        "The home page shows Total $0, but it should be $70."
    )

    ranked = rank_files(tmp_path, files, repo_map, issue)

    paths = [r.path for r in ranked]
    # The issue names both the cart module and the home page, so both lead the ranking.
    assert set(paths[:2]) == {"lib/cart.ts", "app/page.tsx"}
    assert "package-lock.json" not in paths and "frontend/yarn.lock" not in paths


def test_rank_returns_nothing_for_filler_only_query(tmp_path: Path) -> None:
    files = write_repo(tmp_path, {"a.ts": "export function a() {}\n"})

    assert rank_files(tmp_path, files, build_repo_map(tmp_path, files), "which is the") == []
