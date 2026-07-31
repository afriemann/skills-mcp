## Why

Agents connected to skills-mcp must call `list_skills` before they know any
skills exist, adding an unnecessary discovery round-trip. `list_registries` is
the spec-designated "call first" discovery tool and its description is
automatically injected into the agent's system prompt at startup. By letting
each registry declare optional proactive-call guidance via an `instructions`
field in the config, the server can assemble that guidance into the
`list_registries` description — making the right call sequence visible to
agents without any additional instruction file.

## What Changes

**(a) Config field (mechanical):** `GithubRegistry` and `HttpRegistry` gain an
optional `instructions: str | None` field, defaulting to `None`. Parsing follows
the identical pattern already used for `description`.

**(b) Dynamic description assembly:** The `list_registries` tool description is
built dynamically at `build_app()` time from the loaded config. It lists each
configured registry (name, description, and instructions if set). Registries
with no `instructions` are listed without a call-to-action. A pure helper
function `_build_list_registries_description(cfg)` is extracted as the
testable seam; the `list_skills` description remains static. The assembly rule
(not the text) is what gets specified and tested.

The assembled description is static for the server's lifetime — a config change
requires a server restart.

## Capabilities

### New Capabilities
- `registry-instructions`: Optional per-registry `instructions` field in config
  and the assembly rule that incorporates it into the `list_registries` tool
  description.

### Modified Capabilities
<!-- none — list_registries tool surface (name, inputs, output) is unchanged;
     only the description string is config-assembled. The existing spec does not
     govern description *content*, so this is new behaviour, not a modification. -->

## Impact

- `src/skills_mcp/config/model.py` — `instructions: str | None = None` on both registry dataclasses
- `src/skills_mcp/config/loader.py` — `instructions` parsed in `_parse_github_registry` and `_parse_http_registry` (same pattern as `description`)
- `src/skills_mcp/server.py` — `_build_list_registries_description(cfg)` pure helper; `list_registries` tool registered with its result
- `~/.config/skills-mcp/config.jsonc` — operator adds `instructions` text to desired registries (user action, not committed here)
- Tests: unit tests for `_build_list_registries_description` (pure function, no FastMCP internals) and for config parsing of `instructions`
- No breaking changes; `instructions` is optional and defaults to `None`
- Trust boundary: `instructions` is operator-supplied config text, not agent-supplied — consistent with the allow-list trust model
