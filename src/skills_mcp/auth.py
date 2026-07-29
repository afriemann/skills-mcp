"""Authentication resolver for skills-mcp.

Reads secret values from environment variables at request time.
Caches the gh-CLI token in-process (one subprocess per lifetime).
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os

import anyio

from .config.model import (
    BasicAuth,
    BearerAuth,
    GhCliAuth,
    GithubAuthVariant,
    GithubTokenAuth,
    HttpAuthVariant,
    NoAuth,
)
from .errors import RegistryUnavailableError

logger = logging.getLogger(__name__)


class AuthResolver:
    """Resolves authentication credentials into HTTP headers.

    A single instance is shared for the server lifetime; ``gh_cli`` tokens
    are cached in-process behind an asyncio lock.
    """

    def __init__(self) -> None:
        self._gh_token: str | None = None
        self._gh_lock: asyncio.Lock = asyncio.Lock()

    def headers_for_sync(self, auth: GithubAuthVariant | HttpAuthVariant) -> dict[str, str]:
        """Return HTTP headers for *auth* — synchronous variant (no gh_cli support)."""
        return self._resolve_sync(auth)

    async def headers_for(self, auth: GithubAuthVariant | HttpAuthVariant) -> dict[str, str]:
        """Return HTTP headers for *auth*, awaiting gh_cli if needed."""
        if isinstance(auth, GhCliAuth):
            token = await self._gh_token_cached()
            if not token:
                return {}  # graceful fallback — gh absent or failed
            return {"Authorization": f"Bearer {token}"}
        return self._resolve_sync(auth)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_sync(self, auth: GithubAuthVariant | HttpAuthVariant) -> dict[str, str]:
        if isinstance(auth, NoAuth):
            return {}
        if isinstance(auth, (GithubTokenAuth, BearerAuth)):
            value = os.environ.get(auth.env_var, "")
            if not value:
                raise RegistryUnavailableError(f"auth env var '{auth.env_var}' is not set or empty")
            return {"Authorization": f"Bearer {value}"}
        if isinstance(auth, BasicAuth):
            username = os.environ.get(auth.username_env_var, "")
            password = os.environ.get(auth.password_env_var, "")
            if not username:
                raise RegistryUnavailableError(
                    f"auth env var '{auth.username_env_var}' is not set or empty"
                )
            if not password:
                raise RegistryUnavailableError(
                    f"auth env var '{auth.password_env_var}' is not set or empty"
                )
            token = base64.b64encode(f"{username}:{password}".encode()).decode()
            return {"Authorization": f"Basic {token}"}
        if isinstance(auth, GhCliAuth):
            raise RuntimeError(
                "GhCliAuth requires the async headers_for(); use await"
            )  # programming error
        return {}  # unreachable

    async def _gh_token_cached(self) -> str:
        """Return a cached gh-CLI token, running `gh auth token` on cache miss.

        Falls back to empty string (NoAuth) and logs a warning if gh is absent
        or returns a non-zero exit code.
        """
        if self._gh_token is not None:
            return self._gh_token

        async with self._gh_lock:
            # Re-check inside the lock (another coroutine may have populated it)
            if self._gh_token is not None:
                return self._gh_token

            try:
                result = await anyio.run_process(
                    ["gh", "auth", "token"],
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                token = result.stdout.decode().strip()
                if not token:
                    logger.warning(
                        "gh auth token returned an empty token; "
                        "falling back to unauthenticated requests"
                    )
                    self._gh_token = ""
                else:
                    self._gh_token = token
            except (FileNotFoundError, OSError):
                logger.warning("gh CLI not found on PATH; falling back to unauthenticated requests")
                self._gh_token = ""
            except Exception as exc:
                logger.warning(
                    "gh auth token failed (%s); falling back to unauthenticated requests",
                    exc,
                )
                self._gh_token = ""

            return self._gh_token
