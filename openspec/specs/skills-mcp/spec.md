# skills-mcp

## Purpose

MCP server for fetching agent skills from configurable registries. Agents use its tools
to discover and read skill content (SKILL.md and companion files) from remote sources
without installing skills locally. Supports GitHub repositories (public and private,
multi-skill, ref-locked) and direct HTTP URLs.

*This is the initial stub spec. All requirements are introduced by change `skills-mcp-server`.*
## Requirements
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

### Requirement: Configuration Loading
The server SHALL load its registry and cache configuration from the platform
config directory (Linux: `$XDG_CONFIG_HOME/skills-mcp/config.jsonc`, default
`~/.config/skills-mcp/config.jsonc`; macOS: `~/Library/Application Support/skills-mcp/config.jsonc`;
Windows: `%APPDATA%\skills-mcp\config.jsonc`) (JSONC format: `//` line comments,
`/* */` block comments, one trailing comma before `]` or `}` are all permitted).
The JSONC comment stripper SHALL correctly preserve `//` occurring inside string
literals (e.g. inside URL values). On any unreadable, unparseable, or structurally
invalid config, the server SHALL print an actionable error to stderr and exit with
code 1 **before** the JSON-RPC handshake completes. A `--config` CLI argument SHALL
override the default path.

#### Scenario: Loads valid JSONC with comments
- **WHEN** the config file contains `//` comments and a trailing comma
- **THEN** the server starts and all registries are available

#### Scenario: Preserves URLs containing double-slash
- **WHEN** a registry URL such as `"https://github.com/..."` appears in the config
- **THEN** the server parses it correctly without stripping the `//` inside the string

#### Scenario: Exits on missing config
- **WHEN** the config file does not exist
- **THEN** the server writes an error to stderr and exits with code 1

#### Scenario: Exits on invalid registry type
- **WHEN** a registry entry specifies an unknown `type` field
- **THEN** the server writes an actionable error to stderr and exits with code 1

### Requirement: Registry Allow-List Trust Model
The server SHALL restrict agent access to the named registries declared in
configuration. Agents SHALL NOT be able to pass arbitrary URLs or paths to the
server's tools; all registry access is addressed by name only. The configuration file
is the sole allow-list.

#### Scenario: Agent cannot access an ad-hoc URL
- **WHEN** a tool is called with a `registry` value not in the config
- **THEN** the tool returns an `is_error=True` result (the name is not in the allow-list)

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

### Requirement: HTTP Registry Adapter
The HTTP adapter SHALL fetch skill content from a single, directly-addressed `SKILL.md`
URL. `list_skills` SHALL return a single-element list with the declared `skill_name`.
`get_skill` SHALL perform an HTTP GET of the configured `url` and return the response
body as `content` with an empty `files` list. `get_skill_file` SHALL raise an
`UnsupportedOperationError` (`ValueError`).

#### Scenario: Lists single skill name
- **WHEN** `list_skills` is called for an HTTP registry with `skill_name = "my-skill"`
- **THEN** the result is `["my-skill"]`

#### Scenario: Fetches SKILL.md from URL
- **WHEN** `get_skill` is called for the HTTP registry
- **THEN** an HTTP GET is performed and the response body is returned as `content`

#### Scenario: get_skill_file raises unsupported error
- **WHEN** `get_skill_file` is called for an HTTP registry
- **THEN** an `is_error=True` result is returned with a message describing the limitation

### Requirement: GitHub Rate Limit Handling
The GitHub adapter SHALL honour rate-limit responses by waiting once for the duration
specified in the `Retry-After` header (up to a small cap) on a `429` or `403` response,
then retrying. If the retry still fails, or if no `Retry-After` is present, the adapter
SHALL raise a `RegistryUnavailableError` which the tool boundary translates to an error
string result. The server SHALL NOT crash on rate-limit responses.

#### Scenario: Retries once on 429 with Retry-After
- **WHEN** a GitHub API call returns 429 with `Retry-After: 2`
- **THEN** the adapter waits approximately 2 seconds and retries the request once

#### Scenario: Returns error string after second rate-limit
- **WHEN** a GitHub API call returns 429 on both the initial attempt and the retry
- **THEN** the tool returns an error string result (not an is_error crash)

