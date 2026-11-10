"""Error taxonomy for skills-mcp.

Two contained paths:
- ModelRecoverableError subclasses  →  the agent can fix them; the server layer re-raises them
  as the MCP SDK's tool/resource errors so the message reaches the agent unchanged.
- RegistryUnavailableError  →  infra failure; caught at tool boundary, returned as error string.
"""


class ModelRecoverableError(ValueError):
    """Base for errors the calling agent can correct and retry."""


class RegistryNotFoundError(ModelRecoverableError):
    """The named registry does not exist in the configuration."""


class SkillNotFoundError(ModelRecoverableError):
    """The named skill does not exist in the registry."""


class SkillFileNotFoundError(ModelRecoverableError):
    """The requested file is not present in the skill's enumerated file tree."""


class PathTraversalError(ModelRecoverableError):
    """The requested file_path contains '..' or is absolute, escaping the skill root."""


class UnsupportedOperationError(ModelRecoverableError):
    """The operation is not supported by this registry type (e.g. get_skill_file on HTTP)."""


class RepositoryTargetError(ModelRecoverableError):
    """Repository path is missing, wrong-kind, unsupported, oversized, or non-text."""


class RegistryUnavailableError(Exception):
    """Infrastructure failure: HTTP error, timeout, rate limit, auth env-var missing.

    Not a ModelRecoverableError — caught at the tool boundary and returned as a plain error string.
    """
