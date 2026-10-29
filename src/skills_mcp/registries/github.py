"""GitHub registry adapter — two-phase fetch via Contents + Trees + Blobs APIs."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import quote

import anyio
import httpx
from anyio.lowlevel import checkpoint_if_cancelled

from ..auth import AuthResolver
from ..config.model import (
    REPO_CLEANUP_MAX_SECONDS,
    REPO_CLEANUP_RESERVE_FRACTION,
    REPO_LISTING_MAX_BYTES,
    REPO_METADATA_MAX_BYTES,
    REPO_METADATA_TOTAL_BYTES,
    REPO_OPERATION_SECONDS,
    REPO_PATH_MAX_COMPONENTS,
    REPO_TEXT_MAX_BYTES,
    REPO_TREE_MAX_ENTRIES,
    GithubRegistry,
)
from ..errors import (
    PathTraversalError,
    RegistryUnavailableError,
    RepositoryTargetError,
    SkillFileNotFoundError,
    SkillNotFoundError,
    UnsupportedOperationError,
)
from . import SkillContent

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_RAW_ACCEPT = "application/vnd.github.raw"
_JSON_ACCEPT = "application/vnd.github+json"

# Maximum Retry-After we will honour (seconds).
_MAX_RETRY_AFTER = 5.0

_REPO_MODES = {
    "100644": ("blob", "file"),
    "100755": ("blob", "file"),
    "040000": ("tree", "directory"),
    "120000": ("blob", "symlink"),
    "160000": ("commit", "submodule"),
}


@dataclass(frozen=True)
class _RepoEntry:
    path: str
    kind: str
    sha: str
    size: int | None


@dataclass
class _RepoBudget:
    deadline: float
    cleanup_seconds: float
    metadata_bytes: int = 0


def _repo_retry_delay(headers: httpx.Headers) -> float:
    try:
        parsed = float(headers["Retry-After"])
    except ValueError:
        return 0
    return min(max(parsed, 0), _MAX_RETRY_AFTER) if math.isfinite(parsed) else 0


def _repo_parts(path: str, *, root: bool = False) -> list[str]:
    if path == "" and root:
        return []
    parts = path.split("/")
    if (
        len(parts) > REPO_PATH_MAX_COMPONENTS
        or "\\" in path
        or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in path)
        or any(part in ("", ".", "..") for part in parts)
    ):
        raise PathTraversalError(
            "Use a literal repository-relative POSIX path without dot, empty, control, or backslash components"
        )
    return parts


def _repo_sha(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[a-fA-F0-9]{40}", value) is None:
        raise RegistryUnavailableError("GitHub repository metadata contains an invalid object SHA")
    return value


class _NotFoundError(Exception):
    """Internal signal: GitHub returned 404."""


class _ParentNotFoundError(_NotFoundError):
    """The parent directory itself returned 404."""


class _EntryAbsentError(_NotFoundError):
    """The parent directory was found but the named entry is not in it."""


class GithubAdapter:
    """Fetches skills from a GitHub repository using the REST API.

    list_skills:   resolves skills_dir tree SHA via Contents-on-parent
                   -> recursive Git Trees walk -> filter /SKILL.md blobs.
    fetch_skill:   resolves skill dir tree SHA via Contents-on-parent
                   -> recursive Git Trees API -> SKILL.md blob SHA -> Blobs raw.
    fetch_file:    same as fetch_skill but returns a companion file blob.
    """

    type = "github"

    def __init__(
        self,
        config: GithubRegistry,
        http_client: httpx.AsyncClient,
        auth_resolver: AuthResolver,
    ) -> None:
        self._config = config
        self._client = http_client
        self._auth = auth_resolver
        self.name = config.name
        self.ref: str | None = config.ref

    async def get_registry_source(self) -> dict[str, object]:
        cfg = self._config
        return {
            "registry": self.name,
            "type": self.type,
            "url": f"https://github.com/{cfg.owner}/{cfg.repo}",
            "owner": cfg.owner,
            "repo": cfg.repo,
            "ref": cfg.ref,
            "skills_dir": cfg.skills_dir,
        }

    async def list_repo_entries(self, path: str = "") -> dict[str, object]:
        return await self._repo_operation(path, read_file=False)

    async def read_repo_text_file(self, path: str) -> dict[str, object]:
        return await self._repo_operation(path, read_file=True)

    async def _repo_operation(self, path: str, *, read_file: bool) -> dict[str, object]:
        parts = _repo_parts(path, root=not read_file)
        reserve = min(
            REPO_CLEANUP_MAX_SECONDS, REPO_OPERATION_SECONDS * REPO_CLEANUP_RESERVE_FRACTION
        )
        budget = _RepoBudget(anyio.current_time() + REPO_OPERATION_SECONDS, reserve)
        try:
            with anyio.fail_after(REPO_OPERATION_SECONDS - reserve):
                commit = await self._repo_json(
                    f"commits/{quote(self._config.ref, safe='')}", budget
                )
                try:
                    commit_sha = _repo_sha(commit["sha"])
                    commit_body = commit["commit"]
                    if not isinstance(commit_body, dict) or not isinstance(
                        commit_body.get("tree"), dict
                    ):
                        raise TypeError
                    tree_sha = _repo_sha(commit_body["tree"]["sha"])
                except (KeyError, TypeError):
                    raise RegistryUnavailableError(
                        "GitHub repository commit metadata is malformed"
                    ) from None
                target, tree_sha = await self._repo_target(
                    parts, tree_sha, budget, read_file=read_file
                )
                result: dict[str, object] = {
                    "source": await self.get_registry_source(),
                    "path": path,
                    "commit_sha": commit_sha,
                }
                if read_file:
                    result["content"] = await self._repo_text(target, budget)
                else:
                    listed: list[dict[str, object]] = []
                    for entry in sorted(
                        await self._repo_tree(tree_sha, budget), key=lambda e: e.path
                    ):
                        item: dict[str, object] = {
                            "path": f"{path}/{entry.path}" if path else entry.path,
                            "type": entry.kind,
                        }
                        if entry.size is not None:
                            item["size"] = entry.size
                        listed.append(item)
                    result["entries"] = listed
                    if len(json.dumps(result).encode("utf-8")) > REPO_LISTING_MAX_BYTES:
                        raise RegistryUnavailableError(
                            "Repository listing output budget exceeded; no partial listing returned"
                        )
                return result
        except TimeoutError:
            raise RegistryUnavailableError(
                "GitHub repository operation deadline exceeded"
            ) from None

    async def _repo_target(
        self, parts: list[str], tree_sha: str, budget: _RepoBudget, *, read_file: bool
    ) -> tuple[_RepoEntry | None, str]:
        target: _RepoEntry | None = None
        for index, part in enumerate(parts):
            entries = await self._repo_tree(tree_sha, budget)
            target = next((entry for entry in entries if entry.path == part), None)
            if target is None:
                raise RepositoryTargetError(
                    "Repository target not found; list its parent directory"
                )
            if target.kind in ("symlink", "submodule"):
                raise UnsupportedOperationError(
                    f"Repository {target.kind} targets cannot be followed"
                )
            if index < len(parts) - 1 or not read_file:
                if target.kind != "directory":
                    raise RepositoryTargetError("Repository target is not a directory")
                tree_sha = target.sha
        return target, tree_sha

    async def _repo_text(self, target: _RepoEntry | None, budget: _RepoBudget) -> str:
        if target is None or target.kind != "file":
            raise RepositoryTargetError("Repository target is not a regular file")
        if target.size is not None and target.size > REPO_TEXT_MAX_BYTES:
            raise RepositoryTargetError("Repository text file exceeds 1 MiB")
        raw = await self._repo_request(f"git/blobs/{target.sha}", budget, file=True)
        try:
            content = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise RepositoryTargetError("Repository file is not strict UTF-8 text") from None
        if "\x00" in content:
            raise RepositoryTargetError("Repository file contains NUL bytes, not text")
        return content

    async def _repo_tree(self, sha: str, budget: _RepoBudget) -> list[_RepoEntry]:
        data = await self._repo_json(f"git/trees/{sha}", budget)
        raw_entries = data.get("tree")
        if (
            data.get("truncated") is not False
            or not isinstance(raw_entries, list)
            or len(raw_entries) > REPO_TREE_MAX_ENTRIES
        ):
            raise RegistryUnavailableError(
                "GitHub repository tree metadata is incomplete or exceeds entry budget"
            )
        entries: list[_RepoEntry] = []
        seen: set[str] = set()
        for raw in raw_entries:
            if not isinstance(raw, dict):
                raise RegistryUnavailableError("GitHub repository entry metadata is malformed")
            name, mode, kind = raw.get("path"), raw.get("mode"), raw.get("type")
            size = raw.get("size")
            if (
                not isinstance(name, str)
                or not isinstance(mode, str)
                or mode not in _REPO_MODES
                or kind != _REPO_MODES[mode][0]
                or name in seen
                or (size is not None and (type(size) is not int or size < 0))
            ):
                raise RegistryUnavailableError("GitHub repository entry metadata is malformed")
            try:
                if len(_repo_parts(name)) != 1:
                    raise PathTraversalError("Expected one component")
            except PathTraversalError:
                raise RegistryUnavailableError(
                    "GitHub repository path metadata is malformed"
                ) from None
            seen.add(name)
            entries.append(_RepoEntry(name, _REPO_MODES[mode][1], _repo_sha(raw.get("sha")), size))
        return entries

    async def _repo_json(self, suffix: str, budget: _RepoBudget) -> dict[str, object]:
        raw = await self._repo_request(suffix, budget)
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise RegistryUnavailableError("GitHub repository metadata is malformed JSON") from None
        if not isinstance(data, dict):
            raise RegistryUnavailableError("GitHub repository metadata is not an object")
        return data

    async def _repo_request(self, suffix: str, budget: _RepoBudget, *, file: bool = False) -> bytes:
        cfg = self._config
        base = f"{_GITHUB_API}/repos/{quote(cfg.owner, safe='')}/{quote(cfg.repo, safe='')}"
        try:
            headers = await self._auth.headers_for(cfg.auth)
        except RegistryUnavailableError:
            raise RegistryUnavailableError(
                "GitHub repository authentication unavailable; check configured credentials"
            ) from None
        headers = {
            **headers,
            "Accept": "application/vnd.github.raw+json" if file else _JSON_ACCEPT,
            "Accept-Encoding": "identity",
        }
        retry_allowed = True
        while True:
            delay: float | None = None
            try:
                async with self._repo_stream(f"{base}/{suffix}", headers, budget) as response:
                    status = response.status_code
                    if status in (403, 429) and retry_allowed and "Retry-After" in response.headers:
                        retry_allowed = False
                        delay = _repo_retry_delay(response.headers)
                    elif status != 200:
                        raise RegistryUnavailableError(
                            f"GitHub repository request failed (HTTP {status}); check configured source, ref and access"
                        )
                    if delay is None:
                        return await self._repo_read_bounded(response, budget, file=file)
            except httpx.HTTPError:
                raise RegistryUnavailableError(
                    "GitHub repository request failed; check connectivity and configured access"
                ) from None
            if delay is not None:
                await anyio.sleep(delay)

    async def _repo_read_bounded(
        self, response: httpx.Response, budget: _RepoBudget, *, file: bool
    ) -> bytes:
        if response.headers.get("Content-Encoding", "identity").lower() != "identity":
            raise RegistryUnavailableError(
                "GitHub repository response used unsupported content encoding"
            )
        if not isinstance(response.stream, httpx.AsyncByteStream):
            raise RegistryUnavailableError("GitHub repository response is not an async stream")
        limit = REPO_TEXT_MAX_BYTES if file else REPO_METADATA_MAX_BYTES
        data = bytearray()
        # Iterate the identity-encoded transport stream directly: HTTPX's aiter_*
        # auto-closes at EOF before our bounded, cancellation-safe close can run.
        async for chunk in response.stream:
            if not file:
                budget.metadata_bytes += len(chunk)
                if budget.metadata_bytes > REPO_METADATA_TOTAL_BYTES:
                    raise RegistryUnavailableError(
                        "GitHub repository cumulative metadata budget exceeded"
                    )
            if len(data) + len(chunk) > limit:
                if file:
                    raise RepositoryTargetError("Repository text file exceeds 1 MiB")
                raise RegistryUnavailableError(
                    "GitHub repository metadata response budget exceeded"
                )
            data.extend(chunk)
        return bytes(data)

    @asynccontextmanager
    async def _repo_stream(
        self, url: str, headers: dict[str, str], budget: _RepoBudget
    ) -> AsyncIterator[httpx.Response]:
        async with self._client.stream(
            "GET", url, headers=headers, follow_redirects=False
        ) as response:
            completed = False
            try:
                yield response
                completed = True
            finally:
                close_deadline = min(budget.deadline, anyio.current_time() + budget.cleanup_seconds)
                cleanup_error = None
                try:
                    with anyio.CancelScope(deadline=close_deadline, shield=True) as cleanup:
                        await response.aclose()
                except Exception:
                    cleanup_error = "GitHub repository response cleanup failed"
                if completed:
                    # Deliver cancellation that first arrived inside the cleanup shield.
                    await checkpoint_if_cancelled()
                    if cleanup_error is not None:
                        raise RegistryUnavailableError(cleanup_error) from None
                    # Check the final cancellation state after the cleanup scope has exited.
                    if cleanup.cancel_called:
                        raise RegistryUnavailableError(
                            "GitHub repository response cleanup deadline exceeded"
                        )

    # ------------------------------------------------------------------
    # RegistryAdapter protocol
    # ------------------------------------------------------------------

    async def list_skills(self) -> list[str]:
        """Return skills at any nesting depth inside skills_dir."""
        skills_dir = self._skills_dir_path()

        try:
            tree_sha = await self._get_tree_sha_for_dir(skills_dir)
        except _NotFoundError:
            raise RegistryUnavailableError(
                f"GitHub registry '{self.name}': skills_dir '{skills_dir}' not found"
                f" (ref '{self._config.ref}') — check the registry configuration"
            ) from None

        try:
            tree_entries = await self._get_tree_recursive(tree_sha)
        except _NotFoundError:
            raise RegistryUnavailableError(
                f"GitHub registry '{self.name}': tree SHA '{tree_sha}' not found"
            ) from None

        candidates = [
            str(e.get("path", ""))[: -len("/SKILL.md")]
            for e in tree_entries
            if e.get("type") == "blob" and str(e.get("path", "")).endswith("/SKILL.md")
        ]

        return sorted(_prune_nested(candidates))

    async def fetch_skill(self, skill: str) -> SkillContent:
        """Enumerate the skill subtree and return SKILL.md content + file list."""
        _validate_skill_path(skill)

        skills_dir = self._skills_dir_path()
        skill_path = f"{skills_dir}/{skill}" if skills_dir else skill

        tree_sha = await self._resolve_skill_tree_sha(skill, skill_path, skills_dir)

        try:
            tree_entries = await self._get_tree_recursive(tree_sha)
        except _NotFoundError:
            raise RegistryUnavailableError(
                f"GitHub registry '{self.name}': tree SHA '{tree_sha}' not found"
            ) from None

        skill_md_entry = next(
            (e for e in tree_entries if e.get("path") == "SKILL.md" and e.get("type") == "blob"),
            None,
        )
        if skill_md_entry is None:
            raise SkillNotFoundError(f"skill '{skill}' in registry '{self.name}' has no SKILL.md")

        skill_md_sha = str(skill_md_entry.get("sha", ""))
        try:
            content = await self._get_blob_raw(skill_md_sha)
        except _NotFoundError:
            raise RegistryUnavailableError(
                f"GitHub registry '{self.name}': SKILL.md blob '{skill_md_sha}' not found"
            ) from None

        files = sorted(
            str(e.get("path", ""))
            for e in tree_entries
            if e.get("type") == "blob" and e.get("path") != "SKILL.md"
        )

        return SkillContent(content=content, files=tuple(files))

    async def fetch_file(self, skill: str, file_path: str) -> str:
        """Return the raw text of a companion file.

        Validates both *skill* and *file_path* before any I/O.
        """
        _validate_skill_path(skill)
        _validate_file_path(file_path)

        skills_dir = self._skills_dir_path()
        skill_path = f"{skills_dir}/{skill}" if skills_dir else skill

        tree_sha = await self._resolve_skill_tree_sha(skill, skill_path, skills_dir)

        try:
            tree_entries = await self._get_tree_recursive(tree_sha)
        except _NotFoundError:
            raise RegistryUnavailableError(
                f"GitHub registry '{self.name}': tree SHA '{tree_sha}' not found"
            ) from None

        file_entry = next(
            (
                e
                for e in tree_entries
                if e.get("path") == file_path
                and e.get("type") == "blob"
                and e.get("path") != "SKILL.md"
            ),
            None,
        )
        if file_entry is None:
            raise SkillFileNotFoundError(
                f"file '{file_path}' not found in skill '{skill}' (registry '{self.name}')"
            )

        blob_sha = str(file_entry.get("sha", ""))
        try:
            return await self._get_blob_raw(blob_sha)
        except _NotFoundError:
            raise RegistryUnavailableError(
                f"GitHub registry '{self.name}': blob '{blob_sha}' not found"
            ) from None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _skills_dir_path(self) -> str:
        return self._config.skills_dir.strip("/")

    async def _resolve_skill_tree_sha(self, skill: str, skill_path: str, skills_dir: str) -> str:
        """Return the tree SHA for a skill directory, with correct error classification.

        A 404 on skills_dir itself is infra (RegistryUnavailableError); a 404 deeper
        in the path is agent-recoverable (SkillNotFoundError).
        """
        try:
            return await self._get_tree_sha_for_dir(skill_path)
        except _ParentNotFoundError:
            # The parent directory returned 404.  If the parent IS skills_dir, that's
            # a config-level problem; otherwise the skill path is simply wrong.
            p = PurePosixPath(skill_path)
            parent = "" if p.parent == PurePosixPath(".") else str(p.parent)
            if parent == skills_dir:
                raise RegistryUnavailableError(
                    f"GitHub registry '{self.name}': skills_dir '{skills_dir}' not found"
                    f" — check the registry configuration"
                ) from None
            raise SkillNotFoundError(
                f"skill '{skill}' not found in GitHub registry '{self.name}'"
            ) from None
        except _EntryAbsentError:
            raise SkillNotFoundError(
                f"skill '{skill}' not found in GitHub registry '{self.name}'"
            ) from None

    async def _get_tree_sha_for_dir(self, path: str) -> str:
        """Return the Git tree SHA for the directory at repo-relative *path*.

        Uses the Contents API on the parent directory to read the SHA from the
        directory entry (same approach the old code used for skill entries).
        For an empty *path* (skills_dir at repo root), resolves the root tree SHA
        via the Commits API (Option B — fully specified, no ref-as-tree-ish needed).
        """
        if not path:
            return await self._get_root_tree_sha()

        p = PurePosixPath(path)
        parent = "" if p.parent == PurePosixPath(".") else str(p.parent)
        name = p.name

        try:
            entries = await self._get_contents(parent)
        except _NotFoundError:
            raise _ParentNotFoundError() from None

        entry = next(
            (e for e in entries if str(e.get("name", "")) == name and e.get("type") == "dir"),
            None,
        )
        if entry is None:
            raise _EntryAbsentError()

        sha = str(entry.get("sha", ""))
        if not sha:
            raise RegistryUnavailableError(
                f"GitHub registry '{self.name}': directory '{path}' has no tree SHA"
            )
        return sha

    async def _get_root_tree_sha(self) -> str:
        """Return the root tree SHA by resolving the ref via the Commits API (Option B)."""
        owner = self._config.owner
        repo = self._config.repo
        ref = self._config.ref
        url = f"{_GITHUB_API}/repos/{owner}/{repo}/commits/{ref}"
        headers = {**await self._auth_headers(), "Accept": _JSON_ACCEPT}
        try:
            response = await self._request_with_retry(url, headers=headers)
        except _NotFoundError:
            raise RegistryUnavailableError(
                f"GitHub registry '{self.name}': ref '{ref}' not found"
            ) from None
        data = response.json()
        if not isinstance(data, dict):
            raise RegistryUnavailableError(
                f"GitHub registry '{self.name}': unexpected Commits API response for ref '{ref}'"
            )
        tree_sha = str(data.get("commit", {}).get("tree", {}).get("sha", ""))
        if not tree_sha:
            raise RegistryUnavailableError(
                f"GitHub registry '{self.name}': could not resolve root tree SHA from ref '{ref}'"
            )
        return tree_sha

    async def _auth_headers(self) -> dict[str, str]:
        return await self._auth.headers_for(self._config.auth)

    async def _get_contents(self, path: str) -> list[dict[str, object]]:
        """Call GitHub Contents API; return a list of entry dicts."""
        owner = self._config.owner
        repo = self._config.repo
        ref = self._config.ref
        url = f"{_GITHUB_API}/repos/{owner}/{repo}/contents/{path}"
        params: dict[str, str] = {"ref": ref}
        headers = {**await self._auth_headers(), "Accept": _JSON_ACCEPT}

        response = await self._request_with_retry(url, headers=headers, params=params)
        data = response.json()
        if not isinstance(data, list):
            raise RegistryUnavailableError(
                f"GitHub registry '{self.name}': Contents API returned unexpected type "
                f"for path '{path}'"
            )
        result: list[dict[str, object]] = []
        for item in data:
            if isinstance(item, dict):
                result.append(item)
        return result

    async def _get_tree_recursive(self, tree_sha: str) -> list[dict[str, object]]:
        """Call Git Trees API with recursive=1; return flat list of entries."""
        owner = self._config.owner
        repo = self._config.repo
        url = f"{_GITHUB_API}/repos/{owner}/{repo}/git/trees/{tree_sha}"
        params: dict[str, str] = {"recursive": "1"}
        headers = {**await self._auth_headers(), "Accept": _JSON_ACCEPT}

        response = await self._request_with_retry(url, headers=headers, params=params)
        data = response.json()
        if not isinstance(data, dict):
            raise RegistryUnavailableError(
                f"GitHub registry '{self.name}': Trees API returned unexpected type"
            )
        truncated = data.get("truncated", False)
        if truncated:
            logger.warning(
                "GitHub registry '%s': Trees API response was truncated; "
                "some skills or companion files may be missing.",
                self.name,
            )
        tree = data.get("tree", [])
        if not isinstance(tree, list):
            return []
        result: list[dict[str, object]] = []
        for item in tree:
            if isinstance(item, dict):
                result.append(item)
        return result

    async def _get_blob_raw(self, blob_sha: str) -> str:
        """Fetch raw blob content by SHA."""
        owner = self._config.owner
        repo = self._config.repo
        url = f"{_GITHUB_API}/repos/{owner}/{repo}/git/blobs/{blob_sha}"
        headers = {**await self._auth_headers(), "Accept": _RAW_ACCEPT}

        response = await self._request_with_retry(url, headers=headers)
        return response.text

    async def _request_with_retry(
        self,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Make a GET request, honouring Retry-After once on 429/403."""
        try:
            response = await self._client.get(url, headers=headers, params=params)
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            raise RegistryUnavailableError(
                f"GitHub registry '{self.name}': request to {url} failed: {exc}"
            ) from exc

        if response.status_code in (429, 403) and "Retry-After" in response.headers:
            retry_after_str = response.headers.get("Retry-After", "0")
            try:
                wait = min(float(retry_after_str), _MAX_RETRY_AFTER)
            except ValueError:
                wait = _MAX_RETRY_AFTER
            if wait > 0:
                await asyncio.sleep(wait)
            # Retry once
            try:
                response = await self._client.get(url, headers=headers, params=params)
            except (httpx.TimeoutException, httpx.RequestError) as exc:
                raise RegistryUnavailableError(
                    f"GitHub registry '{self.name}': request to {url} failed on retry: {exc}"
                ) from exc
            if response.is_error:
                raise RegistryUnavailableError(
                    f"GitHub registry '{self.name}': upstream returned "
                    f"{response.status_code} after retry"
                )
            return response

        if response.status_code == 429:
            raise RegistryUnavailableError(
                f"GitHub registry '{self.name}': rate limited (429) with no Retry-After header"
            )

        if response.status_code == 403:
            raise RegistryUnavailableError(
                f"GitHub registry '{self.name}': forbidden (403) — check authentication config"
            )

        if response.status_code == 404:
            raise _NotFoundError()

        if response.is_error:
            raise RegistryUnavailableError(
                f"GitHub registry '{self.name}': upstream returned {response.status_code} for {url}"
            )

        return response


