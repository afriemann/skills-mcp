"""Tests for AuthResolver: headers, missing env vars, gh_cli caching."""

import base64
from unittest.mock import MagicMock, patch

import pytest

from skills_mcp.auth import AuthResolver
from skills_mcp.config.model import BasicAuth, BearerAuth, GhCliAuth, GithubTokenAuth, NoAuth
from skills_mcp.errors import RegistryUnavailableError


@pytest.fixture()
def resolver():
    return AuthResolver()


async def test_no_auth_returns_empty(resolver: AuthResolver):
    headers = await resolver.headers_for(NoAuth())
    assert headers == {}


async def test_github_token_auth_bearer_header(resolver: AuthResolver, monkeypatch):
    monkeypatch.setenv("MY_GH_TOKEN", "secret-pat")
    headers = await resolver.headers_for(GithubTokenAuth(env_var="MY_GH_TOKEN"))
    assert headers == {"Authorization": "Bearer secret-pat"}


async def test_bearer_auth_bearer_header(resolver: AuthResolver, monkeypatch):
    monkeypatch.setenv("MY_BEARER_TOKEN", "my-secret")
    headers = await resolver.headers_for(BearerAuth(env_var="MY_BEARER_TOKEN"))
    assert headers == {"Authorization": "Bearer my-secret"}


async def test_basic_auth_base64_header(resolver: AuthResolver, monkeypatch):
    monkeypatch.setenv("MY_USER", "alice")
    monkeypatch.setenv("MY_PASS", "p4ssw0rd")
    headers = await resolver.headers_for(
        BasicAuth(username_env_var="MY_USER", password_env_var="MY_PASS")
    )
    expected_b64 = base64.b64encode(b"alice:p4ssw0rd").decode()
    assert headers == {"Authorization": f"Basic {expected_b64}"}


async def test_missing_env_var_raises(resolver: AuthResolver, monkeypatch):
    monkeypatch.delenv("MISSING_VAR", raising=False)
    with pytest.raises(RegistryUnavailableError, match="MISSING_VAR"):
        await resolver.headers_for(GithubTokenAuth(env_var="MISSING_VAR"))


async def test_gh_cli_token_fetched_once(resolver: AuthResolver):
    """gh auth token should be called once even with two concurrent requests."""
    call_count = 0

    async def _fake_run_process(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        # Simulate a small delay to let concurrency race
        result = MagicMock()
        result.stdout = b"gh-token-abc\n"
        return result

    with patch("anyio.run_process", side_effect=_fake_run_process):
        h1 = await resolver.headers_for(GhCliAuth())
        h2 = await resolver.headers_for(GhCliAuth())

    assert h1 == {"Authorization": "Bearer gh-token-abc"}
    assert h2 == {"Authorization": "Bearer gh-token-abc"}
    assert call_count == 1, "gh auth token must be invoked exactly once"


async def test_gh_cli_absent_falls_back_to_no_auth(resolver: AuthResolver):
    """When gh is not on PATH, fall back to empty headers."""
    with patch("anyio.run_process", side_effect=FileNotFoundError("gh not found")):
        headers = await resolver.headers_for(GhCliAuth())
    assert headers == {}
