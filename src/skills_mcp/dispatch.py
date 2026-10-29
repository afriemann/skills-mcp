"""Dispatcher — routes tool calls to the correct registry adapter."""

from __future__ import annotations

from .errors import RegistryNotFoundError
from .registries import MetadataRegistry, SkillContent


class Dispatcher:
    """Holds the registry adapters and routes the tool operations."""

    def __init__(
        self,
        adapters: dict[str, MetadataRegistry],
    ) -> None:
        self._adapters = adapters

    async def get_registry_source(self, registry: str) -> dict[str, object]:
        return await self._get_adapter(registry).get_registry_source()

    async def list_repo_entries(self, registry: str, path: str = "") -> dict[str, object]:
        return await self._get_adapter(registry).list_repo_entries(path)

    async def read_repo_text_file(self, registry: str, path: str) -> dict[str, object]:
        return await self._get_adapter(registry).read_repo_text_file(path)

    async def list_skills_metadata(
        self, registry: str, *, refresh: bool = False
    ) -> list[dict[str, object]]:
        """Return skill listing with frontmatter metadata from the index."""
        return await self._get_adapter(registry).list_skills_metadata(refresh=refresh)

    async def get_skill(
        self,
        registry: str,
        skill: str,
        file: str | None = None,
        *,
        refresh: bool = False,
    ) -> SkillContent | str:
        """Fetch a skill or one of its companion files.

        When *file* is None: returns a SkillContent (SKILL.md + file list).
        When *file* is provided: returns the raw companion-file text directly,
        routing straight to fetch_file without a prior fetch_skill call.
        The *refresh* parameter is forwarded to ``fetch_skill`` and is ignored
        when *file* is provided.
        """
        if file is None:
            return await self._get_adapter(registry).fetch_skill(skill, refresh=refresh)
        return await self._get_adapter(registry).fetch_file(skill, file)

    async def get_skill_file(self, registry: str, skill: str, file_path: str) -> str:
        """Internal helper kept for backwards-compatible internal use."""
        return await self._get_adapter(registry).fetch_file(skill, file_path)

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _get_adapter(self, registry: str) -> MetadataRegistry:
        adapter = self._adapters.get(registry)
        if adapter is None:
            available = sorted(self._adapters.keys())
            raise RegistryNotFoundError(
                f"registry '{registry}' not found; available registries: {available}"
            )
        return adapter
