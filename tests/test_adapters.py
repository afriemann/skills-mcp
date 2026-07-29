"""Tests for HTTP and GitHub registry adapters using fake httpx transports."""

# spec: openspec/changes/github-nested-skill-discovery/specs/skills-mcp/spec.md

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
from skills_mcp.registries.github import (
    GithubAdapter,
    _prune_nested,
    _validate_file_path,
    _validate_skill_path,
)
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
    """Adapter should wait and retry once on 429 + Retry-After (root contents call)."""
    call_count = 0

    class CountingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            url = str(request.url).split("?")[0]
            # First call to root contents gets rate-limited
            if call_count == 1 and url.endswith("/contents/"):
                return httpx.Response(
                    429,
                    text="rate limited",
                    headers={"Retry-After": "0"},  # 0s wait for test speed
                )
            if url.endswith("/contents/"):
                return json_response(_root_contents_response())
            if url.endswith("/git/trees/tree-sha-skills-dir"):
                return json_response(_skills_flat_tree_response())
            return httpx.Response(404)

    async with httpx.AsyncClient(transport=CountingTransport()) as client:
        adapter = GithubAdapter(gh_config, client, AuthResolver())
        result = await adapter.list_skills()
    assert "coding" in result
    assert call_count == 3  # 429 on first contents/ + retry + trees call


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


# ---------------------------------------------------------------------------
# Helpers for nested-layout tests
# ---------------------------------------------------------------------------


def _root_contents_response(skills_sha: str = "tree-sha-skills-dir") -> list[dict[str, Any]]:
    """Root listing that includes the 'skills' directory."""
    return [
        {"name": "skills", "type": "dir", "sha": skills_sha},
        {"name": "README.md", "type": "file", "sha": "blob-readme"},
    ]


def _skills_flat_tree_response() -> dict[str, Any]:
    """Recursive tree of skills/ matching the existing flat layout (coding + git)."""
    return {
        "truncated": False,
        "tree": [
            {"path": "coding/SKILL.md", "type": "blob", "sha": "blob-coding-skill-md"},
            {"path": "coding/references/guide.md", "type": "blob", "sha": "blob-guide"},
            {"path": "git/SKILL.md", "type": "blob", "sha": "blob-git-skill-md"},
            {"path": "README.md", "type": "blob", "sha": "blob-readme"},
        ],
    }


def _skills_nested_tree_response() -> dict[str, Any]:
    """Recursive tree of skills/ for a deeply-nested layout."""
    return {
        "truncated": False,
        "tree": [
            {
                "path": "engineering/testing/tdd/SKILL.md",
                "type": "blob",
                "sha": "blob-tdd-skill-md",
            },
            {
                "path": "engineering/testing/tdd/references/guide.md",
                "type": "blob",
                "sha": "blob-tdd-guide",
            },
            {
                "path": "business/brainstorming/SKILL.md",
                "type": "blob",
                "sha": "blob-bs-skill-md",
            },
        ],
    }


# ---------------------------------------------------------------------------
# _validate_skill_path
# ---------------------------------------------------------------------------


def test_validate_skill_path_empty_rejected():
    with pytest.raises(PathTraversalError):
        _validate_skill_path("")


def test_validate_skill_path_absolute_rejected():
    with pytest.raises(PathTraversalError):
        _validate_skill_path("/etc/passwd")


def test_validate_skill_path_dotdot_rejected():
    with pytest.raises(PathTraversalError):
        _validate_skill_path("../secrets")


def test_validate_skill_path_flat_accepted():
    _validate_skill_path("my-skill")  # must not raise


def test_validate_skill_path_nested_accepted():
    _validate_skill_path("engineering/testing/tdd-development")  # must not raise


# ---------------------------------------------------------------------------
# _prune_nested
# ---------------------------------------------------------------------------


def test_prune_nested_drops_descendant():
    result = _prune_nested(["my-skill", "my-skill/references/example"])
    assert result == ["my-skill"]


def test_prune_nested_keeps_siblings():
    result = _prune_nested(["a/b", "a/c"])
    assert "a/b" in result
    assert "a/c" in result


def test_prune_nested_empty():
    assert _prune_nested([]) == []


def test_prune_nested_no_ancestors():
    skills = ["engineering/testing/tdd", "business/brainstorming"]
    result = _prune_nested(skills)
    assert set(result) == set(skills)


# ---------------------------------------------------------------------------
# list_skills — updated and new scenarios
# ---------------------------------------------------------------------------


async def test_github_list_skills_returns_subdirs(gh_config: GithubRegistry):
    """list_skills resolves skills_dir tree SHA then walks recursively (flat layout)."""
    responses = {
        f"{_gh_base()}/contents/": json_response(_root_contents_response()),
        f"{_gh_base()}/git/trees/tree-sha-skills-dir": json_response(_skills_flat_tree_response()),
    }
    async with fake_client(responses) as client:
        adapter = GithubAdapter(gh_config, client, AuthResolver())
        result = await adapter.list_skills()
    assert result == ["coding", "git"]


