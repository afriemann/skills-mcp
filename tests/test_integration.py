"""Integration tests using in-memory MCP transport (create_connected_server_and_client_session)."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from skills_mcp.server import build_app

# ---------------------------------------------------------------------------
# Fake httpx transport
# ---------------------------------------------------------------------------


def _gh_base() -> str:
    return "https://api.github.com/repos/acme/skills"


def _skills_dir() -> list[dict[str, Any]]:
    return [
        {"name": "coding", "type": "dir", "sha": "tree-sha-coding"},
        {"name": "git", "type": "dir", "sha": "tree-sha-git"},
    ]


def _skill_tree() -> dict[str, Any]:
    return {
        "truncated": False,
        "tree": [
            {"path": "SKILL.md", "type": "blob", "sha": "blob-skill-md"},
            {"path": "references/guide.md", "type": "blob", "sha": "blob-guide"},
        ],
    }


class IntegrationTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url).split("?")[0]
        # list_skills: resolve skills_dir tree SHA from root listing
        if url == f"{_gh_base()}/contents/":
            return httpx.Response(
                200,
                json=[{"name": "skills", "type": "dir", "sha": "tree-sha-skills-dir"}],
            )
        # list_skills: recursive tree of skills/
        if url == f"{_gh_base()}/git/trees/tree-sha-skills-dir":
            return httpx.Response(
                200,
                json={
                    "truncated": False,
                    "tree": [
                        {"path": "coding/SKILL.md", "type": "blob", "sha": "blob-coding-skill-md"},
                        {"path": "git/SKILL.md", "type": "blob", "sha": "blob-git-skill-md"},
                    ],
                },
            )
        # fetch_skill/fetch_file: resolve individual skill tree SHAs from skills/ listing
        if url == f"{_gh_base()}/contents/skills":
            return httpx.Response(200, json=_skills_dir())
        if url == f"{_gh_base()}/git/trees/tree-sha-coding":
            return httpx.Response(200, json=_skill_tree())
        if url == f"{_gh_base()}/git/blobs/blob-skill-md":
            return httpx.Response(200, text="# Coding Skill\nThis is the coding skill.")
        if url == f"{_gh_base()}/git/blobs/blob-guide":
            return httpx.Response(200, text="# Guide\nThis is the guide.")
        if url == "https://example.com/SKILL.md":
            return httpx.Response(200, text="# HTTP Skill")
        return httpx.Response(404, text="Not found")


@pytest.fixture()
def config_file(tmp_path: Path) -> Path:
    data = {
        "registries": {
            "gh-skills": {
                "type": "github",
                "owner": "acme",
                "repo": "skills",
                "skills_dir": "skills",
                "ref": "main",
            },
            "my-http": {
                "type": "http",
                "url": "https://example.com/SKILL.md",
                "skill_name": "http-skill",
            },
        },
        "cache": {"enabled": False},
    }
    p = tmp_path / "skills-mcp.jsonc"
    p.write_text(json.dumps(data))
    return p


@pytest.fixture()
def mcp_app(config_file: Path, monkeypatch: pytest.MonkeyPatch):
    """Build the FastMCP app with a fake httpx transport active for the entire test."""
    original_cls = httpx.AsyncClient

    class PatchedClient(original_cls):  # type: ignore[misc]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["transport"] = IntegrationTransport()
            super().__init__(*args, **kwargs)

    # Keep the patch active for the whole test (monkeypatch auto-restores after the test)
    monkeypatch.setattr(httpx, "AsyncClient", PatchedClient)
    return build_app(config_file)


# ---------------------------------------------------------------------------
# Helper: call a tool and return (content_text, isError)
# ---------------------------------------------------------------------------


async def _call(app, tool: str, args: dict[str, Any]) -> tuple[str, bool]:
    async with create_connected_server_and_client_session(app, raise_exceptions=False) as session:
        result = await session.call_tool(tool, args)
    text = ""
    for part in result.content:
        if hasattr(part, "text"):
            text = str(part.text)  # type: ignore[union-attr]
            break
    return text, result.isError


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


async def test_list_registries_returns_both(mcp_app):
    text, is_error = await _call(mcp_app, "list_registries", {})
    assert not is_error
    data = json.loads(text)
    names = {r["name"] for r in data}
    assert names == {"gh-skills", "my-http"}


async def test_list_registries_empty(tmp_path: Path):
    p = tmp_path / "skills-mcp.jsonc"
    p.write_text(json.dumps({"registries": {}}))
    app = build_app(p)
    text, is_error = await _call(app, "list_registries", {})
    assert not is_error
    assert json.loads(text) == []


async def test_list_skills_github(mcp_app):
    text, is_error = await _call(mcp_app, "list_skills", {"registry": "gh-skills"})
    assert not is_error
    skills = json.loads(text)
    assert "coding" in skills
    assert "git" in skills


async def test_list_skills_http_single_entry(mcp_app):
    text, is_error = await _call(mcp_app, "list_skills", {"registry": "my-http"})
    assert not is_error
    assert json.loads(text) == ["http-skill"]


async def test_list_skills_unknown_registry_is_error(mcp_app):
    _text, is_error = await _call(mcp_app, "list_skills", {"registry": "nonexistent"})
    assert is_error


async def test_get_skill_github_content_and_files(mcp_app):
    text, is_error = await _call(mcp_app, "get_skill", {"registry": "gh-skills", "skill": "coding"})
    assert not is_error
    data = json.loads(text)
    assert "# Coding Skill" in data["content"]
    assert "references/guide.md" in data["files"]


async def test_get_skill_http_empty_files(mcp_app):
    text, is_error = await _call(
        mcp_app, "get_skill", {"registry": "my-http", "skill": "http-skill"}
    )
    assert not is_error
    data = json.loads(text)
    assert data["files"] == []
    assert "# HTTP Skill" in data["content"]


async def test_get_skill_missing_skill_is_error(mcp_app):
    _text, is_error = await _call(
        mcp_app, "get_skill", {"registry": "gh-skills", "skill": "nonexistent"}
    )
    assert is_error


async def test_get_skill_file_github_returns_content(mcp_app):
    text, is_error = await _call(
        mcp_app,
        "get_skill_file",
        {"registry": "gh-skills", "skill": "coding", "file_path": "references/guide.md"},
    )
    assert not is_error
    assert "# Guide" in text


async def test_get_skill_file_http_registry_is_error(mcp_app):
    _text, is_error = await _call(
        mcp_app,
        "get_skill_file",
        {"registry": "my-http", "skill": "http-skill", "file_path": "file.md"},
    )
    assert is_error


async def test_get_skill_file_path_traversal_is_error(mcp_app):
    _text, is_error = await _call(
        mcp_app,
        "get_skill_file",
        {"registry": "gh-skills", "skill": "coding", "file_path": "../../secret"},
    )
    assert is_error


async def test_get_skill_file_unknown_path_is_error(mcp_app):
    _text, is_error = await _call(
        mcp_app,
        "get_skill_file",
        {"registry": "gh-skills", "skill": "coding", "file_path": "unlisted.txt"},
    )
    assert is_error


async def test_network_error_returns_error_string(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    p = tmp_path / "skills-mcp.jsonc"
    p.write_text(
        json.dumps(
            {
                "registries": {
                    "broken": {
                        "type": "http",
                        "url": "https://unreachable.invalid/SKILL.md",
                        "skill_name": "s",
                    }
                },
                "cache": {"enabled": False},
            }
        )
    )

    class ErrorTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

    original_cls = httpx.AsyncClient

    class PatchedClient(original_cls):  # type: ignore[misc]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["transport"] = ErrorTransport()
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", PatchedClient)
    app = build_app(p)

    text, is_error = await _call(app, "get_skill", {"registry": "broken", "skill": "s"})
    # Network error → error string (not is_error crash)
    assert not is_error
    data = json.loads(text)
    assert "error" in data or "Error" in str(data)


# ---------------------------------------------------------------------------
# Spec scenario: Tool list is stable (exactly four tools)
# ---------------------------------------------------------------------------


async def test_tool_list_is_exactly_four(mcp_app):
    """The server MUST advertise exactly four tools: list_registries, list_skills,
    get_skill, get_skill_file — no more, no fewer."""
    expected = {"list_registries", "list_skills", "get_skill", "get_skill_file"}
    from mcp.shared.memory import create_connected_server_and_client_session

    async with create_connected_server_and_client_session(mcp_app) as session:
        tools = await session.list_tools()
    names = {t.name for t in tools.tools}
    assert names == expected, f"Expected {expected}, got {names}"


# ---------------------------------------------------------------------------
# Spec scenario: One registry failure does not affect another (BLOCKER fix)
# ---------------------------------------------------------------------------


async def test_one_registry_failure_does_not_affect_other(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A network failure on registry A must not prevent registry B from serving
    a successful result in the same session."""
    p = tmp_path / "skills-mcp.jsonc"
    p.write_text(
        json.dumps(
            {
                "registries": {
                    "broken": {
                        "type": "http",
                        "url": "https://broken.invalid/SKILL.md",
                        "skill_name": "broken-skill",
                    },
                    "working": {
                        "type": "http",
                        "url": "https://working.example.com/SKILL.md",
                        "skill_name": "working-skill",
                    },
                },
                "cache": {"enabled": False},
            }
        )
    )

    class PartialTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            url = str(request.url).split("?")[0]
            if "broken" in url:
                raise httpx.ConnectError("connection refused")
            if "working" in url:
                return httpx.Response(200, text="# Working Skill")
            return httpx.Response(404)

    original_cls = httpx.AsyncClient

    class PatchedClient(original_cls):  # type: ignore[misc]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["transport"] = PartialTransport()
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", PatchedClient)
    app = build_app(p)

    # Broken registry → error string result (not is_error crash)
    broken_text, broken_is_error = await _call(
        app, "get_skill", {"registry": "broken", "skill": "broken-skill"}
    )
    assert not broken_is_error, "infra error should not be is_error"
    assert "Error" in broken_text or "error" in json.loads(broken_text).get("error", "Error")

    # Working registry → success, even after the broken one failed
    working_text, working_is_error = await _call(
        app, "get_skill", {"registry": "working", "skill": "working-skill"}
    )
    assert not working_is_error
    working_data = json.loads(working_text)
    assert "# Working Skill" in working_data["content"]
