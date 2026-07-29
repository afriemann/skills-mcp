## Why

The server exposes `get_skill_file` as a separate tool, requiring two round-trips to read a skill's companion file: first `get_skill` to discover available files, then `get_skill_file` to fetch one. The aws-mcp server's `retrieve_skill` consolidates both into a single tool call with an optional `file` parameter — removing the extra hop. Additionally, skills are not accessible as MCP resources, limiting clients that prefer URI-based context injection (e.g. `read_mcp_resource` in opencode). Registry descriptions are also absent from `list_registries` output, forcing agents to explore a registry to understand its purpose.

## What Changes

- **MODIFIED**: `get_skill(registry, skill, file=None)` gains an optional `file` parameter. When absent: returns `{content, files}` as today. When present: returns the named companion file's **raw text** directly (not wrapped in a JSON envelope) — the same shape `get_skill_file` returns today, so migration is a parameter rename. The `file` value must be URL-decoded before use (`urllib.parse.unquote`); callers constructing a `skill://` URI encode slashes as `%2F`. When `file` is provided the call routes **directly** to `fetch_file` — no prior `fetch_skill` pre-call.
- **REMOVED (BREAKING)**: `get_skill_file` MCP tool is removed. No deprecation window; migration is trivial — replace `get_skill_file(r, s, f)` with `get_skill(r, s, file=f)`. There is no prior public API commitment; the server is early-stage.
- **ADDED**: MCP resource template `skill://{registry}/{+skill}{?file}` — `read_mcp_resource` works on any skill or companion file by URI. Discovered via `list_resource_templates` (not `list_resources`, which remains empty). Resources return raw text (not JSON). Errors use the same `ValueError`-subclass taxonomy as tools, surfaced as error content items.
- **ADDED**: Optional `description: str | None` field on each registry dataclass (`GithubRegistryConfig`, `HttpRegistryConfig`) independently. When set, included in `list_registries` output so agents understand each registry's purpose without exploring it.
- **MODIFIED**: All tool descriptions updated to be richer and more actionable (aws-mcp style), noting `list_resource_templates` as the discovery path for the `skill://` scheme.

## Capabilities

### New Capabilities

_None — no new capability spec files needed._

### Modified Capabilities

- `skills-mcp`: MCP tool surface changes (4 tools → 3), `get_skill` gains `file` param, `get_skill_file` removed, resource template added, `list_registries` gains optional `description` per registry, config model gains optional `description` field.

## Impact

- **Breaking**: `get_skill_file` tool removed. Callers migrate to `get_skill(..., file=...)`.
- **Tool count**: 4 → 3 (`list_registries`, `list_skills`, `get_skill`).
- **New resource surface**: `skill://` URI scheme; `list_resources` returns empty, `list_resource_templates` advertises the template, `read_resource` works for any well-formed `skill://` URI.
- **Code**: `server.py` (tool registration, resource template, URL-decode), `dispatch.py` (`get_skill` absorbs `get_skill_file`; docstring count updated), `config/model.py` (optional `description` field on both registry dataclasses), `tests/test_integration.py` (migrate 5 `get_skill_file` tests, add resource and `description` tests), `tests/test_adapters.py` (scenario annotation update), `README.md` (tools table, opencode permission names, description config example).
- **No new dependencies**: FastMCP resource template support is already in `mcp[cli]>=1.0.0`.
