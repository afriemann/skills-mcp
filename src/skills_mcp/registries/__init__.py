"""Registry adapter protocol, SkillContent, CachingRegistry, and build_adapters factory."""

from __future__ import annotations

import json
import logging
from typing import Protocol, runtime_checkable

import httpx

from ..auth import AuthResolver
from ..cache import _SKILL_CONTENT_FILE, _SKILLS_LIST_FILE, DiskCache
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


class CachingRegistry:
    """Decorator that wraps a RegistryAdapter with read-through disk caching."""

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

    async def fetch_skill(self, skill: str) -> SkillContent:
        ref = self._inner.ref or "_http"
        if self._enabled:
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


def build_adapters(
    config: Config,
    http_client: httpx.AsyncClient,
    auth_resolver: AuthResolver,
) -> dict[str, RegistryAdapter]:
    """Build one CachingRegistry-wrapped adapter per configured registry."""
    from .github import GithubAdapter
    from .http import HttpAdapter

    adapters: dict[str, RegistryAdapter] = {}
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
