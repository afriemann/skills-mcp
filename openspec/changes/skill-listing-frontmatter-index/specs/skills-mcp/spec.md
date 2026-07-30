## MODIFIED Requirements

### Requirement: List Skills Tool
`list_skills(registry: str, refresh_cache: bool = False)` SHALL return a JSON array of
objects, one per skill available in the named registry. Each object SHALL contain at minimum
`name` (the skill identifier string — the value an agent passes to `get_skill`). When the
skill's SKILL.md contains a parseable frontmatter block, the object SHALL also contain any
top-level scalar or string-list fields found there (e.g. `description`, `tags`); the `name`
key in the result is always the skill identifier, not the frontmatter `name:` field.
A skill whose SKILL.md cannot be fetched at index-build time SHALL still appear in the
result as a name-only object (`{"name": "<identifier>"}`), preserving discoverability.

The N+1 upstream-call cost is avoided by the cached skill index (see Skill Index
capability): only skills absent from the index incur a fetch; warm-index calls perform no
upstream I/O beyond the names-list cache read. The discovery rules for skill identifiers are
unchanged: GitHub registries walk the recursive tree of `skills_dir`; HTTP registries return
a single-element list containing the declared `skill_name`; pruning and nesting rules are
unchanged.

When `refresh_cache` is `True` the names-list cache and the skill index are both bypassed:
skills are re-discovered upstream and all SKILL.md blobs are re-fetched, rebuilding the
index from scratch. The refreshed names list and index SHALL be written back to cache.

Unknown registry SHALL raise an error (`is_error=True`). Registry-unreachable SHALL return
an error string result (per the existing error-classification requirement).

#### Scenario: Returns object list with frontmatter fields
- **WHEN** `list_skills` is called for a registry whose skills have frontmatter `description` and `tags`
- **THEN** the result is a JSON array of objects each containing `name`, `description`, and `tags`

#### Scenario: Returns name-only object when SKILL.md cannot be fetched
- **WHEN** `list_skills` is called and one skill's SKILL.md is temporarily unreachable
- **THEN** the result still includes that skill as `{"name": "<identifier>"}` and the other skills appear normally

#### Scenario: Returns object list for HTTP registry
- **WHEN** `list_skills` is called for an HTTP registry
- **THEN** the result is a single-element array containing an object with at least `name`

#### Scenario: refresh_cache rebuilds the index from scratch
- **WHEN** `list_skills` is called with `refresh_cache=True`
- **THEN** the names list and all SKILL.md blobs are re-fetched upstream and the skill index is fully rebuilt

#### Scenario: Warm-index call incurs no upstream blob fetch
- **WHEN** `list_skills` is called a second time for the same registry (index already populated)
- **THEN** no SKILL.md blob fetch is made upstream; the cached index is returned

#### Scenario: Skill identifier is always authoritative for name
- **WHEN** a SKILL.md's frontmatter `name:` field differs from its directory-path identifier
- **THEN** the `name` key in the result object is the directory-path identifier, not the frontmatter value

#### Scenario: Unknown registry raises error
- **WHEN** `list_skills` is called with a registry name that does not exist in the config
- **THEN** the tool returns an `is_error=True` result

### Requirement: Get Skill Tool
`get_skill` SHALL accept `registry`, `skill`, optional `file`, and optional
`refresh_cache: bool = False` and behave as follows:
— When `file` is absent (default): return a JSON object with `content` (the full SKILL.md
text) and `files` (a sorted list of companion file paths relative to the skill root,
excluding `SKILL.md` itself). For HTTP registries `files` SHALL be an empty list.
When `refresh_cache` is `True` and `file` is absent, the SKILL.md SHALL be re-fetched
from upstream, bypassing the per-skill cache entry; the fresh result SHALL be written back
to the per-skill cache, replacing the stale entry.
— When `file` is present: URL-decode the value (`urllib.parse.unquote`) and return the
named companion file's raw text directly (not wrapped in a JSON envelope). This path
SHALL route directly to `fetch_file` with no prior `fetch_skill` call. `refresh_cache`
has no effect when `file` is present.
Security validation (path traversal check, membership in the skill's file tree) SHALL apply
identically. For HTTP registries, calling with `file` present SHALL raise an
`UnsupportedOperationError` (`ValueError`).

#### Scenario: Returns SKILL.md content and companion files from GitHub
- **WHEN** `get_skill` is called without `file` for a GitHub registry skill that contains `SKILL.md` and a `references/guide.md` companion file
- **THEN** `content` contains the full SKILL.md text and `files` contains `["references/guide.md"]`

#### Scenario: Returns SKILL.md content from HTTP registry
- **WHEN** `get_skill` is called without `file` for an HTTP registry
- **THEN** `content` contains the fetched text and `files` is an empty list

#### Scenario: Returns companion file raw text when file is provided
- **WHEN** `get_skill` is called with `file="references/guide.md"` for a valid GitHub skill
- **THEN** the raw text of that companion file is returned directly (not wrapped in a JSON envelope)

#### Scenario: Percent-encoded slashes in file query param are decoded
- **WHEN** `get_skill` is called with `file="references%2Fguide.md"` (percent-encoded slash)
- **THEN** the handler decodes it to `references/guide.md` before dispatch and the correct file content is returned

#### Scenario: refresh_cache bypasses cache and writes back
- **WHEN** `get_skill` is called with `refresh_cache=True` and no `file`
- **THEN** the SKILL.md is re-fetched upstream and the per-skill cache entry is replaced with the fresh content

#### Scenario: refresh_cache ignored when file is present
- **WHEN** `get_skill` is called with `refresh_cache=True` and `file="references/guide.md"`
- **THEN** the companion file is fetched via the normal `fetch_file` path (no special refresh behaviour)

#### Scenario: HTTP registry with file raises error
- **WHEN** `get_skill` is called with `file` present for an HTTP registry
- **THEN** the tool returns an `is_error=True` result describing the operation as unsupported

#### Scenario: Missing skill raises error
- **WHEN** `get_skill` is called for a skill that does not exist in the registry
- **THEN** the tool returns an `is_error=True` result (a `SkillNotFoundError` is raised)

#### Scenario: Path traversal in file is rejected
- **WHEN** `get_skill` is called with a `file` value containing `..` segments
- **THEN** the tool returns an `is_error=True` result (a `PathTraversalError` is raised) and no upstream fetch is attempted
