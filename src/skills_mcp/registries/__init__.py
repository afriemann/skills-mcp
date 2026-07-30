"""Registry adapter protocol, SkillContent, CachingRegistry, and build_adapters factory."""

from __future__ import annotations

import json
import logging
from typing import Protocol, runtime_checkable

import anyio
import httpx

from ..auth import AuthResolver
from ..cache import _SKILL_CONTENT_FILE, _SKILL_INDEX_FILE, _SKILLS_LIST_FILE, DiskCache
from ..config.model import Config, GithubRegistry, HttpRegistry

logger = logging.getLogger(__name__)


class SkillContent:
    """The content of a fetched skill."""

    __slots__ = ("content", "files")

    def __init__(self, content: str, files: tuple[str, ...]) -> None:
        self.content = content
        self.files = files

    def to_dict(self) -> dict[str, object]:
        return {"content": self.content, "files": list(self.files)}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> SkillContent:
        raw_files = data.get("files", [])
        files_seq = list(raw_files) if isinstance(raw_files, (list, tuple)) else []
        return cls(
            content=str(data["content"]),
            files=tuple(str(f) for f in files_seq),
        )


@runtime_checkable
class RegistryAdapter(Protocol):
    """Protocol implemented by all registry adapters."""

    name: str
    type: str
    ref: str | None

    async def list_skills(self) -> list[str]: ...

    async def fetch_skill(self, skill: str) -> SkillContent: ...

    async def fetch_file(self, skill: str, file_path: str) -> str: ...


@runtime_checkable
class MetadataRegistry(Protocol):
    """Extended protocol satisfied by CachingRegistry — adds skill-index and refresh support."""

    name: str
    type: str
    ref: str | None

    async def list_skills(self) -> list[str]: ...

    async def fetch_skill(self, skill: str, *, refresh: bool = False) -> SkillContent: ...

    async def fetch_file(self, skill: str, file_path: str) -> str: ...

    async def list_skills_metadata(self, *, refresh: bool = False) -> list[dict[str, object]]: ...


