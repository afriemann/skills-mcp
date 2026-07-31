# Design: registry `instructions` field

## Context

Agents connected to `skills-mcp` don't know which registry to query until they
call `list_skills`, costing a discovery round-trip. `list_registries` is the
spec-designated "call first" tool, and its description string is surfaced to the
agent at startup. This change lets each registry carry optional proactive-call
guidance (`instructions`) that the server folds into that description — so the
right call sequence is visible without a separate instruction file.

The work is mechanical (a new optional config field plus a description-assembly
helper). Only one decision is worth recording; the rest follows existing
patterns (`description`).

## The one decision: where the dynamic text comes from, and where it lands

```
operator config (per-registry `instructions`)
        │  parsed in loader.py (1:1 clone of `description`)
        ▼
Config.registries[*].instructions: str | None
        │  read at build_app() time
        ▼
_build_list_registries_description(cfg) -> str   ← pure, module-level
        │  passed as description=
        ▼
list_registries tool description  →  agent system prompt at startup
```

`_build_list_registries_description(cfg)` starts from the current static intro,
then appends one line per configured registry: name, `description` (if set), and
`instructions` (if set). A registry with no `instructions` is listed with no
call-to-action. The assembled string is fixed for the server's lifetime — a
config change requires a restart, which is acceptable for operator-owned config.

## Why these choices

**`list_registries`, not `list_skills`.** The guidance is discovery guidance —
"which registry, and when to call `list_skills` on it." `list_registries` is the
tool the spec designates agents call first, and its description reaches the agent
before any skill call. Attaching the text to `list_skills` would surface it only
after the agent already found the registry, defeating the purpose. `list_skills`
stays static.

**Per-registry, not a server-level `instructions`.** The text is inherently
registry-specific — e.g. *"call `list_skills('clark-skills')` when the task
touches Clark infra."* A single server-level blob could not name the registry it
refers to and would grow unmaintainable as registries are added or removed.
Keeping it on the registry dataclass co-locates the guidance with the thing it
describes and mirrors the existing `description` field exactly.

**Trust boundary.** `instructions` is operator-supplied config, never
agent-supplied. It is read from the same trusted config file as every other
registry field and flows one way (config → tool description). No tool input can
set or alter it. This matches the existing allow-list trust model — an agent can
read the assembled description but cannot influence its content.

**Testable seam.** `_build_list_registries_description` is a pure module-level
function: `Config` in, `str` out, no FastMCP objects, no I/O. It is registered as
`description=` at `build_app()` runtime (where `cfg` is already in the closure),
so the assembly rule is exercised directly in unit tests without touching FastMCP
internals. Tests pin the *rule* (ordering, inclusion/omission of optional fields)
rather than exact prose.

## Component breakdown

- **Config field** — add `instructions: str | None = None` to `GithubRegistry`
  and `HttpRegistry` in `config/model.py`. *Done:* both dataclasses carry the
  field, defaulting to `None`; frozen-dataclass invariant preserved.
- **Config parsing** — parse `instructions` in the GitHub and HTTP registry
  parsers in `config/loader.py`, cloning the `description` idiom
  (`str(v) if isinstance(v, str) and v else None`). *Done:* a config with and
  without `instructions` parses to the expected `str`/`None`.
- **Description helper** — extract `_build_list_registries_description(cfg)` at
  module level in `server.py`; register `list_registries` with its result.
  *Done:* pure function assembles intro + per-registry lines; optional fields
  included only when set; `list_skills` description unchanged.
- **Tests** — unit-test the helper directly (empty registries, `description`
  only, `instructions` only, both) and config parsing of `instructions`.
  *Done:* rule-level assertions pass with no FastMCP internals imported.

## Out of scope

Hot-reload of the description on config change (restart is sufficient); any
change to `list_skills` or `get_skill`; changing the `list_registries` output
JSON (only the tool *description* string changes, not the returned array).