async def test_github_list_skills_nested_layout(gh_config: GithubRegistry):
    """list_skills returns slash-delimited paths for nested skill layouts."""
    responses = {
        f"{_gh_base()}/contents/": json_response(_root_contents_response()),
        f"{_gh_base()}/git/trees/tree-sha-skills-dir": json_response(
            _skills_nested_tree_response()
        ),
    }
    async with fake_client(responses) as client:
        adapter = GithubAdapter(gh_config, client, AuthResolver())
        result = await adapter.list_skills()
    assert result == ["business/brainstorming", "engineering/testing/tdd"]


async def test_github_list_skills_non_skill_dir_excluded(gh_config: GithubRegistry):
    """Subdirectories with no SKILL.md are not returned."""
    tree = {
        "truncated": False,
        "tree": [
            {"path": "real-skill/SKILL.md", "type": "blob", "sha": "blob-skill-md"},
            {"path": "no-skill-here/README.md", "type": "blob", "sha": "blob-readme"},
        ],
    }
    responses = {
        f"{_gh_base()}/contents/": json_response(_root_contents_response()),
        f"{_gh_base()}/git/trees/tree-sha-skills-dir": json_response(tree),
    }
    async with fake_client(responses) as client:
        adapter = GithubAdapter(gh_config, client, AuthResolver())
        result = await adapter.list_skills()
    assert result == ["real-skill"]
    assert "no-skill-here" not in result


async def test_github_list_skills_bundled_skill_md_pruned(gh_config: GithubRegistry):
    """A SKILL.md nested inside a skill's companion files is not a phantom skill."""
    tree = {
        "truncated": False,
        "tree": [
            {"path": "my-skill/SKILL.md", "type": "blob", "sha": "blob-skill-md"},
            {
                "path": "my-skill/references/example/SKILL.md",
                "type": "blob",
                "sha": "blob-example-skill-md",
            },
        ],
    }
    responses = {
        f"{_gh_base()}/contents/": json_response(_root_contents_response()),
        f"{_gh_base()}/git/trees/tree-sha-skills-dir": json_response(tree),
    }
    async with fake_client(responses) as client:
        adapter = GithubAdapter(gh_config, client, AuthResolver())
        result = await adapter.list_skills()
    assert result == ["my-skill"]


async def test_github_list_skills_missing_skills_dir_raises_unavailable(
    gh_config: GithubRegistry,
):
    """skills_dir entry absent in root listing → RegistryUnavailableError."""
    responses = {
        f"{_gh_base()}/contents/": json_response(
            [{"name": "README.md", "type": "file", "sha": "blob-readme"}]
        ),
    }
    async with fake_client(responses) as client:
        adapter = GithubAdapter(gh_config, client, AuthResolver())
        with pytest.raises(RegistryUnavailableError):
            await adapter.list_skills()


# ---------------------------------------------------------------------------
# fetch_skill / fetch_file — nested scenarios and traversal guard
# ---------------------------------------------------------------------------


async def test_github_fetch_skill_nested(gh_config: GithubRegistry):
    """fetch_skill works with a slash-delimited nested skill name."""
    skill_md_content = "# TDD Skill"
    responses = {
        # _get_tree_sha_for_dir("skills/engineering/testing/tdd") → Contents("skills/engineering/testing")
        f"{_gh_base()}/contents/skills/engineering/testing": json_response(
            [{"name": "tdd", "type": "dir", "sha": "tree-sha-tdd"}]
        ),
        f"{_gh_base()}/git/trees/tree-sha-tdd": json_response(_skill_tree_response()),
        f"{_gh_base()}/git/blobs/blob-skill-md": text_response(skill_md_content),
    }
    async with fake_client(responses) as client:
        adapter = GithubAdapter(gh_config, client, AuthResolver())
        sc = await adapter.fetch_skill("engineering/testing/tdd")
    assert sc.content == skill_md_content
    assert "references/guide.md" in sc.files


async def test_github_fetch_file_nested(gh_config: GithubRegistry):
    """fetch_file works with a slash-delimited nested skill name."""
    guide_content = "# Nested Guide"
    responses = {
        f"{_gh_base()}/contents/skills/engineering/testing": json_response(
            [{"name": "tdd", "type": "dir", "sha": "tree-sha-tdd"}]
        ),
        f"{_gh_base()}/git/trees/tree-sha-tdd": json_response(_skill_tree_response()),
        f"{_gh_base()}/git/blobs/blob-guide": text_response(guide_content),
    }
    async with fake_client(responses) as client:
        adapter = GithubAdapter(gh_config, client, AuthResolver())
        result = await adapter.fetch_file("engineering/testing/tdd", "references/guide.md")
    assert result == guide_content