def _validate_path(value: str, label: str) -> None:
    """Raise PathTraversalError if *value* is empty, absolute, or contains escaping '..'."""
    if not value:
        raise PathTraversalError(f"{label} must not be empty")

    p = PurePosixPath(value)

    if p.is_absolute():
        raise PathTraversalError(f"{label} '{value}' is absolute; only relative paths are allowed")

    depth = 0
    for part in p.parts:
        if part == "..":
            depth -= 1
            if depth < 0:
                raise PathTraversalError(
                    f"{label} '{value}' contains '..' segments that escape the root"
                )
        elif part != ".":
            depth += 1


def _validate_file_path(file_path: str) -> None:
    """Raise PathTraversalError if file_path is unsafe."""
    _validate_path(file_path, "file_path")


def _validate_skill_path(skill: str) -> None:
    """Raise PathTraversalError if skill is unsafe (empty, absolute, or escaping '..')."""
    _validate_path(skill, "skill")


def _prune_nested(candidates: list[str]) -> list[str]:
    """Remove candidates that are descendants of another candidate.

    Keeps the shallowest SKILL.md on each ancestor path, so a skill that bundles
    an example SKILL.md inside its companion-file tree does not produce a phantom
    second skill entry.
    """
    candidate_set = set(candidates)
    result = []
    for candidate in candidates:
        if any(candidate.startswith(other + "/") for other in candidate_set if other != candidate):
            logger.debug("Pruning nested skill '%s': ancestor skill already in listing", candidate)
        else:
            result.append(candidate)
    return result
