## Why

`list_skills` currently returns bare skill names — no descriptions, no metadata. An agent
calling `list_skills` has to follow up with N `get_skill` calls just to know which skill
is relevant to its task. Adding SKILL.md frontmatter (description, tags) to the listing
removes that N+1 round-trip and makes skill discovery useful by itself.

## What Changes

- **BREAKING** `list_skills(registry)` return type changes from `list[str]` (names only) to
  `list[dict]` containing `name`, `description`, and `tags` parsed from each skill's SKILL.md
  frontmatter.
- A persistent **skill index** is maintained in the disk cache: only new skills (not yet in
  the index) have their SKILL.md fetched; deleted skills are retired from the index on the
  next listing call. The index is stored alongside the existing skills-list cache entry.
- `list_skills` gains a `refresh_cache` boolean parameter (default `False`). When `True` the
  index is rebuilt from scratch (all skills re-fetched) bypassing the cached name list too.
- `get_skill` gains a matching `refresh_cache` boolean parameter (default `False`) that
  forces a fresh upstream fetch for that individual skill, bypassing its per-skill cache
  entry.
- A new `frontmatter.py` module provides a small inline YAML-frontmatter parser (no new
  dependency); returns an empty dict gracefully for skills with no frontmatter.

## Capabilities

### New Capabilities
- `skill-index`: Persistent skill index stored in the disk cache, mapping skill names to
  their parsed frontmatter. Incrementally updated on each `list_skills` call.
- `frontmatter-parsing`: Parse YAML frontmatter from SKILL.md content into a dict of
  `name`, `description`, and `tags` fields. Handles missing or malformed frontmatter
  gracefully.

### Modified Capabilities
- `skills-mcp`: `list_skills` return type changes (BREAKING); both `list_skills` and
  `get_skill` gain `refresh_cache` parameter; cache layer extended with skill index.

## Impact

- `src/skills_mcp/frontmatter.py` — new module
- `src/skills_mcp/cache.py` — new `_SKILL_INDEX_FILE` constant; `DiskCache` unchanged (reuses existing put/get)
- `src/skills_mcp/registries/__init__.py` — `CachingRegistry` gains `list_skills_metadata` and `fetch_skill` gains `refresh` param
- `src/skills_mcp/dispatch.py` — new `list_skills_metadata` method; `get_skill` gains `refresh` param
- `src/skills_mcp/server.py` — `list_skills` tool rewritten; `get_skill` gains `refresh_cache` param
- `tests/` — new unit tests for frontmatter parser and index behaviour; updated integration tests
- No new external dependencies
- Wire-format breaking change: `list_skills` callers that expect `list[str]` must update to `list[dict]`
