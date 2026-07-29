"""Dispatcher — routes tool calls to the correct registry adapter."""

from __future__ import annotations

from .errors import RegistryNotFoundError
from .registries import RegistryAdapter, SkillContent


class Dispatcher:
    """Holds the registry adapters and routes the four tool operations."""

    def __init__(self, adapters: dict[str, RegistryAdapter]) -> None:
        self._adapters = adapters

    def list_registries(self) -> list[dict[str, object]]:
        """Return metadata for all configured registries (pure, no I/O)."""
        result: list[dict[str, object]] = []
        for adapter in self._adapters.values():
            entry: dict[str, object] = {"name": adapter.name, "type": adapter.type}
            if adapter.ref is not None:
                entry["ref"] = adapter.ref
            result.append(entry)
        return result

    async def list_skills(self, registry: str) -> list[str]:
        return await self._get_adapter(registry).list_skills()

    async def get_skill(self, registry: str, skill: str) -> SkillContent:
        return await self._get_adapter(registry).fetch_skill(skill)

    async def get_skill_file(self, registry: str, skill: str, file_path: str) -> str:
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
