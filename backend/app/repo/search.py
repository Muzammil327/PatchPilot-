import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.repo.repo_map import FileMap, RepoMap
from app.repo.scan import ScannedFile
from app.repo.tests_map import resolve_relative_import

MAX_MATCHES = 50
MAX_MATCHES_PER_FILE = 5
MAX_LINE_LENGTH = 200
DEFAULT_RANK_LIMIT = 10
MIN_TERM_LENGTH = 2

# Ranking weights: names a developer chose say more than incidental content hits.
SYMBOL_WEIGHT = 4.0
PATH_WEIGHT = 3.0
ROUTE_WEIGHT = 3.0
IMPORT_WEIGHT = 2.0
CONTENT_WEIGHT = 1.0
NEIGHBOUR_BONUS = 1.0
NEIGHBOUR_SOURCE_COUNT = 3  # top files whose relative imports earn neighbours a bonus

STOP_WORDS = frozenset(
    {
        "a", "an", "and", "are", "about", "all", "any", "as", "at", "be", "by", "can",
        "code", "do", "does", "file", "files", "find", "for", "from", "has", "have", "how",
        "i", "in", "is", "it", "me", "of", "on", "or", "related", "show", "that", "the",
        "this", "to", "uses", "what", "where", "which", "who", "why", "with",
    }
)  # fmt: skip

CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
WORD = re.compile(r"[A-Za-z0-9]+")

AddScore = Callable[[str, float, str], None]  # (path, points, reason)


@dataclass(frozen=True)
class SearchMatch:
    path: str
    line: int
    text: str


@dataclass(frozen=True)
class SearchResult:
    matches: list[SearchMatch]
    is_truncated: bool


@dataclass(frozen=True)
class RankedFile:
    path: str
    score: float
    reasons: list[str]


def query_terms(query: str) -> list[str]:
    """Lowercased search terms: words split on camelCase/snake_case, minus filler words."""
    terms: list[str] = []
    for word in WORD.findall(query):
        for part in CAMEL_BOUNDARY.split(word):
            term = part.lower()
            if len(term) >= MIN_TERM_LENGTH and term not in STOP_WORDS and term not in terms:
                terms.append(term)
    return terms


def read_text(workspace: Path, path: str) -> str | None:
    """File text, or None for unreadable or binary-looking files."""
    try:
        text = (workspace / path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return None if "\x00" in text else text


def search_code(workspace: Path, files: list[ScannedFile], query: str) -> SearchResult:
    """Case-insensitive literal search for the whole query, line by line."""
    needle = query.strip().lower()
    matches: list[SearchMatch] = []
    if not needle:
        return SearchResult(matches=matches, is_truncated=False)

    for scanned in files:
        text = read_text(workspace, scanned.path)
        if text is None or needle not in text.lower():
            continue
        file_matches = 0
        for number, line in enumerate(text.splitlines(), start=1):
            if needle not in line.lower():
                continue
            if len(matches) >= MAX_MATCHES:
                return SearchResult(matches=matches, is_truncated=True)
            matches.append(
                SearchMatch(path=scanned.path, line=number, text=line.strip()[:MAX_LINE_LENGTH])
            )
            file_matches += 1
            if file_matches >= MAX_MATCHES_PER_FILE:
                break
    return SearchResult(matches=matches, is_truncated=False)


def rank_files(
    workspace: Path,
    files: list[ScannedFile],
    repo_map: RepoMap,
    query: str,
    limit: int = DEFAULT_RANK_LIMIT,
) -> list[RankedFile]:
    terms = query_terms(query)
    if not terms:
        return []

    maps_by_path = {file_map.path: file_map for file_map in repo_map.files}
    scores: dict[str, float] = {}
    reasons: dict[str, list[str]] = {}

    def add(path: str, points: float, reason: str) -> None:
        # A symbol matching two query terms scores twice but is listed once.
        scores[path] = scores.get(path, 0.0) + points
        file_reasons = reasons.setdefault(path, [])
        if reason not in file_reasons:
            file_reasons.append(reason)

    for scanned in files:
        path = scanned.path
        path_lower = path.lower()
        file_map = maps_by_path.get(path)
        text = read_text(workspace, path)
        text_lower = text.lower() if text is not None else ""

        for term in terms:
            if term in path_lower:
                add(path, PATH_WEIGHT, f"path: {term}")
            if file_map is not None:
                score_file_map(file_map, term, path, add)
            hits = text_lower.count(term)
            if hits:
                add(path, CONTENT_WEIGHT * math.log2(1 + hits), f"content: {term} ×{hits}")

    add_neighbour_bonus(scores, maps_by_path, {scanned.path for scanned in files}, add)

    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:limit]
    return [
        RankedFile(path=path, score=round(score, 2), reasons=reasons[path])
        for path, score in ranked
    ]


def score_file_map(file_map: FileMap, term: str, path: str, add: AddScore) -> None:
    names = (
        [function.name for function in file_map.functions]
        + [cls.name for cls in file_map.classes]
        + [name for name in file_map.exports if name not in {"default", "*"}]
    )
    symbol = next((name for name in names if term in name.lower()), None)
    if symbol:
        add(path, SYMBOL_WEIGHT, f"symbol: {symbol}")

    ref = next(
        (
            ref
            for ref in file_map.imports
            if term in ref.source.lower() or any(term in name.lower() for name in ref.names)
        ),
        None,
    )
    if ref:
        add(path, IMPORT_WEIGHT, f"import: {ref.source}")

    route = next((route for route in file_map.routes if term in route.path.lower()), None)
    if route:
        add(path, ROUTE_WEIGHT, f"route: {route.method} {route.path}")


def add_neighbour_bonus(
    scores: dict[str, float],
    maps_by_path: dict[str, FileMap],
    all_paths: set[str],
    add: AddScore,
) -> None:
    """Files one relative import away from the top matches are likely related too."""
    top = sorted(scores, key=lambda path: (-scores[path], path))[:NEIGHBOUR_SOURCE_COUNT]
    for source_path in top:
        file_map = maps_by_path.get(source_path)
        if file_map is None:
            continue
        for ref in file_map.imports:
            target = resolve_relative_import(source_path, ref.source, all_paths)
            if target and target not in top:
                add(target, NEIGHBOUR_BONUS, f"imported by: {source_path}")
