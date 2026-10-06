import json
from pathlib import Path

from app.repo.scan import ScannedFile
from app.repo.stack import detect_stack


def test_detects_typescript_next_app(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "dependencies": {"next": "16.0.0", "react": "19.0.0"},
                "devDependencies": {"typescript": "5.0.0"},
                "scripts": {"dev": "next dev", "build": "next build", "lint": "eslint"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "pnpm-lock.yaml").write_text("", encoding="utf-8")

    stack = detect_stack(tmp_path, [])

    assert stack.language == "typescript"
    assert stack.frameworks == ["Next.js", "React"]
    assert stack.package_manager == "pnpm"
    assert stack.scripts == {"lint": "eslint", "build": "next build"}


def test_detects_plain_javascript_express(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"dependencies": {"express": "5.0.0"}, "scripts": {"test": "jest"}}),
        encoding="utf-8",
    )
    files = [ScannedFile(path="server.js", language="javascript", size_bytes=10)]

    stack = detect_stack(tmp_path, files)

    assert stack.language == "javascript"
    assert stack.frameworks == ["Express"]
    assert stack.package_manager == "npm"
    assert stack.scripts == {"test": "jest"}


def test_handles_repo_without_package_json(tmp_path: Path) -> None:
    files = [ScannedFile(path="main.go", language="other", size_bytes=10)]

    stack = detect_stack(tmp_path, files)

    assert stack.language == "unknown"
    assert stack.frameworks == []
    assert stack.package_manager is None
    assert stack.scripts == {}


def test_ignores_wrongly_typed_package_fields(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"dependencies": ["next"], "scripts": "build"}), encoding="utf-8"
    )

    stack = detect_stack(tmp_path, [])

    assert stack.frameworks == []
    assert stack.scripts == {}


def test_ignores_malformed_package_json(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{ not json", encoding="utf-8")

    stack = detect_stack(tmp_path, [])

    assert stack.language == "unknown"
    assert stack.scripts == {}
