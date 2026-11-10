# Spec Delta

## MODIFIED Requirements

### Requirement: MCP Tool Surface
The server SHALL expose exactly five MCP tools — `list_skills`, `get_skill`,
`get_registry_source`, `list_repo_entries` and `read_repo_text_file` —
and one MCP resource template — `skill://{registry}/{+skill}{?file}` — over a
stdio transport. Each tool SHALL carry an explicit `description=`
parameter (not a docstring) as its only contract with the calling model.

#### Scenario: Tool list is stable
- **WHEN** an MCP client connects to the server
- **THEN** exactly the five named tools are advertised, with repository tool descriptions identifying returned data as untrusted and not authorisation to execute commands

#### Scenario: Resource template is advertised
- **WHEN** an MCP client calls `list_resource_templates`
- **THEN** exactly one template is returned with URI pattern `skill://{registry}/{+skill}{?file}`

### Requirement: Error Classification
The server SHALL distinguish two classes of error:
**Model-recoverable errors** — conditions the calling agent can fix (unknown registry,
skill not found, companion file not found, path traversal, unsupported operation) —
SHALL reach the agent as an `is_error=True` tool result carrying the original,
readable message; the agent may retry.
**Infrastructure failures** — conditions the agent cannot fix (HTTP error, timeout,
rate limit exhausted, auth env var unset) — SHALL be caught at the tool boundary
and returned as a plain error string result; the server and other registries remain
unaffected.

#### Scenario: Unknown registry produces is_error result
- **WHEN** a tool is called with a registry name not in the config
- **THEN** the result has `is_error=True` and contains the unknown name

#### Scenario: Network error produces error string result
- **WHEN** a registry's upstream host is unreachable (connection timeout)
- **THEN** the tool returns a plain string starting with "Error:" and the server continues serving

#### Scenario: One registry failure does not affect another
- **WHEN** a request to registry A fails with a network error
- **THEN** a subsequent request to registry B succeeds normally

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
Every failed read — model-recoverable or infrastructure — SHALL be returned to the client
as an error response carrying a readable message, without crashing the server.

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
- **THEN** an error response naming the unknown registry is returned and the server continues serving

#### Scenario: Registry infrastructure failure produces error content item
- **WHEN** `read_resource` is called and the registry is temporarily unreachable
- **THEN** an error response is returned without crashing the server

#### Scenario: Path traversal in resource URI is rejected
- **WHEN** `read_resource` is called with a `file` query value containing a `..` path component
- **THEN** an error response is returned and no upstream fetch is attempted
