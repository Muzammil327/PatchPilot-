import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.api.llm import get_llm_client, to_llm_http_error
from app.llm.client import LLMClient, LLMError
from app.repo.ask import SYSTEM_PROMPT
from app.repo.errors import (
    CloneFailedError,
    CloneTimeoutError,
    InvalidRepoUrlError,
    RepoError,
    RepoNotFoundError,
    RepoTooLargeError,
    RepoUnavailableError,
)
from app.repo.repo_map import RepoMap
from app.repo.search import RankedFile
from app.repo.service import RepoService, RepoSummary, get_repo_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/repos")

MAX_URL_LENGTH = 300
MAX_QUERY_LENGTH = 200
MAX_QUESTION_LENGTH = 1000

STATUS_BY_ERROR: dict[type[RepoError], int] = {
    InvalidRepoUrlError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    RepoUnavailableError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    RepoTooLargeError: status.HTTP_413_CONTENT_TOO_LARGE,
    CloneTimeoutError: status.HTTP_504_GATEWAY_TIMEOUT,
    CloneFailedError: status.HTTP_502_BAD_GATEWAY,
    RepoNotFoundError: status.HTTP_404_NOT_FOUND,
}


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class RepoConnectRequest(BaseModel):
    url: str = Field(min_length=1, max_length=MAX_URL_LENGTH)


class StackResponse(CamelModel):
    language: str
    frameworks: list[str]
    package_manager: str | None
    scripts: dict[str, str]


class RepoFileResponse(CamelModel):
    path: str
    language: str
    size_bytes: int


class RepoSummaryResponse(CamelModel):
    repo_id: str
    name: str
    url: str
    stack: StackResponse
    file_count: int
    skipped_count: int
    is_truncated: bool
    files: list[RepoFileResponse]
    function_count: int
    class_count: int
    route_count: int
    test_file_count: int


class FunctionSymbolResponse(CamelModel):
    name: str
    line: int


class ClassSymbolResponse(CamelModel):
    name: str
    line: int
    methods: list[str]


class ImportRefResponse(CamelModel):
    source: str
    names: list[str]


class FileMapResponse(CamelModel):
    path: str
    functions: list[FunctionSymbolResponse]
    classes: list[ClassSymbolResponse]
    imports: list[ImportRefResponse]
    exports: list[str]


class RouteResponse(CamelModel):
    method: str
    path: str
    file: str
    line: int
    kind: str


class TestLinkResponse(CamelModel):
    test_file: str
    source_files: list[str]


class RepoMapResponse(CamelModel):
    files: list[FileMapResponse]
    parsed_count: int
    failed_count: int
    routes: list[RouteResponse]
    test_links: list[TestLinkResponse]


class SearchMatchResponse(CamelModel):
    path: str
    line: int
    text: str


class SearchResponse(CamelModel):
    matches: list[SearchMatchResponse]
    is_truncated: bool


class RankedFileResponse(CamelModel):
    path: str
    score: float
    reasons: list[str]


class RelevantFilesResponse(CamelModel):
    files: list[RankedFileResponse]


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_LENGTH)


class AskResponse(CamelModel):
    answer: str
    model: str
    latency_ms: int
    files: list[RankedFileResponse]


def to_ranked_responses(files: list[RankedFile]) -> list[RankedFileResponse]:
    return [RankedFileResponse(path=f.path, score=f.score, reasons=f.reasons) for f in files]


def require_text(value: str, field: str) -> str:
    text = value.strip()
    if not text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{field} must not be empty")
    return text


def to_map_response(repo_map: RepoMap) -> RepoMapResponse:
    return RepoMapResponse(
        files=[
            FileMapResponse(
                path=file.path,
                functions=[
                    FunctionSymbolResponse(name=f.name, line=f.line) for f in file.functions
                ],
                classes=[
                    ClassSymbolResponse(name=c.name, line=c.line, methods=c.methods)
                    for c in file.classes
                ],
                imports=[ImportRefResponse(source=i.source, names=i.names) for i in file.imports],
                exports=file.exports,
            )
            for file in repo_map.files
        ],
        parsed_count=repo_map.parsed_count,
        failed_count=repo_map.failed_count,
        routes=[
            RouteResponse(method=r.method, path=r.path, file=r.file, line=r.line, kind=r.kind)
            for r in repo_map.routes
        ],
        test_links=[
            TestLinkResponse(test_file=link.test_file, source_files=link.source_files)
            for link in repo_map.test_links
        ],
    )


