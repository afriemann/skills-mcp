## Why

`list_registries` was the bootstrap discovery tool, but the config-assembled
`list_skills` description already enumerates every configured registry by name
(regardless of whether `description` or `instructions` are set). Agents can go
straight to `list_skills` without a prior round-trip, making `list_registries`
redundant as an agent-facing tool.

## What Changes

- **BREAKING**: Remove the `list_registries` MCP tool from the server surface
- Move the registry enumeration (currently in `list_registries`'s description) to
  `list_skills`'s description instead
- Rename `_build_list_registries_description` → `_build_list_skills_description`;
  update its static intro text to match `list_skills`
- Remove `Dispatcher.list_registries()` method and the `descriptions` dict wired
  through lifespan (no callers remain once the tool is gone)
- Update tests to reflect the removed tool and renamed helper

## Capabilities

### New Capabilities

_(none)_

### Modified Capabilities

- `skills-mcp`: MCP tool surface changes from three tools to two; `list_skills`
  description is now config-assembled
- `registry-instructions`: `Config-Assembled Description` requirement retargeted
  from `list_registries` to `list_skills`; function renamed

## Impact

- `src/skills_mcp/server.py` — remove `list_registries` tool; rename helper; update `list_skills` registration
- `src/skills_mcp/dispatch.py` — remove `list_registries()` method and `descriptions` parameter
- `tests/test_integration.py` — remove `list_registries` tool call tests; add `list_skills` description test
- `tests/test_registry_instructions.py` — update import and function name references
- MCP clients that call `list_registries` will receive an "unknown tool" error after upgrade
