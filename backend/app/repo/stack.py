import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from app.repo.scan import ScannedFile

logger = logging.getLogger(__name__)

StackLanguage = Literal["typescript", "javascript", "unknown"]

# Checked in order; a repo can match several (e.g. Next.js + React).
FRAMEWORK_PACKAGES = (
    ("next", "Next.js"),
    ("react", "React"),
    ("vue", "Vue"),
    ("svelte", "Svelte"),
    ("@angular/core", "Angular"),
    ("express", "Express"),
    ("fastify", "Fastify"),
    ("@nestjs/core", "NestJS"),
    ("koa", "Koa"),
    ("hono", "Hono"),
)

LOCKFILE_PACKAGE_MANAGERS = (
    ("pnpm-lock.yaml", "pnpm"),
    ("yarn.lock", "yarn"),
    ("bun.lock", "bun"),
    ("bun.lockb", "bun"),
    ("package-lock.json", "npm"),
)

TRACKED_SCRIPTS = ("test", "lint", "build")


@dataclass(frozen=True)
class Stack:
    language: StackLanguage
    frameworks: list[str] = field(default_factory=list)
    package_manager: str | None = None
    scripts: dict[str, str] = field(default_factory=dict)  # test/lint/build -> command


def read_package_json(root: Path) -> dict:
    package_json = root / "package.json"
    if not package_json.is_file():
        return {}
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        logger.warning("unreadable package.json in %s", root.name)
        return {}
    return data if isinstance(data, dict) else {}


def detect_stack(root: Path, files: list[ScannedFile]) -> Stack:
    """Detect the JS/TS stack from the root package.json and the scanned files."""
    package = read_package_json(root)
    dependencies = {
        name
        for key in ("dependencies", "devDependencies")
        if isinstance(package.get(key), dict)
        for name in package[key]
    }
    languages = {scanned.language for scanned in files}

    if (
        "typescript" in languages
        or "typescript" in dependencies
        or (root / "tsconfig.json").is_file()
    ):
        language: StackLanguage = "typescript"
    elif "javascript" in languages or package:
        language = "javascript"
    else:
        language = "unknown"

    scripts = package.get("scripts") if isinstance(package.get("scripts"), dict) else {}
    return Stack(
        language=language,
        frameworks=[label for name, label in FRAMEWORK_PACKAGES if name in dependencies],
        package_manager=next(
            (
                manager
                for lockfile, manager in LOCKFILE_PACKAGE_MANAGERS
                if (root / lockfile).is_file()
            ),
            "npm" if package else None,
        ),
        scripts={
            name: str(scripts[name])
            for name in TRACKED_SCRIPTS
            if isinstance(scripts.get(name), str)
        },
    )
