## Why

The skill-index test suite uses only flat skill names (`"skill-a"`, `"skill-b"`); a
regression in nested-path (slash-containing) identifier handling would be invisible to
CI. Given that real registries already use nested paths (e.g.
`quality/reviewing/code-review`), this gap needs to be closed with targeted regression tests.

## What Changes

- Add 3 new test scenarios to `tests/test_skill_index.py` covering:
  - Slash-containing identifier preserved verbatim on cold cache (first call)
  - Slash-containing identifier preserved verbatim from warm index (second call)
  - Stale flat identifier retired when the registry renames the skill to a nested path

No production code changes.

## Capabilities

### New Capabilities

_(none — test-only change)_

### Modified Capabilities

- `skill-index`: add three scenarios documenting that slash-containing skill identifiers
  are preserved verbatim throughout the index lifecycle (cold, warm, and stale-name-retirement)

## Impact

- `tests/test_skill_index.py` — three new test functions
- `openspec/specs/skill-index/spec.md` — three new scenarios appended to the existing requirement
- No production code, dependencies, or APIs affected
