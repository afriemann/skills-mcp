"""Error taxonomy for skills-mcp.

Two contained paths (per mcp-server-dev skill):
- ValueError subclasses  →  model-recoverable; FastMCP marks is_error=True.
- RegistryUnavailableError  →  infra failure; caught at tool boundary, returned as error string.
"""


class RegistryNotFoundError(ValueError):
    """The named registry does not exist in the configuration."""


class SkillNotFoundError(ValueError):
    """The named skill does not exist in the registry."""


class SkillFileNotFoundError(ValueError):
    """The requested file is not present in the skill's enumerated file tree."""


class PathTraversalError(ValueError):
    """The requested file_path contains '..' or is absolute, escaping the skill root."""


class UnsupportedOperationError(ValueError):
    """The operation is not supported by this registry type (e.g. get_skill_file on HTTP)."""


class RegistryUnavailableError(Exception):
    """Infrastructure failure: HTTP error, timeout, rate limit, auth env-var missing.

    Not a ValueError — caught at the tool boundary and returned as a plain error string.
    """
