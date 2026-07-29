## MODIFIED Requirements

### Requirement: MCP Tool Surface
The server SHALL expose exactly three MCP tools — `list_registries`, `list_skills`, and
`get_skill` — and one MCP resource template — `skill://{registry}/{+skill}{?file}` —
over a stdio transport using FastMCP. Each tool SHALL carry an explicit `description=`
parameter (not a docstring) as its only contract with the calling model.

#### Scenario: Tool list is stable
- **WHEN** an MCP client connects to the server
- **THEN** exactly three tools are advertised: `list_registries`, `list_skills`, `get_skill`

#### Scenario: Resource template is advertised
- **WHEN** an MCP client calls `list_resource_templates`
- **THEN** exactly one template is returned with URI pattern `skill://{registry}/{+skill}{?file}`

### Requirement: List Registries Tool
`list_registries()` SHALL return a list of objects, one per configured registry, each
containing `name` (string), `type` (`"github"` or `"http"`), optionally `ref`
(the configured ref for GitHub registries; absent for HTTP), and optionally `description`
(a human-readable string describing the registry's purpose; absent when not configured
in config). The operation requires no I/O and SHALL never fail with an error.

#### Scenario: Returns all configured registries
- **WHEN** `list_registries` is called with two configured registries (one GitHub, one HTTP)
- **THEN** both appear in the result with their name, type, and ref (GitHub) or no ref (HTTP)

#### Scenario: Returns empty list when no registries configured
- **WHEN** `list_registries` is called with an empty registry config
- **THEN** the result is an empty list

#### Scenario: Returns description when configured
- **WHEN** a registry is configured with `description: "Clark engineering skills"`
- **THEN** the `description` field appears in the `list_registries` result for that registry

#### Scenario: Description absent when not configured
- **WHEN** a registry is configured without a `description` field
- **THEN** the result object for that registry contains no `description` key

### Requirement: Get Skill Tool
`get_skill(registry: str, skill: str, file: str | None = None)` SHALL behave as follows:
— When `file` is absent (default): return a JSON object with `content` (the full SKILL.md
text) and `files` (a sorted list of companion file paths relative to the skill root,
excluding `SKILL.md` itself). For HTTP registries `files` SHALL be an empty list.
— When `file` is present: URL-decode the value (`urllib.parse.unquote`) and return the
named companion file's raw text directly (not wrapped in a JSON envelope). This path
SHALL route directly to `fetch_file` with no prior `fetch_skill` call. Security validation
(path traversal check, membership in the skill's file tree) SHALL apply identically to
the removed `get_skill_file` behaviour. For HTTP registries, calling with `file` present
SHALL raise an `UnsupportedOperationError` (`ValueError`).

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

#### Scenario: HTTP registry with file raises error
- **WHEN** `get_skill` is called with `file` present for an HTTP registry
- **THEN** the tool returns an `is_error=True` result describing the operation as unsupported

#### Scenario: Missing skill raises error
- **WHEN** `get_skill` is called for a skill that does not exist in the registry
- **THEN** the tool returns an `is_error=True` result (a `SkillNotFoundError` is raised)

#### Scenario: Path traversal in file is rejected
- **WHEN** `get_skill` is called with a `file` value containing `..` segments
- **THEN** the tool returns an `is_error=True` result (a `PathTraversalError` is raised) and no upstream fetch is attempted

## REMOVED Requirements

### Requirement: Get Skill File Tool
**Reason**: Consolidated into `get_skill(registry, skill, file=...)`. A separate tool required
two round-trips to read a companion file (first `get_skill` for the file list, then
`get_skill_file` for the content); the optional `file` parameter eliminates the extra hop.
**Migration**: Replace `get_skill_file(registry, skill, file_path)` with
`get_skill(registry, skill, file=file_path)`. The return value is unchanged — raw text.

## ADDED Requirements

### Requirement: MCP Resource Surface
The server SHALL expose a single MCP resource template `skill://{registry}/{+skill}{?file}`
allowing clients to access skills and companion files by URI via `read_resource`, without
calling a tool. The `{+skill}` placeholder preserves slashes (e.g.
`engineering/testing/tdd-development`); `{?file}` is an optional query parameter carrying
a URL-encoded companion file path (e.g. `?file=references%2Fguide.md`).
— When `file` is absent: the resource handler SHALL return the raw SKILL.md text.
— When `file` is present: the handler SHALL URL-decode the value and return the companion
file's raw text.
In both cases, resources return raw text (not JSON envelopes). The resource template SHALL
be discoverable via `list_resource_templates`; `list_resources` SHALL remain empty.
`RegistryUnavailableError` SHALL be caught at the resource boundary and re-raised as a
`ValueError` so FastMCP surfaces it as an error content item rather than a protocol crash.
All other `ValueError` subclasses (e.g. `SkillNotFoundError`, `PathTraversalError`) propagate
naturally and are surfaced as error content items.

#### Scenario: Reads SKILL.md via URI
- **WHEN** `read_resource` is called with URI `skill://clark-skills/engineering/testing/tdd-development`
- **THEN** the raw SKILL.md text for that skill is returned as the resource content

#### Scenario: Reads companion file via URI with file query param
- **WHEN** `read_resource` is called with URI `skill://my-registry/my-skill?file=references%2Fguide.md`
- **THEN** the raw text of `references/guide.md` within `my-skill` is returned

#### Scenario: Resource template is discoverable
- **WHEN** `list_resource_templates` is called
- **THEN** exactly one template is returned with the URI pattern `skill://{registry}/{+skill}{?file}`

#### Scenario: Unknown registry produces error content item
- **WHEN** `read_resource` is called with an unknown registry in the URI
- **THEN** an error content item is returned and the server continues serving

#### Scenario: Registry infrastructure failure produces error content item
- **WHEN** `read_resource` is called and the registry is temporarily unreachable
- **THEN** `RegistryUnavailableError` is caught at the resource boundary, re-raised as `ValueError`, and an error content item is returned without crashing the server