def to_response(summary: RepoSummary) -> RepoSummaryResponse:
    stack = summary.stack
    return RepoSummaryResponse(
        repo_id=summary.repo_id,
        name=summary.name,
        url=summary.url,
        stack=StackResponse(
            language=stack.language,
            frameworks=stack.frameworks,
            package_manager=stack.package_manager,
            scripts=stack.scripts,
        ),
        file_count=summary.file_count,
        skipped_count=summary.skipped_count,
        is_truncated=summary.is_truncated,
        files=[
            RepoFileResponse(path=file.path, language=file.language, size_bytes=file.size_bytes)
            for file in summary.files
        ],
        function_count=summary.function_count,
        class_count=summary.class_count,
        route_count=summary.route_count,
        test_file_count=summary.test_file_count,
    )


def to_http_error(error: RepoError) -> HTTPException:
    logger.warning("repo request failed: %s: %s", type(error).__name__, error)
    status_code = STATUS_BY_ERROR.get(type(error), status.HTTP_500_INTERNAL_SERVER_ERROR)
    return HTTPException(status_code, error.public_message)


RepoServiceDep = Annotated[RepoService, Depends(get_repo_service)]


@router.post(
    "",
    response_model=RepoSummaryResponse,
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
)
async def create_repo(body: RepoConnectRequest, repos: RepoServiceDep) -> RepoSummaryResponse:
    try:
        summary = await repos.connect(body.url)
    except RepoError as exc:
        raise to_http_error(exc) from exc
    return to_response(summary)


@router.get("/{repo_id}/map", response_model=RepoMapResponse, response_model_by_alias=True)
async def get_repo_map(repo_id: str, repos: RepoServiceDep) -> RepoMapResponse:
    try:
        repo_map = repos.get_map(repo_id)
    except RepoError as exc:
        raise to_http_error(exc) from exc
    return to_map_response(repo_map)


SearchQuery = Annotated[str, Query(min_length=1, max_length=MAX_QUERY_LENGTH)]


@router.get("/{repo_id}/search", response_model=SearchResponse, response_model_by_alias=True)
async def search_repo(repo_id: str, q: SearchQuery, repos: RepoServiceDep) -> SearchResponse:
    try:
        result = await repos.search(repo_id, require_text(q, "Query"))
    except RepoError as exc:
        raise to_http_error(exc) from exc
    return SearchResponse(
        matches=[
            SearchMatchResponse(path=m.path, line=m.line, text=m.text) for m in result.matches
        ],
        is_truncated=result.is_truncated,
    )


@router.get(
    "/{repo_id}/relevant", response_model=RelevantFilesResponse, response_model_by_alias=True
)
async def get_relevant_files(
    repo_id: str, q: SearchQuery, repos: RepoServiceDep
) -> RelevantFilesResponse:
    try:
        ranked = await repos.rank(repo_id, require_text(q, "Query"))
    except RepoError as exc:
        raise to_http_error(exc) from exc
    return RelevantFilesResponse(files=to_ranked_responses(ranked))


@router.post("/{repo_id}/ask", response_model=AskResponse, response_model_by_alias=True)
async def ask_repo(
    repo_id: str,
    body: AskRequest,
    repos: RepoServiceDep,
    llm: Annotated[LLMClient, Depends(get_llm_client)],
) -> AskResponse:
    question = require_text(body.question, "Question")
    try:
        ask_prompt = await repos.build_ask_prompt(repo_id, question)
    except RepoError as exc:
        raise to_http_error(exc) from exc
    try:
        completion = await llm.complete(ask_prompt.prompt, role="worker", system=SYSTEM_PROMPT)
    except LLMError as exc:
        raise to_llm_http_error(exc) from exc
    return AskResponse(
        answer=completion.output,
        model=completion.model,
        latency_ms=completion.latency_ms,
        files=to_ranked_responses(ask_prompt.files),
    )


@router.get("/{repo_id}", response_model=RepoSummaryResponse, response_model_by_alias=True)
async def get_repo(repo_id: str, repos: RepoServiceDep) -> RepoSummaryResponse:
    try:
        summary = repos.get(repo_id)
    except RepoError as exc:
        raise to_http_error(exc) from exc
    return to_response(summary)
