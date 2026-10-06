import asyncio
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.config import Settings, get_settings
from app.repo.ask import AskPrompt, build_ask_prompt
from app.repo.clone import GitHubRepoRef, clone_repository, parse_github_url
from app.repo.errors import RepoNotFoundError, RepoTooLargeError
from app.repo.repo_map import RepoMap, build_repo_map
from app.repo.scan import ScannedFile, scan_workspace
from app.repo.search import RankedFile, SearchResult, rank_files, search_code
from app.repo.stack import Stack, detect_stack
from app.repo.workspace import directory_size_bytes, remove_workspace

logger = logging.getLogger(__name__)

MAX_FILES_IN_SUMMARY = 500
BYTES_PER_MB = 1024 * 1024
BYTES_PER_KB = 1024

CloneFn = Callable[[GitHubRepoRef, Path, float], None]


@dataclass(frozen=True)
class RepoSummary:
    repo_id: str
    name: str
    url: str
    stack: Stack
    file_count: int
    skipped_count: int
    is_truncated: bool
    files: list[ScannedFile]  # first MAX_FILES_IN_SUMMARY files
    function_count: int
    class_count: int
    route_count: int
    test_file_count: int


@dataclass(frozen=True)
class RepoRecord:
    summary: RepoSummary
    repo_map: RepoMap
    workspace: Path
    files: list[ScannedFile]  # every scanned file, not just the summary's first page


class RepoService:
    """Clones, scans, and maps repositories. The registry is in memory and resets on restart."""

    def __init__(self, settings: Settings, clone: CloneFn = clone_repository):
        self._settings = settings
        self._clone = clone
        self._repos: dict[str, RepoRecord] = {}

    async def connect(self, url: str) -> RepoSummary:
        ref = parse_github_url(url)
        repo_id = uuid.uuid4().hex
        workspace = self._settings.workspace_root / repo_id
        self._settings.workspace_root.mkdir(parents=True, exist_ok=True)

        try:
            record = await asyncio.to_thread(self._build_record, ref, repo_id, workspace)
        except Exception:
            await asyncio.to_thread(remove_workspace, workspace)
            raise

        self._repos[repo_id] = record
        summary = record.summary
        logger.info(
            "repo connected id=%s name=%s files=%d skipped=%d mapped=%d map_failed=%d",
            repo_id,
            ref.full_name,
            summary.file_count,
            summary.skipped_count,
            record.repo_map.parsed_count,
            record.repo_map.failed_count,
        )
        return summary

    def get(self, repo_id: str) -> RepoSummary:
        return self._get_record(repo_id).summary

    def get_map(self, repo_id: str) -> RepoMap:
        return self._get_record(repo_id).repo_map

    async def search(self, repo_id: str, query: str) -> SearchResult:
        record = self._get_record(repo_id)
        return await asyncio.to_thread(search_code, record.workspace, record.files, query)

    async def rank(self, repo_id: str, query: str) -> list[RankedFile]:
        record = self._get_record(repo_id)
        return await asyncio.to_thread(
            rank_files, record.workspace, record.files, record.repo_map, query
        )

    async def build_ask_prompt(self, repo_id: str, question: str) -> AskPrompt:
        record = self._get_record(repo_id)
        ranked = await self.rank(repo_id, question)
        return await asyncio.to_thread(build_ask_prompt, record.workspace, ranked, question)

    def _get_record(self, repo_id: str) -> RepoRecord:
        record = self._repos.get(repo_id)
        if record is None:
            raise RepoNotFoundError(f"Unknown repo id {repo_id!r}")
        return record

    def _build_record(self, ref: GitHubRepoRef, repo_id: str, workspace: Path) -> RepoRecord:
        settings = self._settings
        self._clone(ref, workspace, settings.clone_timeout_seconds)

        size = directory_size_bytes(workspace)
        if size > settings.max_repo_size_mb * BYTES_PER_MB:
            raise RepoTooLargeError(f"{ref.full_name} is {size} bytes")

        scan = scan_workspace(
            workspace,
            max_files=settings.max_scan_files,
            max_file_size_bytes=settings.max_file_size_kb * BYTES_PER_KB,
        )
        repo_map = build_repo_map(workspace, scan.files)
        summary = RepoSummary(
            repo_id=repo_id,
            name=ref.full_name,
            url=f"https://github.com/{ref.full_name}",
            stack=detect_stack(workspace, scan.files),
            file_count=len(scan.files),
            skipped_count=scan.skipped_count,
            is_truncated=scan.is_truncated,
            files=scan.files[:MAX_FILES_IN_SUMMARY],
            function_count=repo_map.function_count,
            class_count=repo_map.class_count,
            route_count=len(repo_map.routes),
            test_file_count=len(repo_map.test_links),
        )
        return RepoRecord(summary=summary, repo_map=repo_map, workspace=workspace, files=scan.files)


@lru_cache
def get_repo_service() -> RepoService:
    return RepoService(get_settings())
