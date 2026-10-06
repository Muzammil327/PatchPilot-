from pathlib import Path

from app.repo.repo_map import build_repo_map
from app.repo.routes import find_next_routes
from app.repo.scan import ScannedFile


def build(tmp_path: Path, files: dict[str, str]):
    scanned = []
    for relative, content in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        scanned.append(ScannedFile(path=relative, language="typescript", size_bytes=1))
    return build_repo_map(tmp_path, scanned)


def route_tuples(repo_map) -> list[tuple[str, str, str, str]]:
    return [(r.method, r.path, r.kind, r.file) for r in repo_map.routes]


def test_next_app_router_pages_and_api_routes(tmp_path: Path) -> None:
    repo_map = build(
        tmp_path,
        {
            "web/next.config.ts": "export default {}",
            "web/app/page.tsx": "export default function Home() {}",
            "web/app/(marketing)/about/page.tsx": "export default function About() {}",
            "web/app/users/[id]/page.tsx": "export default function User() {}",
            "web/app/@modal/login/page.tsx": "export default function Login() {}",
            "web/app/_internal/page.tsx": "export default function Hidden() {}",
            "web/app/layout.tsx": "export default function Layout() {}",
            "web/app/api/items/route.ts": (
                "export async function GET() {}\n\nexport const POST = async () => {}\n"
            ),
        },
    )

    assert route_tuples(repo_map) == [
        ("GET", "/", "page", "web/app/page.tsx"),
        ("GET", "/about", "page", "web/app/(marketing)/about/page.tsx"),
        ("GET", "/users/[id]", "page", "web/app/users/[id]/page.tsx"),
        ("GET", "/login", "page", "web/app/@modal/login/page.tsx"),
        ("GET", "/api/items", "api", "web/app/api/items/route.ts"),
        ("POST", "/api/items", "api", "web/app/api/items/route.ts"),
    ]
    post = repo_map.routes[-1]
    assert post.line == 3


def test_next_src_app_dir_uses_config_one_level_up() -> None:
    routes = find_next_routes("src/app/dashboard/page.tsx", ["default"], {}, {"next.config.mjs"})

    assert [(r.method, r.path) for r in routes] == [("GET", "/dashboard")]


def test_next_pages_router() -> None:
    all_paths = {"next.config.js"}

    def urls(path: str) -> list[tuple[str, str, str]]:
        return [(r.method, r.path, r.kind) for r in find_next_routes(path, [], {}, all_paths)]

    assert urls("pages/index.tsx") == [("GET", "/", "page")]
    assert urls("pages/blog/[slug].tsx") == [("GET", "/blog/[slug]", "page")]
    assert urls("pages/api/users.ts") == [("*", "/api/users", "api")]
    assert urls("pages/_app.tsx") == []


def test_app_folder_without_next_config_is_not_a_router() -> None:
    assert find_next_routes("app/page.tsx", ["default"], {}, {"package.json"}) == []


def test_express_routes_with_import(tmp_path: Path) -> None:
    repo_map = build(
        tmp_path,
        {
            "server.ts": (
                'import express from "express"\n'
                "const app = express()\n"
                'app.get("/health", (req, res) => res.send("ok"))\n'
                "function mount(router) {\n"
                "  router.post(`/orders`, handler)\n"
                '  router.all("/admin", handler)\n'
                "}\n"
                "app.get(`/x/${id}`, handler)\n"
                'app.get("relative", handler)\n'
            ),
        },
    )

    assert [(r.method, r.path, r.line) for r in repo_map.routes] == [
        ("GET", "/health", 3),
        ("POST", "/orders", 5),
        ("*", "/admin", 6),
    ]


def test_express_routes_with_require(tmp_path: Path) -> None:
    repo_map = build(
        tmp_path,
        {
            "app.js": (
                'const express = require("express")\n'
                "const router = express.Router()\n"
                'router.delete("/items/:id", remove)\n'
            ),
        },
    )

    assert [(r.method, r.path) for r in repo_map.routes] == [("DELETE", "/items/:id")]


def test_client_calls_are_not_routes(tmp_path: Path) -> None:
    repo_map = build(
        tmp_path,
        {
            "client.ts": (
                'import axios from "axios"\n'
                "// talks to the express backend\n"
                'axios.get("/api/users")\n'
                'cache.get("/home")\n'
            ),
        },
    )

    assert repo_map.routes == []
