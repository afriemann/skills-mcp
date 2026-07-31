"""JSONC configuration loader for skills-mcp.

Responsible for:
- JSONC comment stripping (string-aware; preserves '//' inside URL literals)
- JSON parsing
- Structural validation and construction of the frozen Config dataclass
- _fatal() / sys.exit(1) on any fatal error (called at startup; never after)
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

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


def _default_config_path() -> Path:
    """Return the platform-appropriate config file path for skills-mcp.

    Priority (all platforms): $XDG_CONFIG_HOME/skills-mcp/config.jsonc
    Linux default:  ~/.config/skills-mcp/config.jsonc
    macOS default:  ~/Library/Application Support/skills-mcp/config.jsonc
    Windows default: %APPDATA%/skills-mcp/config.jsonc
    """
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "skills-mcp" / "config.jsonc"
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            return Path(appdata) / "skills-mcp" / "config.jsonc"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "skills-mcp" / "config.jsonc"
    return Path.home() / ".config" / "skills-mcp" / "config.jsonc"


# ---------------------------------------------------------------------------
# JSONC stripper
# ---------------------------------------------------------------------------


def strip_jsonc(text: str) -> str:
    """Remove JSONC comments from *text*, preserving '//' inside string literals.

    Handles:
    - ``//`` line comments (outside strings)
    - ``/* */`` block comments (outside strings)
    - Trailing commas before ``]`` or ``}``
    - ``\"`` escape sequences inside strings
    - ``\\`` escape sequences inside strings

    Returns valid JSON that ``json.loads`` can parse.
    """
    result: list[str] = []
    i = 0
    n = len(text)
    in_string = False
    in_block_comment = False

    while i < n:
        ch = text[i]

        if in_block_comment:
            if ch == "*" and i + 1 < n and text[i + 1] == "/":
                # End of block comment
                i += 2
                in_block_comment = False
            else:
                i += 1
            continue

        if in_string:
            result.append(ch)
            if ch == "\\":
                # Consume the escaped character verbatim (handles \" and \\)
                i += 1
                if i < n:
                    result.append(text[i])
                    i += 1
            elif ch == '"':
                in_string = False
                i += 1
            else:
                i += 1
            continue

        # Not in string, not in block comment
        if ch == '"':
            in_string = True
            result.append(ch)
            i += 1
        elif ch == "/" and i + 1 < n and text[i + 1] == "/":
            # Line comment: skip to end of line
            while i < n and text[i] != "\n":
                i += 1
        elif ch == "/" and i + 1 < n and text[i + 1] == "*":
            # Block comment start
            i += 2
            in_block_comment = True
        else:
            result.append(ch)
            i += 1

    stripped = "".join(result)
    # Remove trailing commas before ] or } (one pass is sufficient for well-formed JSONC)
    stripped = re.sub(r",\s*([\]}])", r"\1", stripped)
    return stripped


# ---------------------------------------------------------------------------
# Fatal error helper
# ---------------------------------------------------------------------------


def _fatal(msg: str) -> None:
    """Print an actionable error to stderr and exit(1)."""
    print(f"skills-mcp: configuration error: {msg}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Auth parsing helpers
# ---------------------------------------------------------------------------


def _parse_github_auth(raw: Any, registry_name: str) -> NoAuth | GithubTokenAuth | GhCliAuth:
    if raw is None or raw == {} or raw == {"type": "none"}:
        return NoAuth()
    if not isinstance(raw, dict):
        _fatal(f"registry '{registry_name}': auth must be a JSON object")
    auth_type = raw.get("type", "none")
    if auth_type == "none":
        return NoAuth()
    if auth_type == "github_token":
        env_var = raw.get("env_var", "")
        if not env_var or not isinstance(env_var, str):
            _fatal(
                f"registry '{registry_name}': auth.env_var must be a non-empty string "
                f"for type 'github_token'"
            )
        return GithubTokenAuth(env_var=env_var)
    if auth_type == "gh_cli":
        return GhCliAuth()
    _fatal(
        f"registry '{registry_name}': unknown auth type '{auth_type}'; "
        f"expected one of: none, github_token, gh_cli"
    )
    return NoAuth()  # unreachable; satisfies type checker


def _parse_http_auth(raw: Any, registry_name: str) -> NoAuth | BearerAuth | BasicAuth:
    if raw is None or raw == {} or raw == {"type": "none"}:
        return NoAuth()
    if not isinstance(raw, dict):
        _fatal(f"registry '{registry_name}': auth must be a JSON object")
    auth_type = raw.get("type", "none")
    if auth_type == "none":
        return NoAuth()
    if auth_type == "bearer":
        env_var = raw.get("env_var", "")
        if not env_var or not isinstance(env_var, str):
            _fatal(
                f"registry '{registry_name}': auth.env_var must be a non-empty string "
                f"for type 'bearer'"
            )
        return BearerAuth(env_var=env_var)
    if auth_type == "basic":
        user_var = raw.get("username_env_var", "")
        pass_var = raw.get("password_env_var", "")
        if not user_var or not isinstance(user_var, str):
            _fatal(
                f"registry '{registry_name}': auth.username_env_var must be a non-empty "
                f"string for type 'basic'"
            )
        if not pass_var or not isinstance(pass_var, str):
            _fatal(
                f"registry '{registry_name}': auth.password_env_var must be a non-empty "
                f"string for type 'basic'"
            )
        return BasicAuth(username_env_var=user_var, password_env_var=pass_var)
    _fatal(
        f"registry '{registry_name}': unknown auth type '{auth_type}'; "
        f"expected one of: none, bearer, basic"
    )
    return NoAuth()  # unreachable


# ---------------------------------------------------------------------------
# Registry parsing helpers
# ---------------------------------------------------------------------------


def _parse_github_registry(name: str, raw: dict[str, Any]) -> GithubRegistry:
    for required in ("owner", "repo", "ref"):
        if not raw.get(required):
            _fatal(f"registry '{name}': missing required field '{required}'")
    skills_dir = raw.get("skills_dir", "")
    if not isinstance(skills_dir, str):
        skills_dir = ""
    auth = _parse_github_auth(raw.get("auth"), name)
    cache_enabled = bool(raw.get("cache_enabled", True))
    raw_desc = raw.get("description")
    description = str(raw_desc) if isinstance(raw_desc, str) and raw_desc else None
    raw_instr = raw.get("instructions")
    instructions = str(raw_instr) if isinstance(raw_instr, str) and raw_instr else None
    return GithubRegistry(
        name=name,
        owner=str(raw["owner"]),
        repo=str(raw["repo"]),
        skills_dir=skills_dir,
        ref=str(raw["ref"]),
        auth=auth,
        cache_enabled=cache_enabled,
        description=description,
        instructions=instructions,
    )


def _parse_http_registry(name: str, raw: dict[str, Any]) -> HttpRegistry:
    for required in ("url", "skill_name"):
        if not raw.get(required):
            _fatal(f"registry '{name}': missing required field '{required}'")
    auth = _parse_http_auth(raw.get("auth"), name)
    cache_enabled = bool(raw.get("cache_enabled", True))
    raw_desc = raw.get("description")
    description = str(raw_desc) if isinstance(raw_desc, str) and raw_desc else None
    raw_instr = raw.get("instructions")
    instructions = str(raw_instr) if isinstance(raw_instr, str) and raw_instr else None
    return HttpRegistry(
        name=name,
        url=str(raw["url"]),
        skill_name=str(raw["skill_name"]),
        auth=auth,
        cache_enabled=cache_enabled,
        description=description,
        instructions=instructions,
    )


# ---------------------------------------------------------------------------
# Cache config parsing
# ---------------------------------------------------------------------------


def _parse_cache_config(raw: Any) -> CacheConfig:
    if raw is None:
        return CacheConfig()
    if not isinstance(raw, dict):
        _fatal("'cache' must be a JSON object")
    enabled = bool(raw.get("enabled", True))
    ttl = raw.get("ttl_seconds", 3600)
    if not isinstance(ttl, int) or ttl < 0:
        _fatal("cache.ttl_seconds must be a non-negative integer")
    cache_dir_raw = raw.get("dir")
    cache_dir = Path(cache_dir_raw).expanduser() if cache_dir_raw else CacheConfig().dir
    return CacheConfig(enabled=enabled, dir=cache_dir, ttl_seconds=int(ttl))


# ---------------------------------------------------------------------------
# Top-level loader
# ---------------------------------------------------------------------------


def load_config(config_path: Path | None = None) -> Config:
    """Load and validate skills-mcp config.jsonc.

    Resolves the path via: *config_path* arg → ``_default_config_path()``.
    Calls ``_fatal`` (sys.exit(1)) on any error.
    """
    if config_path is None:
        config_path = _default_config_path()

    try:
        raw_text = config_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        _fatal(f"config file not found: {config_path}")
        return Config(registries={})  # unreachable
    except OSError as exc:
        _fatal(f"cannot read config file {config_path}: {exc}")
        return Config(registries={})  # unreachable

    stripped = strip_jsonc(raw_text)

    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as exc:
        _fatal(f"invalid JSON in {config_path}: {exc}")
        return Config(registries={})  # unreachable

    if not isinstance(data, dict):
        _fatal(f"config file must be a JSON object, got {type(data).__name__}")

    # Parse registries
    raw_registries = data.get("registries", {})
    if not isinstance(raw_registries, dict):
        _fatal("'registries' must be a JSON object")

    registries: dict[str, RegistryVariant] = {}
    for reg_name, reg_raw in raw_registries.items():
        if not isinstance(reg_raw, dict):
            _fatal(f"registry '{reg_name}' must be a JSON object")
        reg_type = reg_raw.get("type")
        if reg_type == "github":
            registries[reg_name] = _parse_github_registry(reg_name, reg_raw)
        elif reg_type == "http":
            registries[reg_name] = _parse_http_registry(reg_name, reg_raw)
        else:
            _fatal(f"registry '{reg_name}': unknown type '{reg_type}'; expected 'github' or 'http'")

    cache = _parse_cache_config(data.get("cache"))
    return Config(registries=registries, cache=cache)
