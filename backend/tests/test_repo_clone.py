import pytest

from app.repo.clone import parse_github_url
from app.repo.errors import InvalidRepoUrlError


@pytest.mark.parametrize(
    ("url", "full_name"),
    [
        ("https://github.com/vercel/next.js", "vercel/next.js"),
        ("https://github.com/vercel/next.js/", "vercel/next.js"),
        ("https://github.com/vercel/next.js.git", "vercel/next.js"),
        ("  https://github.com/owner-1/repo_name  ", "owner-1/repo_name"),
    ],
)
def test_parse_github_url_accepts_public_repo_urls(url: str, full_name: str) -> None:
    ref = parse_github_url(url)

    assert ref.full_name == full_name
    assert ref.clone_url == f"https://github.com/{full_name}.git"


@pytest.mark.parametrize(
    "url",
    [
        "",
        "http://github.com/owner/repo",
        "https://gitlab.com/owner/repo",
        "https://github.com/owner",
        "https://github.com/owner/repo/tree/main",
        "https://github.com/owner/..",
        "https://github.com/-owner/repo",
        "git@github.com:owner/repo.git",
        "https://github.com/owner/repo?x=1",
        "file:///etc/passwd",
    ],
)
def test_parse_github_url_rejects_everything_else(url: str) -> None:
    with pytest.raises(InvalidRepoUrlError):
        parse_github_url(url)
