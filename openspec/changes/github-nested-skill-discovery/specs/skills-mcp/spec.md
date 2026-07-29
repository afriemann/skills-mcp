## MODIFIED Requirements

### Requirement: List Skills Tool
`list_skills(registry: str)` SHALL return a list of skill identifier strings available in
the named registry. For GitHub registries it discovers skills at any nesting depth within
`skills_dir` by performing a recursive Git Trees walk; each skill is identified by its
slash-delimited path relative to `skills_dir` (e.g. `engineering/testing/tdd-development`
for a skill at `skills_dir/engineering/testing/tdd-development/SKILL.md`). A directory is
a skill if and only if it contains a `SKILL.md` file; subdirectories that contain no
`SKILL.md` are not returned. Skills whose `SKILL.md` sits directly at the root of
`skills_dir` (rather than in a subdirectory) are excluded — skill names are always
non-empty subdirectory paths. When one skill's directory is an ancestor of another skill's
directory (i.e. a `SKILL.md` is bundled inside a companion-file subtree), only the
shallowest skill is returned; the deeper path is treated as a companion file, not a skill.
For HTTP registries it returns a single-element list containing the declared `skill_name`.
Names only are returned — no descriptions, no metadata — to avoid N+1 upstream API calls.

#### Scenario: Lists GitHub registry skills (flat layout)
- **WHEN** `list_skills` is called for a GitHub registry whose `skills_dir` contains two direct
  skill subdirectories `skill-a` and `skill-b`, each with a `SKILL.md`
- **THEN** the result is `["skill-a", "skill-b"]`

#### Scenario: Lists GitHub registry skills (nested layout)
- **WHEN** `list_skills` is called for a GitHub registry whose `skills_dir` contains skills
  at `engineering/testing/tdd-development/SKILL.md` and `business/brainstorming/SKILL.md`
- **THEN** the result is `["business/brainstorming", "engineering/testing/tdd-development"]`

#### Scenario: Non-skill subdirectories are excluded
- **WHEN** `list_skills` is called for a GitHub registry whose `skills_dir` contains a
  subdirectory that has no `SKILL.md` (only other files)
- **THEN** that subdirectory does not appear in the result

#### Scenario: Bundled SKILL.md is not a phantom skill
- **WHEN** a skill at `my-skill/SKILL.md` also ships `my-skill/references/example/SKILL.md`
  as a companion file
- **THEN** `list_skills` returns only `["my-skill"]` — the deeper path is not a separate skill

#### Scenario: Lists HTTP registry skill
- **WHEN** `list_skills` is called for an HTTP registry declared with `skill_name = "my-skill"`
- **THEN** the result is `["my-skill"]`

#### Scenario: Unknown registry raises error
- **WHEN** `list_skills` is called with a registry name that does not exist in the config
- **THEN** the tool returns an `is_error=True` result (a `ValueError` is raised)

### Requirement: GitHub Registry Adapter
The GitHub adapter SHALL fetch skill content from a multi-skill GitHub repository locked
to a configured `ref` (branch, tag, or full/abbreviated commit SHA). Skills may be
organised at any nesting depth within `skills_dir`; each skill is identified by its
slash-delimited path relative to `skills_dir`. The adapter SHALL discover skills by
resolving the tree SHA of `skills_dir` (via the GitHub Contents API on its parent
directory), then performing a single recursive Git Trees walk of that subtree; any blob
whose path ends with `/SKILL.md` (relative to `skills_dir`) is a skill. The adapter SHALL
fetch individual file contents via the Git Blobs API with
`Accept: application/vnd.github.raw` (supporting files larger than 1 MB). The adapter
SHALL validate agent-supplied `skill` path values before use, rejecting empty, absolute,
and `..`-escaping paths with a `PathTraversalError`. When a `list_skills` result may be
truncated by the GitHub API's recursive-tree limit, the server SHALL log a warning to
stderr indicating that skills (not just companion files) may be missing.

#### Scenario: Lists skill subdirectories from GitHub (flat)
- **WHEN** `list_skills` is called for a GitHub registry with a flat `skills_dir`
- **THEN** the adapter resolves the tree SHA of `skills_dir`, performs one recursive Trees
  walk, and returns the direct subdirectory names that contain `SKILL.md`

#### Scenario: Lists skill subdirectories from GitHub (nested)
- **WHEN** `list_skills` is called for a GitHub registry whose `skills_dir` has skills
  nested multiple levels deep
- **THEN** the adapter returns slash-delimited relative paths for all discovered skills

#### Scenario: Fetches SKILL.md via raw blob (flat skill)
- **WHEN** `get_skill` is called for a flat GitHub skill
- **THEN** the adapter resolves the skill's tree SHA via Contents-on-parent, uses the
  recursive Trees API to locate `SKILL.md`, and fetches it via the Blobs API

#### Scenario: Fetches SKILL.md via raw blob (nested skill)
- **WHEN** `get_skill` is called with a slash-delimited skill name such as
  `engineering/testing/tdd-development`
- **THEN** the adapter resolves the tree SHA for that nested directory and fetches `SKILL.md`

#### Scenario: Rejects traversal in skill name
- **WHEN** `get_skill` or `get_skill_file` is called with a `skill` value containing `..`
  segments (e.g. `../secrets`)
- **THEN** the tool returns an `is_error=True` result (a `PathTraversalError` is raised)
  and no upstream API call is made

#### Scenario: Fetches file larger than 1 MB
- **WHEN** `get_skill_file` is called for a companion file whose size exceeds 1 MB
- **THEN** the adapter successfully returns its content via the Blobs raw endpoint
