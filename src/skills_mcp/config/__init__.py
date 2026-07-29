"""Config package — re-exports for convenience."""

from .loader import load_config
from .model import (
    BasicAuth,
    BearerAuth,
    CacheConfig,
    Config,
    GhCliAuth,
    GithubRegistry,
    GithubTokenAuth,
    HttpRegistry,
    NoAuth,
    RegistryVariant,
)

__all__ = [
    "BasicAuth",
    "BearerAuth",
    "CacheConfig",
    "Config",
    "GhCliAuth",
    "GithubRegistry",
    "GithubTokenAuth",
    "HttpRegistry",
    "NoAuth",
    "RegistryVariant",
    "load_config",
]
