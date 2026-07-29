"""HTTP registry adapter — fetches a single SKILL.md from a direct URL."""

from __future__ import annotations

import logging

import httpx

from ..auth import AuthResolver
from ..config.model import HttpRegistry
from ..errors import RegistryUnavailableError, SkillNotFoundError, UnsupportedOperationError
from . import SkillContent

logger = logging.getLogger(__name__)


class HttpAdapter:
    """Fetches a single SKILL.md from a configured HTTP URL.

    list_skills  → [skill_name]
    fetch_skill  → GET url → SkillContent(content, files=())
    fetch_file   → UnsupportedOperationError (HTTP registries have no file tree)
    """

    type = "http"
    ref: str | None = None

    def __init__(
        self,
        config: HttpRegistry,
        http_client: httpx.AsyncClient,
        auth_resolver: AuthResolver,
    ) -> None:
        self._config = config
        self._client = http_client
        self._auth = auth_resolver
        self.name = config.name

    async def list_skills(self) -> list[str]:
        return [self._config.skill_name]

    async def fetch_skill(self, skill: str) -> SkillContent:
        if skill != self._config.skill_name:
            raise SkillNotFoundError(
                f"skill '{skill}' not found in HTTP registry '{self.name}'; "
                f"this registry exposes only '{self._config.skill_name}'"
            )
        headers = await self._auth.headers_for(self._config.auth)
        try:
            response = await self._client.get(self._config.url, headers=headers)
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            raise RegistryUnavailableError(
                f"HTTP registry '{self.name}': request failed: {exc}"
            ) from exc
        if response.status_code == 404:
            raise SkillNotFoundError(f"skill '{skill}' not found at {self._config.url} (404)")
        if response.is_error:
            raise RegistryUnavailableError(
                f"HTTP registry '{self.name}': upstream returned {response.status_code}"
            )
        return SkillContent(content=response.text, files=())

    async def fetch_file(self, skill: str, file_path: str) -> str:
        raise UnsupportedOperationError(
            f"get_skill_file is not supported for HTTP registries (registry: '{self.name}'). "
            f"HTTP registries expose a single SKILL.md with no companion file tree."
        )
