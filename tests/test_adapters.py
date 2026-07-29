"""Tests for HTTP and GitHub registry adapters using fake httpx transports."""

from typing import Any

import httpx
import pytest

from skills_mcp.auth import AuthResolver
from skills_mcp.config.model import GithubRegistry, HttpRegistry, NoAuth
from skills_mcp.errors import (
    PathTraversalError,
    RegistryUnavailableError,
    SkillFileNotFoundError,
    SkillNotFoundError,
    UnsupportedOperationError,
)
from skills_mcp.registries.github import GithubAdapter, _validate_file_path
from skills_mcp.registries.http import HttpAdapter

# ---------------------------------------------------------------------------
# Fake httpx transport
# ---------------------------------------------------------------------------


class FakeTransport(httpx.AsyncBaseTransport):
    """Returns responses from a URL→response dict."""

    def __init__(self, responses: dict[str, httpx.Response]) -> None:
        self._responses = responses

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url).split("?")[0]
        if url in self._responses:
            resp = self._responses[url]
            return resp
        return httpx.Response(404, text="Not found (FakeTransport)")


def fake_client(responses: dict[str, httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=FakeTransport(responses))


def json_response(data: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=data)


def text_response(text: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, text=text)


# ---------------------------------------------------------------------------
# HTTP adapter tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def http_config() -> HttpRegistry:
    return HttpRegistry(
        name="my-http",
        url="https://example.com/SKILL.md",
        skill_name="my-skill",
        auth=NoAuth(),
    )


async def test_http_list_skills_returns_single_name(http_config: HttpRegistry):
    async with fake_client({}) as client:
        adapter = HttpAdapter(http_config, client, AuthResolver())
        result = await adapter.list_skills()
    assert result == ["my-skill"]


async def test_http_fetch_skill_gets_url(http_config: HttpRegistry):
    responses = {"https://example.com/SKILL.md": text_response("# My Skill")}
    async with fake_client(responses) as client:
        adapter = HttpAdapter(http_config, client, AuthResolver())
        sc = await adapter.fetch_skill("my-skill")
    assert sc.content == "# My Skill"
    assert sc.files == ()


async def test_http_fetch_skill_wrong_name_raises(http_config: HttpRegistry):
    async with fake_client({}) as client:
        adapter = HttpAdapter(http_config, client, AuthResolver())
        with pytest.raises(SkillNotFoundError):
            await adapter.fetch_skill("other-skill")


async def test_http_fetch_skill_404_raises(http_config: HttpRegistry):
    responses = {"https://example.com/SKILL.md": text_response("Not found", status=404)}
    async with fake_client(responses) as client:
        adapter = HttpAdapter(http_config, client, AuthResolver())
        with pytest.raises(SkillNotFoundError):
            await adapter.fetch_skill("my-skill")


async def test_http_fetch_skill_5xx_raises(http_config: HttpRegistry):
    responses = {"https://example.com/SKILL.md": text_response("Server error", status=500)}
    async with fake_client(responses) as client:
        adapter = HttpAdapter(http_config, client, AuthResolver())
        with pytest.raises(RegistryUnavailableError):
            await adapter.fetch_skill("my-skill")


async def test_http_fetch_file_raises_unsupported(http_config: HttpRegistry):
    async with fake_client({}) as client:
        adapter = HttpAdapter(http_config, client, AuthResolver())
        with pytest.raises(UnsupportedOperationError):
            await adapter.fetch_file("my-skill", "references/guide.md")


# ---------------------------------------------------------------------------
# GitHub adapter tests
# ---------------------------------------------------------------------------


def _gh_base(owner: str = "acme", repo: str = "skills") -> str:
    return f"https://api.github.com/repos/{owner}/{repo}"


@pytest.fixture()
def gh_config() -> GithubRegistry:
    return GithubRegistry(
        name="gh-skills",
        owner="acme",
        repo="skills",
        skills_dir="skills",
        ref="main",
        auth=NoAuth(),
    )


def _skills_dir_response() -> list[dict[str, Any]]:
    return [
        {"name": "coding", "type": "dir", "sha": "tree-sha-coding"},
        {"name": "git", "type": "dir", "sha": "tree-sha-git"},
        {"name": "README.md", "type": "file", "sha": "blob-sha-readme"},
    ]


def _skill_tree_response(skill_md_sha: str = "blob-skill-md") -> dict[str, Any]:
    return {
        "truncated": False,
        "tree": [
            {"path": "SKILL.md", "type": "blob", "sha": skill_md_sha},
            {"path": "references/guide.md", "type": "blob", "sha": "blob-guide"},
        ],
    }


async def test_github_list_skills_returns_subdirs(gh_config: GithubRegistry):
    responses = {
        f"{_gh_base()}/contents/skills": json_response(_skills_dir_response()),
    }
    async with fake_client(responses) as client:
        adapter = GithubAdapter(gh_config, client, AuthResolver())
        result = await adapter.list_skills()
    assert result == ["coding", "git"]


async def test_github_fetch_skill_calls_tree_and_blob(gh_config: GithubRegistry):
    skill_md_content = "# Coding Skill"
    responses = {
        f"{_gh_base()}/contents/skills": json_response(_skills_dir_response()),
        f"{_gh_base()}/git/trees/tree-sha-coding": json_response(_skill_tree_response()),
        f"{_gh_base()}/git/blobs/blob-skill-md": text_response(skill_md_content),
    }
    async with fake_client(responses) as client:
        adapter = GithubAdapter(gh_config, client, AuthResolver())
        sc = await adapter.fetch_skill("coding")
    assert sc.content == skill_md_content
    assert "references/guide.md" in sc.files


async def test_github_fetch_skill_missing_raises(gh_config: GithubRegistry):
    responses = {
        f"{_gh_base()}/contents/skills": json_response(_skills_dir_response()),
    }
    async with fake_client(responses) as client:
        adapter = GithubAdapter(gh_config, client, AuthResolver())
        with pytest.raises(SkillNotFoundError):
            await adapter.fetch_skill("nonexistent")


async def test_github_fetch_file_returns_content(gh_config: GithubRegistry):
    guide_content = "# Guide"
    responses = {
        f"{_gh_base()}/contents/skills": json_response(_skills_dir_response()),
        f"{_gh_base()}/git/trees/tree-sha-coding": json_response(_skill_tree_response()),
        f"{_gh_base()}/git/blobs/blob-guide": text_response(guide_content),
    }
    async with fake_client(responses) as client:
        adapter = GithubAdapter(gh_config, client, AuthResolver())
        result = await adapter.fetch_file("coding", "references/guide.md")
    assert result == guide_content


async def test_github_fetch_file_unlisted_raises(gh_config: GithubRegistry):
    responses = {
        f"{_gh_base()}/contents/skills": json_response(_skills_dir_response()),
        f"{_gh_base()}/git/trees/tree-sha-coding": json_response(_skill_tree_response()),
    }
    async with fake_client(responses) as client:
        adapter = GithubAdapter(gh_config, client, AuthResolver())
        with pytest.raises(SkillFileNotFoundError):
            await adapter.fetch_file("coding", "secret.txt")


# ---------------------------------------------------------------------------
# Path traversal tests
# ---------------------------------------------------------------------------


def test_dotdot_traversal_rejected():
    with pytest.raises(PathTraversalError):
        _validate_file_path("../../other/file.txt")


def test_absolute_path_rejected():
    with pytest.raises(PathTraversalError):
        _validate_file_path("/etc/passwd")


def test_safe_relative_path_accepted():
    _validate_file_path("references/guide.md")  # must not raise


def test_empty_path_rejected():
    with pytest.raises(PathTraversalError):
        _validate_file_path("")


# ---------------------------------------------------------------------------
# Rate-limit handling tests
# ---------------------------------------------------------------------------


async def test_github_retries_on_429_with_retry_after(gh_config: GithubRegistry):
    """Adapter should wait and retry once on 429 + Retry-After."""
    call_count = 0

    class CountingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            url = str(request.url).split("?")[0]
            if call_count == 1 and url.endswith("/contents/skills"):
                return httpx.Response(
                    429,
                    text="rate limited",
                    headers={"Retry-After": "0"},  # 0s wait for test speed
                )
            if url.endswith("/contents/skills"):
                return json_response(_skills_dir_response())
            return httpx.Response(404)

    async with httpx.AsyncClient(transport=CountingTransport()) as client:
        adapter = GithubAdapter(gh_config, client, AuthResolver())
        result = await adapter.list_skills()
    assert "coding" in result
    assert call_count == 2  # first attempt (429) + one retry


async def test_github_double_rate_limit_returns_unavailable(gh_config: GithubRegistry):
    """Two consecutive 429s should raise RegistryUnavailableError."""

    class AlwaysRateLimited(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, text="rate limited", headers={"Retry-After": "0"})

    async with httpx.AsyncClient(transport=AlwaysRateLimited()) as client:
        adapter = GithubAdapter(gh_config, client, AuthResolver())
        with pytest.raises(RegistryUnavailableError):
            await adapter.list_skills()


# ---------------------------------------------------------------------------
# Spec scenario: Fetches file larger than 1 MB
# ---------------------------------------------------------------------------


async def test_github_fetch_file_large_blob_succeeds(gh_config: GithubRegistry):
    """Companion files > 1 MB must be fetched successfully via the Blobs raw endpoint.
    The adapter uses the same Blobs API path regardless of size, so any content
    length is supported."""
    large_content = "x" * (1024 * 1024 + 1)  # 1 MB + 1 byte
    responses = {
        f"{_gh_base()}/contents/skills": json_response(_skills_dir_response()),
        f"{_gh_base()}/git/trees/tree-sha-coding": json_response(
            {
                "truncated": False,
                "tree": [
                    {"path": "SKILL.md", "type": "blob", "sha": "blob-skill-md"},
                    {"path": "references/large.md", "type": "blob", "sha": "blob-large"},
                ],
            }
        ),
        f"{_gh_base()}/git/blobs/blob-skill-md": text_response("# Coding"),
        f"{_gh_base()}/git/blobs/blob-large": text_response(large_content),
    }
    async with fake_client(responses) as client:
        adapter = GithubAdapter(gh_config, client, AuthResolver())
        result = await adapter.fetch_file("coding", "references/large.md")
    assert len(result) == len(large_content)
    assert result == large_content


async def test_github_fetch_file_skill_md_is_rejected(gh_config: GithubRegistry):
    """get_skill_file('SKILL.md') must raise SkillFileNotFoundError — SKILL.md
    is not a companion file and must not be accessible via this path."""
    responses = {
        f"{_gh_base()}/contents/skills": json_response(_skills_dir_response()),
        f"{_gh_base()}/git/trees/tree-sha-coding": json_response(_skill_tree_response()),
    }
    async with fake_client(responses) as client:
        adapter = GithubAdapter(gh_config, client, AuthResolver())
        with pytest.raises(SkillFileNotFoundError):
            await adapter.fetch_file("coding", "SKILL.md")
