"""Integration tests using in-memory MCP transport (create_connected_server_and_client_session)."""

# spec: openspec/changes/skill-access-consolidation/specs/skills-mcp/spec.md

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from pydantic import AnyUrl

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
def config_file_with_description(tmp_path: Path) -> Path:
    data = {
        "registries": {
            "gh-skills": {
                "type": "github",
                "owner": "acme",
                "repo": "skills",
                "skills_dir": "skills",
                "ref": "main",
                "description": "Clark engineering skills",
            },
            "my-http": {
                "type": "http",
                "url": "https://example.com/SKILL.md",
                "skill_name": "http-skill",
                # no description
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


@pytest.fixture()
def mcp_app_with_description(config_file_with_description: Path, monkeypatch: pytest.MonkeyPatch):
    """Build the FastMCP app configured with registry descriptions."""
    original_cls = httpx.AsyncClient

    class PatchedClient(original_cls):  # type: ignore[misc]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["transport"] = IntegrationTransport()
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", PatchedClient)
    return build_app(config_file_with_description)


# ---------------------------------------------------------------------------
# Helpers
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


async def _read_resource(app, uri: str) -> tuple[str, bool]:
    """Call read_resource and return (text, is_error)."""
    async with create_connected_server_and_client_session(app, raise_exceptions=False) as session:
        try:
            result = await session.read_resource(AnyUrl(uri))
            text = ""
            for part in result.contents:
                if hasattr(part, "text"):
                    text = str(part.text)  # type: ignore[union-attr]
                    break
            return text, False
        except Exception:
            return "", True


# ---------------------------------------------------------------------------
# Scenario: Tool list is stable (exactly three tools)
# ---------------------------------------------------------------------------


async def test_tool_list_is_exactly_three(mcp_app):
    """The server MUST advertise exactly three tools: list_registries, list_skills, get_skill."""
    expected = {"list_registries", "list_skills", "get_skill"}
    async with create_connected_server_and_client_session(mcp_app) as session:
        tools = await session.list_tools()
    names = {t.name for t in tools.tools}
    assert names == expected, f"Expected {expected}, got {names}"


# ---------------------------------------------------------------------------
# Scenario: Resource template is advertised
# ---------------------------------------------------------------------------


async def test_resource_template_is_advertised(mcp_app):
    """list_resource_templates MUST return exactly one template matching skill://{registry}/{+skill}{?file}."""
    async with create_connected_server_and_client_session(mcp_app) as session:
        result = await session.list_resource_templates()
    uris = [t.uriTemplate for t in result.resourceTemplates]
    assert len(uris) == 1
    assert uris[0] == "skill://{registry}/{+skill}{?file}"


# ---------------------------------------------------------------------------
# list_registries tests
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


async def test_list_registries_returns_description(mcp_app_with_description):
    """Scenario: Returns description when configured."""
    text, is_error = await _call(mcp_app_with_description, "list_registries", {})
    assert not is_error
    data = json.loads(text)
    gh = next(r for r in data if r["name"] == "gh-skills")
    assert gh.get("description") == "Clark engineering skills"


async def test_list_registries_omits_description_when_absent(mcp_app_with_description):
    """Scenario: Description absent when not configured."""
    text, is_error = await _call(mcp_app_with_description, "list_registries", {})
    assert not is_error
    data = json.loads(text)
    http = next(r for r in data if r["name"] == "my-http")
    assert "description" not in http


# ---------------------------------------------------------------------------
# list_skills tests
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# get_skill tests — without file (existing behaviour)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# get_skill tests — with file param (replaces get_skill_file)
# ---------------------------------------------------------------------------


async def test_get_skill_with_file_returns_raw_text(mcp_app):
    """Scenario: Returns companion file raw text when file is provided."""
    text, is_error = await _call(
        mcp_app,
        "get_skill",
        {"registry": "gh-skills", "skill": "coding", "file": "references/guide.md"},
    )
    assert not is_error
    assert "# Guide" in text
    # Must be raw text, not JSON-wrapped
    assert not text.strip().startswith("{")


async def test_get_skill_with_file_url_decodes_percent_encoded_slash(mcp_app):
    """Scenario: Percent-encoded slashes in file query param are decoded."""
    text, is_error = await _call(
        mcp_app,
        "get_skill",
        {"registry": "gh-skills", "skill": "coding", "file": "references%2Fguide.md"},
    )
    assert not is_error
    assert "# Guide" in text


async def test_get_skill_with_file_http_registry_is_error(mcp_app):
    """Scenario: HTTP registry with file raises error."""
    _text, is_error = await _call(
        mcp_app,
        "get_skill",
        {"registry": "my-http", "skill": "http-skill", "file": "file.md"},
    )
    assert is_error


async def test_get_skill_with_file_traversal_is_error(mcp_app):
    """Scenario: Path traversal in file is rejected."""
    _text, is_error = await _call(
        mcp_app,
        "get_skill",
        {"registry": "gh-skills", "skill": "coding", "file": "../../secret"},
    )
    assert is_error


async def test_get_skill_with_file_unknown_path_is_error(mcp_app):
    """File path not in the skill's file tree returns is_error=True."""
    _text, is_error = await _call(
        mcp_app,
        "get_skill",
        {"registry": "gh-skills", "skill": "coding", "file": "unlisted.txt"},
    )
    assert is_error


# ---------------------------------------------------------------------------
# Resource template tests
# ---------------------------------------------------------------------------


async def test_read_resource_skill_md(mcp_app):
    """Scenario: Reads SKILL.md via URI."""
    text, is_error = await _read_resource(mcp_app, "skill://gh-skills/coding")
    assert not is_error
    assert "# Coding Skill" in text
    # Must be raw text, not JSON envelope
    assert not text.strip().startswith("{")


async def test_read_resource_companion_file(mcp_app):
    """Scenario: Reads companion file via URI with file query param."""
    text, is_error = await _read_resource(
        mcp_app, "skill://gh-skills/coding?file=references%2Fguide.md"
    )
    assert not is_error
    assert "# Guide" in text


async def test_read_resource_unknown_registry_error_content(mcp_app):
    """Scenario: Unknown registry produces error content item (not crash)."""
    _text, is_error = await _read_resource(mcp_app, "skill://nonexistent/some-skill")
    assert is_error


# ---------------------------------------------------------------------------
# Scenario: Network error returns error string
# ---------------------------------------------------------------------------


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
# Scenario: One registry failure does not affect another
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
