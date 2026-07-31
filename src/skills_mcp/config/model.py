"""Frozen dataclass configuration model for skills-mcp.

All types are immutable (frozen=True).  Auth variants carry env-var NAMES only —
secret values are never stored here.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


def _default_cache_dir() -> Path:
    """Return the platform-appropriate cache directory for skills-mcp.

    Priority (all platforms): $XDG_CACHE_HOME/skills-mcp
    Linux default:  ~/.cache/skills-mcp
    macOS default:  ~/Library/Caches/skills-mcp
    Windows default: %LOCALAPPDATA%/skills-mcp/Cache
    """
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg) / "skills-mcp"
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            return Path(local) / "skills-mcp" / "Cache"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "skills-mcp"
    return Path.home() / ".cache" / "skills-mcp"


# ---------------------------------------------------------------------------
# Auth variants
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NoAuth:
    """No authentication."""


@dataclass(frozen=True)
class GithubTokenAuth:
    """Personal Access Token stored in the named environment variable."""

    env_var: str


@dataclass(frozen=True)
class GhCliAuth:
    """Token obtained via `gh auth token` subprocess (cached in-process)."""


@dataclass(frozen=True)
class BearerAuth:
    """Bearer token stored in the named environment variable."""

    env_var: str


@dataclass(frozen=True)
class BasicAuth:
    """HTTP Basic credentials stored in the named environment variables."""

    username_env_var: str
    password_env_var: str


GithubAuthVariant = NoAuth | GithubTokenAuth | GhCliAuth
HttpAuthVariant = NoAuth | BearerAuth | BasicAuth

# ---------------------------------------------------------------------------
# Registry types
# ---------------------------------------------------------------------------

_SHA_PATTERN = re.compile(r"^[0-9a-f]{7,40}$")


@dataclass(frozen=True)
class GithubRegistry:
    """A multi-skill GitHub repository registry."""

    name: str
    owner: str
    repo: str
    skills_dir: str
    ref: str
    auth: GithubAuthVariant = field(default_factory=NoAuth)
    cache_enabled: bool = True
    description: str | None = None
    instructions: str | None = None

    @property
    def ref_is_sha(self) -> bool:
        """True when *ref* is a full or abbreviated commit SHA (7-40 hex chars)."""
        return bool(_SHA_PATTERN.match(self.ref))


@dataclass(frozen=True)
class HttpRegistry:
    """A single-URL HTTP registry pointing directly at a SKILL.md."""

    name: str
    url: str
    skill_name: str
    auth: HttpAuthVariant = field(default_factory=NoAuth)
    cache_enabled: bool = True
    description: str | None = None
    instructions: str | None = None


RegistryVariant = GithubRegistry | HttpRegistry

# ---------------------------------------------------------------------------
# Cache config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CacheConfig:
    """Disk cache configuration."""

    enabled: bool = True
    dir: Path = field(default_factory=_default_cache_dir)
    ttl_seconds: int = 3600


# ---------------------------------------------------------------------------
# Top-level config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Config:
    """Top-level configuration loaded from skills-mcp.jsonc."""

    registries: dict[str, RegistryVariant]
    cache: CacheConfig = field(default_factory=CacheConfig)
