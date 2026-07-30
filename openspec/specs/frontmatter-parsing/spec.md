# frontmatter-parsing Specification

## Purpose
TBD - created by archiving change skill-listing-frontmatter-index. Update Purpose after archive.
## Requirements
### Requirement: Frontmatter Parsing
The server SHALL provide a `parse_frontmatter(content: str) -> dict[str, object]` function
in a dedicated `frontmatter.py` module. The function SHALL parse the leading YAML-style
frontmatter block (delimited by `---` fences) from a SKILL.md string and return a dict of
the top-level keys found within it.

The function SHALL handle the following subset of YAML, and SHALL silently skip or return
partial results for anything outside this subset — it SHALL never raise an exception:
- Top-level `key: value` pairs where the value is a scalar string (including single-quoted
  and double-quoted scalars; an escaped `''` inside a single-quoted scalar is honoured).
- Block list values: a `key:` with an empty right-hand side followed by one or more
  indented `  - item` lines; items are collected into a `list[str]`.
- Full-line comments (`#` as the first non-space character) are skipped.
- Nested mapping keys (indented `k: v` children under a top-level key) are skipped
  entirely; inline `#` mid-value is NOT stripped (non-goal, not YAML comment semantics).

The `name` key in the frontmatter is captured but SHALL NOT overwrite the skill identifier
in the listing — callers are responsible for applying the identifier-wins rule per the
Skill Index requirement.

The function SHALL have no imports from other project modules (it is dependency-free beyond
the Python standard library), and SHALL require no new external dependencies.

#### Scenario: Parses description and tags from typical frontmatter
- **WHEN** `parse_frontmatter` is called with a SKILL.md that has `description:` (quoted) and a `tags:` block list
- **THEN** the returned dict contains `description` as a string and `tags` as a list of strings

#### Scenario: Returns empty dict for content with no frontmatter fence
- **WHEN** `parse_frontmatter` is called with a string that does not start with `---`
- **THEN** the result is `{}`

#### Scenario: Returns partial dict for malformed frontmatter
- **WHEN** `parse_frontmatter` is called with a frontmatter block that is partially valid
- **THEN** the result contains the successfully-parsed keys and omits malformed entries; no exception is raised

#### Scenario: Preserves colon and hash inside quoted scalar
- **WHEN** a frontmatter value is `'Use ALWAYS when interacting: git # important'`
- **THEN** the parsed value is the full string including the colon and hash character

#### Scenario: Honoured escaped single quote inside single-quoted scalar
- **WHEN** a frontmatter value is `'don''t skip this'` (YAML single-quote escape)
- **THEN** the parsed value is `don't skip this`

#### Scenario: Skips nested mapping keys
- **WHEN** the frontmatter contains a `metadata:` key with indented child `k: v` pairs
- **THEN** the `metadata` key is absent from the result and no exception is raised

#### Scenario: Never raises on any input
- **WHEN** `parse_frontmatter` is called with arbitrary or empty string content
- **THEN** the function returns a dict (possibly empty) and never raises an exception
