"""Tests for HTTP and GitHub registry adapters using fake httpx transports."""

# spec: openspec/specs/skills-mcp/spec.md

import json
from dataclasses import replace
from typing import Any

import anyio
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


# spec: openspec/specs/skills-mcp/spec.md
class RepoStream(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False
        self.consumed = 0
        self.delay = False
        self.close_delay = 0
        self.close_failure = None
        self.close_attempted = False
        self.read_started = None
        self.close_started = None
        self.close_release = None

    async def __aiter__(self):
        for chunk in self.chunks:
            self.consumed += 1
            if self.delay:
                if self.read_started is not None:
                    self.read_started.set()
                await anyio.sleep(1)
            yield chunk

    async def aclose(self):
        self.close_attempted = True
        if self.close_started is not None:
            self.close_started.set()
            await self.close_release.wait()
        await anyio.sleep(self.close_delay)
        if self.close_failure is not None:
            raise self.close_failure
        self.closed = True


class RepoTransport(httpx.AsyncBaseTransport):
    """Git Trees/Commits payloads from the official GitHub REST examples."""

    commit = "1" * 40
    root = "2" * 40
    directory = "3" * 40
    blob = "4" * 40

    def __init__(self, content=b"hello\n", mode="100644"):
        self.calls = []
        self.stream = RepoStream([content])
        self.failure = None
        self.delay = False
        self.rate_limit = False
        self.retry_sent = False
        self.retry_after = "0"
        self.retry_status = 429
        self.exhaust_retries = False
        self.opened = []
        self.close_failure = None
        self.retry_stream = RepoStream([b"private upstream diagnostic"])
        self.commit_response = None
        self.content_encoding = None
        self.trees = {
            self.root: {
                "truncated": False,
                "tree": [
                    {"path": "tools", "mode": "040000", "type": "tree", "sha": self.directory},
                    {
                        "path": "README.md",
                        "mode": mode,
                        "type": "blob",
                        "sha": self.blob,
                        "size": len(content),
                    },
                    {"path": "sub", "mode": "160000", "type": "commit", "sha": self.blob},
                    {"path": "link", "mode": "120000", "type": "blob", "sha": self.blob},
                ],
            },
            self.directory: {
                "truncated": False,
                "tree": [
                    {"path": "%2e%2e", "mode": "100755", "type": "blob", "sha": self.blob},
                ],
            },
        }

    async def handle_async_request(self, request):
        self.calls.append(str(request.url))
        if self.delay:
            await anyio.sleep(1)
        if self.failure is not None:
            if isinstance(self.failure, Exception):
                raise self.failure
            stream = RepoStream([b"secret diagnostic"])
            self.opened.append(stream)
            return httpx.Response(
                self.failure,
                stream=stream,
                headers={"Location": "https://elsewhere.invalid/secret"},
            )
        if self.retry_sent:
            assert self.retry_stream.closed
        if self.rate_limit or (self.retry_sent and self.exhaust_retries):
            if self.retry_sent:
                self.retry_stream = RepoStream([b"private upstream diagnostic"])
            self.rate_limit = False
            self.retry_sent = True
            self.opened.append(self.retry_stream)
            return httpx.Response(
                self.retry_status,
                stream=self.retry_stream,
                headers={"Retry-After": self.retry_after},
            )
        path = request.url.path
        if "/commits/" in path:
            if self.commit_response is not None:
                return self.json_response(self.commit_response)
            resolved = (
                self.commit if sum("/commits/" in url for url in self.calls) == 1 else "5" * 40
            )
            return self.json_response({"sha": resolved, "commit": {"tree": {"sha": self.root}}})
        if "/git/trees/" in path:
            return self.json_response(self.trees[path.rsplit("/", 1)[1]])
        if "/git/blobs/" in path:
            self.opened.append(self.stream)
            return httpx.Response(200, stream=self.stream)
        raise AssertionError(f"Unexpected request: {request.url}")

    def json_response(self, payload):
        stream = RepoStream(
            [payload if isinstance(payload, bytes) else json.dumps(payload).encode()]
        )
        stream.close_failure = self.close_failure
        self.opened.append(stream)
        headers = {"Content-Encoding": self.content_encoding} if self.content_encoding else {}
        return httpx.Response(200, stream=stream, headers=headers)


# spec: openspec/specs/skills-mcp/spec.md
class TestRepositoryAccess:
    async def test_lists_repository_directories_with_provenance(self, gh_config):
        transport = RepoTransport()
        async with httpx.AsyncClient(transport=transport) as client:
            adapter = GithubAdapter(gh_config, client, AuthResolver())
            result = await adapter.list_repo_entries()
            assert result.get("commit_sha") == transport.commit
            assert result["path"] == ""
            assert result["source"] == await adapter.get_registry_source()
            assert [(e["path"], e["type"]) for e in result["entries"]] == [
                ("README.md", "file"),
                ("link", "symlink"),
                ("sub", "submodule"),
                ("tools", "directory"),
            ]
            nested = await adapter.list_repo_entries("tools")
            assert nested["entries"] == [{"path": "tools/%2e%2e", "type": "file"}]

    @pytest.mark.parametrize(
        "method,path",
        [
            ("list_repo_entries", "absent"),
            ("list_repo_entries", "README.md"),
            ("read_repo_text_file", "tools"),
            ("read_repo_text_file", "absent"),
            ("read_repo_text_file", "README.md/child"),
        ],
    )
    async def test_rejects_missing_or_wrong_kind_repository_targets(self, gh_config, method, path):
        async with httpx.AsyncClient(transport=RepoTransport()) as client:
            with pytest.raises(ValueError, match=r"not found|directory|file"):
                await getattr(GithubAdapter(gh_config, client, AuthResolver()), method)(path)

    @pytest.mark.parametrize("ref,encoded", [("main", "main"), ("feat/x", "feat%2Fx")])
    async def test_keeps_moving_ref_operations_on_one_snapshot(self, gh_config, ref, encoded):
        transport = RepoTransport()
        async with httpx.AsyncClient(transport=transport) as client:
            result = await GithubAdapter(
                replace(gh_config, ref=ref), client, AuthResolver()
            ).read_repo_text_file("tools/%2e%2e")
        assert result.get("commit_sha") == transport.commit
        assert sum("/commits/" in url for url in transport.calls) == 1
        assert [url.rsplit("/", 1)[1] for url in transport.calls] == [
            encoded,
            transport.root,
            transport.directory,
            transport.blob,
        ]

    @pytest.mark.parametrize(
        "method,path",
        [
            (method, path)
            for method in ("list_repo_entries", "read_repo_text_file")
            for path in [
                "",
                "/etc/passwd",
                "../a",
                "a/../b",
                "./a",
                "a//b",
                "a/",
                "a\\b",
                "a\x00b",
                "a\x85b",
                "/".join(["a"] * 33),
            ]
            if path or method == "read_repo_text_file"
        ],
    )
    async def test_rejects_unsafe_repository_paths_before_io(self, gh_config, path, method):
        transport = RepoTransport()
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(ValueError):
                await getattr(GithubAdapter(gh_config, client, AuthResolver()), method)(path)
        assert transport.calls == []

    @pytest.mark.parametrize("path", ["link", "sub", "link/child", "sub/child"])
    @pytest.mark.parametrize("method", ["list_repo_entries", "read_repo_text_file"])
    async def test_rejects_symlink_and_submodule_targets(self, gh_config, path, method):
        transport = RepoTransport()
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(UnsupportedOperationError, match=r"symlink|submodule"):
                await getattr(GithubAdapter(gh_config, client, AuthResolver()), method)(path)
        assert not any("/git/blobs/" in url for url in transport.calls)

    @pytest.mark.parametrize(
        "content,mode",
        [(b"", "100644"), ("héllo".encode(), "100755"), (b"a" * 1048576, "100644")],
        ids=["empty", "executable", "exact-limit"],
    )
    async def test_reads_repository_text_with_provenance(self, gh_config, content, mode):
        transport = RepoTransport(content, mode)
        async with httpx.AsyncClient(transport=transport) as client:
            result = await GithubAdapter(gh_config, client, AuthResolver()).read_repo_text_file(
                "README.md"
            )
        assert result.get("content") == content.decode()
        assert result["path"] == "README.md"
        assert result["commit_sha"] == transport.commit
        assert result["source"]["repo"] == "skills"
        assert transport.stream.closed

    @pytest.mark.parametrize("content", [b"\xff", b"a\x00b"])
    async def test_rejects_non_text_repository_files(self, gh_config, content):
        transport = RepoTransport(content)
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(ValueError, match=r"UTF-8|NUL"):
                await GithubAdapter(gh_config, client, AuthResolver()).read_repo_text_file(
                    "README.md"
                )
        assert transport.stream.closed

    async def test_rejects_advertised_oversized_files_before_download(self, gh_config):
        transport = RepoTransport(b"a" * 1048577)
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(ValueError, match="1 MiB"):
                await GithubAdapter(gh_config, client, AuthResolver()).read_repo_text_file(
                    "README.md"
                )
        assert not any("/git/blobs/" in url for url in transport.calls)

    @pytest.mark.parametrize("close_failure", [False, True])
    async def test_stops_oversized_downloads_and_closes_streams(self, gh_config, close_failure):
        transport = RepoTransport()
        transport.stream = RepoStream([b"a" * 1048576, b"b", b"never read"])
        if close_failure:
            transport.stream.close_failure = RuntimeError("secret diagnostic")
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(ValueError, match="1 MiB"):
                await GithubAdapter(gh_config, client, AuthResolver()).read_repo_text_file(
                    "README.md"
                )
        assert transport.stream.closed or (close_failure and transport.stream.close_attempted)
        assert transport.stream.consumed == 2

    @pytest.mark.parametrize(
        "bad",
        [
            {"truncated": True, "tree": []},
            {"tree": []},
            {"truncated": False, "tree": [{}]},
            {"truncated": False, "tree": ["not an entry"]},
            ("commit", b"not json"),
            ("commit", b"[]"),
            ("commit", {"sha": "x"}),
            ("commit", {"sha": "1" * 40, "commit": {}}),
            ("commit", {"sha": "1" * 40, "commit": []}),
            ("commit", {"sha": "1" * 40, "commit": {"tree": {}}}),
            {
                "truncated": False,
                "tree": [{"path": "x", "mode": "999999", "type": "blob", "sha": "4" * 40}],
            },
            "REPO_METADATA_MAX_BYTES",
            "REPO_TREE_MAX_ENTRIES",
            "REPO_LISTING_MAX_BYTES",
            {
                "truncated": False,
                "tree": [
                    {"path": "unsafe\\name", "mode": "100644", "type": "blob", "sha": "4" * 40}
                ],
            },
            {
                "truncated": False,
                "tree": [
                    {"path": "control\x85name", "mode": "100644", "type": "blob", "sha": "4" * 40}
                ],
            },
        ],
    )
    async def test_rejects_incomplete_or_malformed_repository_metadata(
        self, gh_config, bad, monkeypatch
    ):
        transport = RepoTransport()
        if isinstance(bad, str):
            monkeypatch.setattr(f"skills_mcp.registries.github.{bad}", 1)
        elif isinstance(bad, tuple):
            transport.commit_response = bad[1]
        else:
            transport.trees[transport.root] = bad
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(RegistryUnavailableError, match=r"metadata|incomplete|budget"):
                await GithubAdapter(gh_config, client, AuthResolver()).list_repo_entries()

    async def test_stops_operations_exceeding_cumulative_metadata_budget(
        self, gh_config, monkeypatch
    ):
        monkeypatch.setattr(
            "skills_mcp.registries.github.REPO_METADATA_TOTAL_BYTES", 100, raising=False
        )
        transport = RepoTransport()
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(RegistryUnavailableError, match="budget"):
                await GithubAdapter(gh_config, client, AuthResolver()).list_repo_entries("tools")
        assert transport.opened and all(stream.closed for stream in transport.opened)

    @pytest.mark.parametrize("stage", ["request", "stream", "close"])
    async def test_stops_repository_operations_at_deadline(self, gh_config, monkeypatch, stage):
        monkeypatch.setattr(
            "skills_mcp.registries.github.REPO_OPERATION_SECONDS", 0.1, raising=False
        )
        transport = RepoTransport()
        transport.delay = stage == "request"
        transport.stream.delay = stage == "stream"
        transport.stream.close_delay = 1 if stage == "close" else 0
        started = anyio.current_time()
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(RegistryUnavailableError, match="deadline"):
                await GithubAdapter(gh_config, client, AuthResolver()).read_repo_text_file(
                    "README.md"
                )
        assert anyio.current_time() - started < 0.3
        if stage == "stream":
            assert transport.stream.closed

    @pytest.mark.parametrize(
        "status,retry_after,expected",
        [(403, "0", 0), (429, "0", 0), (429, "900", 5), (429, "bad", 0), (429, "nan", 0)],
    )
    async def test_retries_repository_rate_limits_after_closing_response(
        self, gh_config, monkeypatch, status, retry_after, expected
    ):
        transport = RepoTransport()
        transport.rate_limit = True
        transport.retry_status = status
        transport.retry_after = retry_after
        delays = []

        async def sleep(seconds):
            if transport.retry_stream.closed and len(transport.calls) == 1:
                delays.append(seconds)

        monkeypatch.setattr("skills_mcp.registries.github.anyio.sleep", sleep)
        async with httpx.AsyncClient(transport=transport) as client:
            result = await GithubAdapter(gh_config, client, AuthResolver()).list_repo_entries()
        assert result.get("commit_sha") == "5" * 40
        assert transport.retry_stream.closed
        assert sum("/commits/" in url for url in transport.calls) == 2
        assert delays == [expected]
        assert all(stream.closed for stream in transport.opened)

    @pytest.mark.parametrize(
        "failure",
        [
            301,
            404,
            401,
            403,
            429,
            500,
            "retry-exhausted",
            "close-error",
            "auth-unavailable",
            "content-encoding",
            httpx.ConnectError("secret diagnostic"),
        ],
    )
    async def test_reports_sanitized_repository_infrastructure_errors(
        self, gh_config, failure, monkeypatch
    ):
        transport = RepoTransport()
        auth = AuthResolver()
        if failure == "close-error":
            transport.close_failure = RuntimeError("secret diagnostic")
        elif failure == "auth-unavailable":

            async def missing_auth(_config):
                raise RegistryUnavailableError(
                    "env SENSITIVE_CREDENTIAL_NAME missing; secret diagnostic"
                )

            monkeypatch.setattr(auth, "headers_for", missing_auth)
        elif failure == "content-encoding":
            transport.content_encoding = "gzip"
        elif failure == "retry-exhausted":
            transport.rate_limit = True
            transport.exhaust_retries = True
        else:
            transport.failure = failure
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(RegistryUnavailableError) as caught:
                await GithubAdapter(gh_config, client, auth).list_repo_entries()
        assert "secret" not in str(caught.value)
        assert "SENSITIVE_CREDENTIAL_NAME" not in str(caught.value)
        assert "https://" not in str(caught.value)
        assert all(
            stream.closed or (failure == "close-error" and stream.close_attempted)
            for stream in transport.opened
        )

    @pytest.mark.parametrize(
        "stage,outcome",
        [
            ("body", "success"),
            ("body", "stalled"),
            ("cleanup", "success"),
            ("cleanup", "stalled"),
            ("cleanup", "failure"),
        ],
    )
    async def test_preserves_caller_cancellation_after_bounded_cleanup(
        self, gh_config, monkeypatch, stage, outcome
    ):
        monkeypatch.setattr("skills_mcp.registries.github.REPO_OPERATION_SECONDS", 0.1)
        transport = RepoTransport()
        entered = anyio.Event()
        release = anyio.Event()
        transport.stream.delay = stage == "body"
        if stage == "body":
            transport.stream.read_started = entered
        else:
            transport.stream.close_started = entered
            transport.stream.close_release = release
        transport.stream.close_delay = 1 if outcome == "stalled" else 0
        if outcome == "failure":
            transport.stream.close_failure = RuntimeError("secret diagnostic")
        results = []

        async def read():
            async with httpx.AsyncClient(transport=transport) as client:
                try:
                    await GithubAdapter(gh_config, client, AuthResolver()).read_repo_text_file(
                        "README.md"
                    )
                except anyio.get_cancelled_exc_class():
                    results.append("cancelled")
                    raise
                except RegistryUnavailableError:
                    results.append("infrastructure error")
                else:
                    results.append("success")

        started = anyio.current_time()
        with anyio.fail_after(0.5):
            async with anyio.create_task_group() as tasks:
                tasks.start_soon(read)
                await entered.wait()
                tasks.cancel_scope.cancel()
                release.set()
        assert results == ["cancelled"]
        assert anyio.current_time() - started < 0.5
        assert transport.stream.closed is (outcome == "success")


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
