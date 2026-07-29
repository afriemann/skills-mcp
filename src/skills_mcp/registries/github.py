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

# GitHub Contents API entry count that triggers a truncation warning.
_CONTENTS_TRUNCATION_WARNING = 1000


class _NotFoundError(Exception):
    """Internal signal: GitHub returned 404."""


class GithubAdapter:
    """Fetches skills from a GitHub repository using the REST API.

    Phase 1 (list_skills):   Contents API -> skill subdirectories.
    Phase 2 (fetch_skill):   Contents API to get skill dir entry sha
                              -> recursive Git Trees API -> SKILL.md blob SHA
                              -> Blobs raw endpoint.
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
        """Return subdirectory names inside skills_dir at ref."""
        try:
            entries = await self._get_contents(self._skills_dir_path())
        except _NotFoundError:
            raise RegistryUnavailableError(
                f"GitHub registry '{self.name}': skills_dir '{self._skills_dir_path()}' not found"
                f" (ref '{self._config.ref}') — check the registry configuration"
            ) from None
        dirs = [str(e["name"]) for e in entries if e.get("type") == "dir"]
        if len(entries) >= _CONTENTS_TRUNCATION_WARNING:
            logger.warning(
                "GitHub registry '%s': Contents API returned %d entries (at the 1,000-entry "
                "limit); the skill list may be truncated.",
                self.name,
                len(entries),
            )
        return sorted(dirs)

    async def fetch_skill(self, skill: str) -> SkillContent:
        """Enumerate the skill subtree and return SKILL.md content + file list."""
        try:
            entries = await self._get_contents(self._skills_dir_path())
        except _NotFoundError:
            raise RegistryUnavailableError(
                f"GitHub registry '{self.name}': skills_dir '{self._skills_dir_path()}' not found"
                f" — check the registry configuration"
            ) from None

        skill_entry = next(
            (e for e in entries if str(e.get("name", "")) == skill and e.get("type") == "dir"),
            None,
        )
        if skill_entry is None:
            raise SkillNotFoundError(f"skill '{skill}' not found in GitHub registry '{self.name}'")

        tree_sha = str(skill_entry.get("sha", ""))
        if not tree_sha:
            raise RegistryUnavailableError(
                f"GitHub registry '{self.name}': skill '{skill}' directory has no tree SHA"
            )

        # Recursive tree listing (one API call)
        try:
            tree_entries = await self._get_tree_recursive(tree_sha)
        except _NotFoundError:
            raise RegistryUnavailableError(
                f"GitHub registry '{self.name}': tree SHA '{tree_sha}' not found"
            ) from None

        # Locate SKILL.md
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

        # Companion files: all other blobs, sorted
        files = sorted(
            str(e.get("path", ""))
            for e in tree_entries
            if e.get("type") == "blob" and e.get("path") != "SKILL.md"
        )

        return SkillContent(content=content, files=tuple(files))

    async def fetch_file(self, skill: str, file_path: str) -> str:
        """Return the raw text of a companion file.

        Validates *file_path* against the skill's file tree before fetching.
        """
        # Phase 1: path guard (logical)
        _validate_file_path(file_path)

        # Phase 2: enumerate tree for defence-in-depth and to get blob SHA
        try:
            entries = await self._get_contents(self._skills_dir_path())
        except _NotFoundError:
            raise RegistryUnavailableError(
                f"GitHub registry '{self.name}': skills_dir '{self._skills_dir_path()}' not found"
                f" — check the registry configuration"
            ) from None

        skill_entry = next(
            (e for e in entries if str(e.get("name", "")) == skill and e.get("type") == "dir"),
            None,
        )
        if skill_entry is None:
            raise SkillNotFoundError(f"skill '{skill}' not found in GitHub registry '{self.name}'")

        tree_sha = str(skill_entry.get("sha", ""))
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
    # Private GitHub API helpers
    # ------------------------------------------------------------------

    def _skills_dir_path(self) -> str:
        return self._config.skills_dir.strip("/")

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
                "some companion files may be missing.",
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


def _validate_file_path(file_path: str) -> None:
    """Raise PathTraversalError if file_path is unsafe."""
    if not file_path:
        raise PathTraversalError("file_path must not be empty")

    p = PurePosixPath(file_path)

    # Reject absolute paths
    if p.is_absolute():
        raise PathTraversalError(
            f"file_path '{file_path}' is absolute; only relative paths are allowed"
        )

    # Reject any path whose components escape the root via '..'
    depth = 0
    for part in p.parts:
        if part == "..":
            depth -= 1
            if depth < 0:
                raise PathTraversalError(
                    f"file_path '{file_path}' contains '..' segments that escape the skill root"
                )
        elif part != ".":
            depth += 1
