"""GitHub registry adapter — two-phase fetch via Contents + Trees + Blobs APIs."""

from __future__ import annotations

import asyncio
import logging
from pathlib import PurePosixPath

import httpx

from ..auth import AuthResolver
from ..config.model import GithubRegistry
from ..errors import (
    PathTraversalError,
    RegistryUnavailableError,
    SkillFileNotFoundError,
    SkillNotFoundError,
)
from . import SkillContent

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_RAW_ACCEPT = "application/vnd.github.raw"
_JSON_ACCEPT = "application/vnd.github+json"

# Maximum Retry-After we will honour (seconds).
_MAX_RETRY_AFTER = 5.0


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
