import pytest

from app.repo.tests_map import is_test_file, link_tests, resolve_relative_import


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("src/cart.test.ts", True),
        ("src/cart.spec.tsx", True),
        ("lib/util.test.mjs", True),
        ("src/__tests__/cart.ts", True),
        ("tests/helpers.js", True),
        ("test/setup.ts", True),
        ("src/cart.ts", False),
        ("src/testing.ts", False),
        ("src/contest/page.tsx", False),
    ],
)
def test_is_test_file(path: str, expected: bool) -> None:
    assert is_test_file(path) is expected


ALL_PATHS = {
    "src/cart.ts",
    "src/lib/index.ts",
    "src/money.tsx",
    "src/cart.test.ts",
    "src/__tests__/money.test.tsx",
    "src/orphan.test.ts",
    "src/helpers.test.ts",
}


@pytest.mark.parametrize(
    ("module", "expected"),
    [
        ("./cart", "src/cart.ts"),
        ("./cart.ts", "src/cart.ts"),
        ("./lib", "src/lib/index.ts"),
        ("../src/money", "src/money.tsx"),
        ("./missing", None),
        ("react", None),
        ("@/lib", None),
        ("../../outside", None),
    ],
)
def test_resolve_relative_import(module: str, expected: str | None) -> None:
    assert resolve_relative_import("src/cart.test.ts", module, ALL_PATHS) == expected


def test_link_tests_uses_imports_then_naming() -> None:
    links = link_tests(
        {
            "src/cart.test.ts": ["vitest", "./cart", "./lib", "./helpers.test"],
            "src/__tests__/money.test.tsx": ["@testing-library/react"],
            "src/orphan.test.ts": [],
            "src/cart.ts": ["./lib"],
        },
        ALL_PATHS,
    )

    assert {link.test_file: link.source_files for link in links} == {
        "src/cart.test.ts": ["src/cart.ts", "src/lib/index.ts"],
        "src/__tests__/money.test.tsx": ["src/money.tsx"],
        "src/orphan.test.ts": [],
    }