async def test_github_fetch_skill_traversal_rejected(gh_config: GithubRegistry):
    """A skill name containing .. is rejected without any I/O."""
    async with fake_client({}) as client:
        adapter = GithubAdapter(gh_config, client, AuthResolver())
        with pytest.raises(PathTraversalError):
            await adapter.fetch_skill("../secrets")


async def test_github_fetch_file_skill_traversal_rejected(gh_config: GithubRegistry):
    """A skill name containing .. in fetch_file is rejected without any I/O."""
    async with fake_client({}) as client:
        adapter = GithubAdapter(gh_config, client, AuthResolver())
        with pytest.raises(PathTraversalError):
            await adapter.fetch_file("../secrets", "guide.md")


async def test_github_fetch_skill_nested_missing_raises_not_found(gh_config: GithubRegistry):
    """A missing nested skill raises SkillNotFoundError (agent-recoverable)."""
    responses = {
        # Parent dir exists but 'tdd' entry is absent
        f"{_gh_base()}/contents/skills/engineering/testing": json_response(
            [{"name": "playwright", "type": "dir", "sha": "tree-sha-pw"}]
        ),
    }
    async with fake_client(responses) as client:
        adapter = GithubAdapter(gh_config, client, AuthResolver())
        with pytest.raises(SkillNotFoundError):
            await adapter.fetch_skill("engineering/testing/tdd")


async def test_github_fetch_skill_missing_skills_dir_raises_unavailable(
    gh_config: GithubRegistry,
):
    """A missing skills_dir (Contents 404) raises RegistryUnavailableError (infra)."""
    # FakeTransport returns 404 for everything → _get_contents("skills") 404s
    async with fake_client({}) as client:
        adapter = GithubAdapter(gh_config, client, AuthResolver())
        with pytest.raises(RegistryUnavailableError):
            await adapter.fetch_skill("coding")


# ---------------------------------------------------------------------------
# _get_root_tree_sha (via list_skills with skills_dir="")
# ---------------------------------------------------------------------------


@pytest.fixture()
def gh_config_root() -> GithubRegistry:
    """GitHub registry with empty skills_dir — skills live at repo root."""
    return GithubRegistry(
        name="gh-root",
        owner="acme",
        repo="skills",
        skills_dir="",
        ref="main",
        auth=NoAuth(),
    )


async def test_github_list_skills_empty_skills_dir(gh_config_root: GithubRegistry):
    """list_skills with skills_dir='' resolves root tree SHA via Commits API."""
    responses = {
        f"{_gh_base()}/commits/main": json_response({"commit": {"tree": {"sha": "root-tree-sha"}}}),
        f"{_gh_base()}/git/trees/root-tree-sha": json_response(
            {
                "truncated": False,
                "tree": [{"path": "coding/SKILL.md", "type": "blob", "sha": "blob-md"}],
            }
        ),
    }
    async with fake_client(responses) as client:
        adapter = GithubAdapter(gh_config_root, client, AuthResolver())
        result = await adapter.list_skills()
    assert result == ["coding"]


async def test_github_list_skills_empty_skills_dir_ref_not_found(
    gh_config_root: GithubRegistry,
):
    """A 404 on the Commits API (bad ref) raises RegistryUnavailableError."""
    async with fake_client({}) as client:
        adapter = GithubAdapter(gh_config_root, client, AuthResolver())
        with pytest.raises(RegistryUnavailableError):
            await adapter.list_skills()


async def test_github_list_skills_empty_skills_dir_malformed_commits_response(
    gh_config_root: GithubRegistry,
):
    """A Commits API response missing tree.sha raises RegistryUnavailableError."""
    responses = {
        f"{_gh_base()}/commits/main": json_response({"commit": {}}),
    }
    async with fake_client(responses) as client:
        adapter = GithubAdapter(gh_config_root, client, AuthResolver())
        with pytest.raises(RegistryUnavailableError):
            await adapter.list_skills()


# ---------------------------------------------------------------------------
# Root-level SKILL.md exclusion
# ---------------------------------------------------------------------------


async def test_github_list_skills_root_skill_md_excluded(gh_config: GithubRegistry):
    """A SKILL.md directly at the skills_dir root is excluded (no empty skill name)."""
    tree = {
        "truncated": False,
        "tree": [
            # Root-level: path has no "/" prefix — must not be returned
            {"path": "SKILL.md", "type": "blob", "sha": "blob-root-md"},
            # Normal skill one level deep — must be returned
            {"path": "real-skill/SKILL.md", "type": "blob", "sha": "blob-skill-md"},
        ],
    }
    responses = {
        f"{_gh_base()}/contents/": json_response(_root_contents_response()),
        f"{_gh_base()}/git/trees/tree-sha-skills-dir": json_response(tree),
    }
    async with fake_client(responses) as client:
        adapter = GithubAdapter(gh_config, client, AuthResolver())
        result = await adapter.list_skills()
    assert result == ["real-skill"]
    assert "" not in result
