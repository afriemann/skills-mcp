## Why

The `GithubAdapter` discovers skills by listing the immediate subdirectories of `skills_dir`,
which assumes every skill sits at exactly one level deep (e.g. `skills/my-skill/SKILL.md`).
Repositories that organise skills into category subdirectories — such as
`skills/engineering/testing/tdd-development/SKILL.md` — return category folders as skill names
instead of actual skills, making `list_skills` useless and `get_skill` / `get_skill_file`
unreachable for any nested skill.

## What Changes

- `list_skills` for GitHub registries switches from a one-level Contents API scan to a
  recursive Git Trees walk of `skills_dir`, discovering skills at any nesting depth.
- Skill names for nested skills become slash-delimited relative paths from `skills_dir`
  (e.g. `engineering/testing/tdd-development`). Flat repos are unaffected — a skill at
  `skills/my-skill/SKILL.md` still returns `my-skill`.
- `fetch_skill` and `fetch_file` accept the slash-delimited name and navigate to the correct
  directory before fetching content.

## Capabilities

### New Capabilities

_(none)_

### Modified Capabilities

- `skills-mcp`: `list_skills` behaviour for GitHub registries changes; `get_skill` and
  `get_skill_file` now accept slash-delimited skill names for nested layouts.

## Impact

- **`src/skills_mcp/registries/github.py`** — `list_skills`, `fetch_skill`, `fetch_file`,
  plus a new `_get_tree_sha_for_dir` helper.
- **Tests** — existing GitHub adapter tests updated; new scenarios for nested and mixed
  (flat + nested) layouts added.
- **No breaking change for flat repos** — skill names for single-level layouts are
  identical to today.
- **No config, cache, or HTTP adapter changes.**