### Requirement: Read-Through Disk Cache
The server SHALL maintain a read-through disk cache at the platform cache
directory (Linux: `$XDG_CACHE_HOME/skills-mcp/`, default `~/.cache/skills-mcp/`;
macOS: `~/Library/Caches/skills-mcp/`; Windows: `%LOCALAPPDATA%\skills-mcp\Cache`)
(mode `0700`). The cache SHALL store the results of `list_skills`, `fetch_skill`, and
`fetch_file` operations. Only successful fetches SHALL be written to the cache.
Cache writes SHALL be atomic: content is written to a temporary file in the same
directory and renamed to its final path via `os.replace()`. Caching SHALL be
enabled by default and configurable globally (via `CacheConfig.enabled`) and
per-registry (via each registry's `cache_enabled` flag).

#### Scenario: Cache directory is created with mode 0700
- **WHEN** the server starts and the cache directory does not exist
- **THEN** the directory is created with permissions `0700`

#### Scenario: Subsequent call returns cached result
- **WHEN** `get_skill` is called twice for the same registry and skill within the TTL
- **THEN** the second call returns the cached result without making an upstream API call

#### Scenario: Failed upstream fetch is not cached
- **WHEN** a registry is unreachable and returns an error
- **THEN** no cache entry is written, and the next call attempts the upstream again

#### Scenario: Cache is bypassed when disabled per-registry
- **WHEN** a registry's `cache_enabled = false` and `get_skill` is called
- **THEN** the upstream API is called every time regardless of any existing cache entry

### Requirement: Immutable Cache Entries
The server SHALL treat cache entries for a GitHub registry with a SHA-locked `ref`
as immutable (never expiring), regardless of `ttl_seconds`. A ref that consists
entirely of lowercase hex characters with a length between 7 and 40 characters is
classified as a SHA at config-load time; all other refs use the configured TTL.

#### Scenario: SHA-locked cache entry never expires
- **WHEN** a GitHub registry is configured with a SHA ref, `get_skill` populates the cache,
  and the `ttl_seconds` has elapsed
- **THEN** the cached entry is still served on the next call (no re-fetch)

#### Scenario: Branch-ref cache entry expires after TTL
- **WHEN** a GitHub registry is configured with a branch ref, `get_skill` populates the cache,
  and more than `ttl_seconds` has elapsed since the cache entry was written
- **THEN** a fresh upstream fetch is performed

### Requirement: Authentication
Authentication configuration SHALL use env-var names only; secret values SHALL never
be stored in the config file. For GitHub registries the supported auth variants are:
`none` (no header), `github_token` (PAT from a named env var as `Authorization: Bearer`),
and `gh_cli` (token retrieved via `gh auth token` subprocess). For HTTP registries:
`none`, `bearer` (named env var as `Authorization: Bearer`), and `basic` (two named
env vars as `Authorization: Basic`). A missing or empty env-var value at request time
SHALL produce a `RegistryUnavailableError` (→ error string, per-tool).

#### Scenario: GitHub token auth injects Bearer header
- **WHEN** a registry is configured with `github_token` auth and the named env var is set
- **THEN** every GitHub API request carries `Authorization: Bearer <token>`

#### Scenario: Bearer auth injects header from env var
- **WHEN** an HTTP registry is configured with `bearer` auth and the named env var is set
- **THEN** the GET request carries `Authorization: Bearer <value>`

#### Scenario: Missing env var produces error string
- **WHEN** an auth-protected registry is accessed and the required env var is not set
- **THEN** the tool returns an error string (not an is_error crash), and other registries remain accessible

### Requirement: GH CLI Token Caching
When `gh_cli` auth is configured, the server SHALL obtain a token by running
`gh auth token` as an async subprocess and cache the result in-process for the
server's lifetime (re-running `gh` only on a cache miss). When `gh` is absent,
not logged in, or returns a non-zero exit code, the server SHALL log a warning
to stderr and fall back to unauthenticated requests (no `Authorization` header).

#### Scenario: Token is fetched once and reused
- **WHEN** two consecutive requests use a `gh_cli`-auth registry
- **THEN** `gh auth token` is invoked only once; the second request uses the cached token

#### Scenario: Missing gh CLI falls back to no auth
- **WHEN** `gh_cli` auth is configured and the `gh` binary is not on PATH
- **THEN** the server logs a warning to stderr, proceeds without an auth header, and does not crash

### Requirement: Path Traversal Protection
`get_skill_file` SHALL reject any `file_path` whose normalised form contains `..`
segments that escape the skill root, or that is an absolute path, by raising a
`PathTraversalError` (`ValueError`). As a defence-in-depth measure, the server SHALL
only serve `file_path` values that appear in the skill's enumerated file tree (obtained
from the Trees API); paths that are structurally safe but not in the tree SHALL raise
a `SkillFileNotFoundError` (`ValueError`).

#### Scenario: Dotdot traversal is rejected at normalisation
- **WHEN** `get_skill_file` is called with `file_path = "../../other-skill/secrets"`
- **THEN** `is_error=True` is returned (PathTraversalError), no upstream fetch is attempted

#### Scenario: Absolute path is rejected
- **WHEN** `get_skill_file` is called with `file_path = "/etc/passwd"`
- **THEN** `is_error=True` is returned (PathTraversalError)

#### Scenario: Valid path not in tree returns not-found
- **WHEN** `get_skill_file` is called with a safe relative path that is not in the skill's file tree
- **THEN** `is_error=True` is returned (SkillFileNotFoundError), no blob fetch is attempted

### Requirement: Error Classification
The server SHALL distinguish two classes of error:
**Model-recoverable errors** — conditions the calling agent can fix (unknown registry,
skill not found, companion file not found, path traversal, unsupported operation) —
SHALL be raised as `ValueError` subclasses so FastMCP marks the tool result
`is_error=True`; the agent reads the message and may retry.
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

### Requirement: Server Startup and Shutdown
The server entry point SHALL configure `logging` to write exclusively to `stderr`
(never `stdout`) before accepting any requests. The server SHALL support a `--config`
argument and a `--log-level` argument. On `SIGTERM` the server SHALL cooperatively
shut down via `anyio` and exit within 1 second even if stdin is blocked, using a
`os._exit(0)` watchdog timer.

#### Scenario: Logging goes to stderr only
- **WHEN** the server is running and a request triggers a log message
- **THEN** the log output appears on stderr and stdout carries only JSON-RPC frames

#### Scenario: SIGTERM triggers clean shutdown within 1 second
- **WHEN** SIGTERM is sent to the running server
- **THEN** the process exits within 1 second

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

## Scenarios