class CachingRegistry:
    """Decorator that wraps a RegistryAdapter with read-through disk caching.

    Satisfies both ``RegistryAdapter`` and ``MetadataRegistry``.
    """

    def __init__(
        self,
        inner: RegistryAdapter,
        cache: DiskCache,
        *,
        immutable: bool,
        enabled: bool,
    ) -> None:
        self._inner = inner
        self._cache = cache
        self._immutable = immutable
        self._enabled = enabled

        # Expose the same protocol fields
        self.name = inner.name
        self.type = inner.type
        self.ref = inner.ref

        # Per-instance lock serialising index read-modify-write
        self._index_lock: anyio.Lock = anyio.Lock()

    async def list_skills(self) -> list[str]:
        ref = self._inner.ref or "_http"
        if self._enabled:
            cached = self._cache.get(
                self.name, ref, "__meta__", _SKILLS_LIST_FILE, immutable=self._immutable
            )
            if cached is not None:
                parsed = json.loads(cached)
                return [str(s) for s in parsed] if isinstance(parsed, list) else []
        result = await self._inner.list_skills()
        if self._enabled:
            self._cache.put(
                self.name, ref, "__meta__", _SKILLS_LIST_FILE, json.dumps(result).encode()
            )
        return result

    async def fetch_skill(self, skill: str, *, refresh: bool = False) -> SkillContent:
        """Fetch *skill*'s SKILL.md and companion file list.

        When *refresh* is ``True``, the per-skill cache entry is bypassed on
        the read path, fresh content is fetched from the inner adapter, and the
        result is written back so subsequent ``refresh=False`` calls are served
        from cache.
        """
        ref = self._inner.ref or "_http"
        if self._enabled and not refresh:
            cached = self._cache.get(
                self.name, ref, skill, _SKILL_CONTENT_FILE, immutable=self._immutable
            )
            if cached is not None:
                return SkillContent.from_dict(json.loads(cached))
        result = await self._inner.fetch_skill(skill)
        if self._enabled:
            self._cache.put(
                self.name,
                ref,
                skill,
                _SKILL_CONTENT_FILE,
                json.dumps(result.to_dict()).encode(),
            )
        return result

    async def fetch_file(self, skill: str, file_path: str) -> str:
        ref = self._inner.ref or "_http"
        if self._enabled:
            cached = self._cache.get(self.name, ref, skill, file_path, immutable=self._immutable)
            if cached is not None:
                return cached.decode("utf-8")
        result = await self._inner.fetch_file(skill, file_path)
        if self._enabled:
            self._cache.put(self.name, ref, skill, file_path, result.encode("utf-8"))
        return result

    async def list_skills_metadata(self, *, refresh: bool = False) -> list[dict[str, object]]:
        """Return a sorted listing of skills with frontmatter metadata.

        Builds and incrementally maintains a skill index in DiskCache.  On each
        call only skills absent from the index are fetched; deleted skills are
        retired.  When *refresh* is ``True``, the names cache and the index are
        both bypassed and all skills are re-fetched.

        Error handling:
          - Fetch failure  → name-only entry in the response; NOT persisted
            (retried on next call).
          - Parse failure  → parsed keys (possibly empty) persisted; deterministic.

        The identifier from ``list_skills`` is always authoritative for the
        ``"name"`` key — any ``name:`` field in SKILL.md frontmatter is discarded.
        """
        from ..frontmatter import parse_frontmatter

        async with self._index_lock:
            ref = self._inner.ref or "_http"

            # ---- 1. Resolve authoritative names --------------------------------
            if refresh:
                names = await self._inner.list_skills()
                if self._enabled:
                    self._cache.put(
                        self.name,
                        ref,
                        "__meta__",
                        _SKILLS_LIST_FILE,
                        json.dumps(names).encode(),
                    )
                index: dict[str, dict[str, object]] = {}
            else:
                names = await self.list_skills()
                index = {}
                if self._enabled:
                    raw_idx = self._cache.get(
                        self.name,
                        ref,
                        "__meta__",
                        _SKILL_INDEX_FILE,
                        immutable=self._immutable,
                    )
                    if raw_idx is not None:
                        try:
                            loaded = json.loads(raw_idx)
                            if isinstance(loaded, dict):
                                index = {k: v for k, v in loaded.items() if isinstance(v, dict)}
                        except (json.JSONDecodeError, ValueError):
                            index = {}

            # ---- 2. Retire deleted skills ---------------------------------------
            names_set = set(names)
            _pre_retire_keys = set(index.keys())
            index = {k: v for k, v in index.items() if k in names_set}
            _retired = _pre_retire_keys - names_set

            # ---- 3. Compute missing skills to fetch -----------------------------
            to_fetch = names_set - set(index.keys())

            # ---- 4. Fan out concurrent fetches with per-skill error isolation ---
            fetch_results: dict[str, SkillContent | BaseException] = {}

            if to_fetch:
                async with anyio.create_task_group() as tg:

                    async def _fetch_one(skill_name: str) -> None:
                        try:
                            sc = await self.fetch_skill(skill_name, refresh=refresh)
                            fetch_results[skill_name] = sc
                        except Exception as exc:
                            fetch_results[skill_name] = exc

                    for skill_name in to_fetch:
                        tg.start_soon(_fetch_one, skill_name)

            # ---- 5. Merge results into index ------------------------------------
            for skill_name, outcome in fetch_results.items():
                if isinstance(outcome, BaseException):
                    # Fetch failure: name-only in this response, NOT persisted
                    logger.debug(
                        "fetch_skill failed for %r in %r: %s",
                        skill_name,
                        self.name,
                        outcome,
                    )
                    continue
                fm = parse_frontmatter(outcome.content)
                # Identifier wins — drop any frontmatter name: field
                entry: dict[str, object] = {
                    "name": skill_name,
                    **{k: v for k, v in fm.items() if k != "name"},
                }
                index[skill_name] = entry

            # ---- 6. Persist reconciled index -----------------------------------
            # Persist when new skills were fetched OR deleted skills were retired
            # (ensures the on-disk index does not serve stale entries indefinitely)
            if self._enabled and (to_fetch or _retired):
                self._cache.put(
                    self.name,
                    ref,
                    "__meta__",
                    _SKILL_INDEX_FILE,
                    json.dumps(index).encode(),
                )

            # ---- 7. Build response ---------------------------------------------
            result: list[dict[str, object]] = []
            for skill_name in sorted(names):
                if skill_name in index:
                    result.append(index[skill_name])
                else:
                    result.append({"name": skill_name})

            return result


def build_adapters(
    config: Config,
    http_client: httpx.AsyncClient,
    auth_resolver: AuthResolver,
) -> dict[str, MetadataRegistry]:
    """Build one CachingRegistry-wrapped adapter per configured registry."""
    from .github import GithubAdapter
    from .http import HttpAdapter

    adapters: dict[str, MetadataRegistry] = {}
    cache = DiskCache(
        config.cache.dir,
        enabled=config.cache.enabled,
        ttl_seconds=config.cache.ttl_seconds,
    )

    for name, reg in config.registries.items():
        if isinstance(reg, GithubRegistry):
            inner: RegistryAdapter = GithubAdapter(reg, http_client, auth_resolver)
            immutable = reg.ref_is_sha
            enabled = config.cache.enabled and reg.cache_enabled
        elif isinstance(reg, HttpRegistry):
            inner = HttpAdapter(reg, http_client, auth_resolver)
            immutable = False
            enabled = config.cache.enabled and reg.cache_enabled
        else:
            continue  # unknown type; skip (should not happen after config validation)

        adapters[name] = CachingRegistry(inner, cache, immutable=immutable, enabled=enabled)

    return adapters
