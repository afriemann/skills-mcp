## MODIFIED Requirements

### Requirement: MCP Tool Surface
The server SHALL expose exactly two MCP tools — `list_skills` and `get_skill` —
and one MCP resource template — `skill://{registry}/{+skill}{?file}` — over a
stdio transport using FastMCP. Each tool SHALL carry an explicit `description=`
parameter (not a docstring) as its only contract with the calling model.

#### Scenario: Tool list is stable
- **WHEN** an MCP client connects to the server
- **THEN** exactly two tools are advertised: `list_skills`, `get_skill`

#### Scenario: Resource template is advertised
- **WHEN** an MCP client calls `list_resource_templates`
- **THEN** exactly one template is returned with URI pattern `skill://{registry}/{+skill}{?file}`

## REMOVED Requirements

### Requirement: List Registries Tool
**Reason**: Redundant — the config-assembled `list_skills` description already
enumerates every configured registry by name, so agents can call `list_skills`
directly without a prior discovery round-trip.
**Migration**: Remove any `list_registries` calls from agent workflows. Registry
names are visible in the `list_skills` tool description; call `list_skills` with
the desired registry name directly.
