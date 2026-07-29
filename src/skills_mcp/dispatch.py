"""Dispatcher — routes tool calls to the correct registry adapter."""

from __future__ import annotations

from .errors import RegistryNotFoundError
from .registries import RegistryAdapter, SkillContent


class Dispatcher:
    """Holds the registry adapters and routes the three tool operations."""

    def __init__(
        self,
        adapters: dict[str, RegistryAdapter],
        descriptions: dict[str, str | None] | None = None,
    ) -> None:
        self._adapters = adapters
        self._descriptions: dict[str, str | None] = descriptions or {}

    def list_registries(self) -> list[dict[str, object]]:
        """Return metadata for all configured registries (pure, no I/O)."""
        result: list[dict[str, object]] = []
        for adapter in self._adapters.values():
            entry: dict[str, object] = {"name": adapter.name, "type": adapter.type}
            if adapter.ref is not None:
                entry["ref"] = adapter.ref
            desc = self._descriptions.get(adapter.name)
            if desc is not None:
                entry["description"] = desc
            result.append(entry)
        return result

    async def list_skills(self, registry: str) -> list[str]:
        return await self._get_adapter(registry).list_skills()

    async def get_skill(
        self, registry: str, skill: str, file: str | None = None
    ) -> SkillContent | str:
        """Fetch a skill or one of its companion files.

        When *file* is None: returns a SkillContent (SKILL.md + file list).
        When *file* is provided: returns the raw companion-file text directly,
        routing straight to fetch_file without a prior fetch_skill call.
        """
        if file is None:
            return await self._get_adapter(registry).fetch_skill(skill)
        return await self._get_adapter(registry).fetch_file(skill, file)

    async def get_skill_file(self, registry: str, skill: str, file_path: str) -> str:
        """Internal helper kept for backwards-compatible internal use."""
        return await self._get_adapter(registry).fetch_file(skill, file_path)

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _get_adapter(self, registry: str) -> RegistryAdapter:
        adapter = self._adapters.get(registry)
        if adapter is None:
            available = sorted(self._adapters.keys())
            raise RegistryNotFoundError(
                f"registry '{registry}' not found; available registries: {available}"
            )
        return adapter
