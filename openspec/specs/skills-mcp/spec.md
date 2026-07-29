# skills-mcp

## Purpose

MCP server for fetching agent skills from configurable registries. Agents use its tools
to discover and read skill content (SKILL.md and companion files) from remote sources
without installing skills locally. Supports GitHub repositories (public and private,
multi-skill, ref-locked) and direct HTTP URLs.

*This is the initial stub spec. All requirements are introduced by change `skills-mcp-server`.*
## Requirements
### Requirement: MCP Tool Surface
The server SHALL expose exactly four MCP tools — `list_registries`, `list_skills`,
`get_skill`, and `get_skill_file` — over a stdio transport using FastMCP. Each tool
SHALL carry an explicit `description=` parameter (not a docstring) as its only contract
with the calling model.

#### Scenario: Tool list is stable
- **WHEN** an MCP client connects to the server
- **THEN** exactly four tools are advertised: `list_registries`, `list_skills`, `get_skill`, `get_skill_file`

### Requirement: List Registries Tool
`list_registries()` SHALL return a list of objects, one per configured registry, each
containing `name` (string), `type` (`"github"` or `"http"`), and optionally `ref`
(the configured ref for GitHub registries; absent for HTTP). The operation requires no
I/O and SHALL never fail with an error.

#### Scenario: Returns all configured registries
- **WHEN** `list_registries` is called with two configured registries (one GitHub, one HTTP)
- **THEN** both appear in the result with their name, type, and ref (GitHub) or no ref (HTTP)

#### Scenario: Returns empty list when no registries configured
- **WHEN** `list_registries` is called with an empty registry config
- **THEN** the result is an empty list

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

### Requirement: Get Skill Tool
`get_skill(registry: str, skill: str)` SHALL return an object with two fields:
`content` (a string containing the full text of `SKILL.md` for the named skill)
and `files` (a sorted list of companion file paths relative to the skill root,
excluding `SKILL.md` itself). For HTTP registries `files` SHALL be an empty list.

#### Scenario: Returns SKILL.md content and companion files from GitHub
- **WHEN** `get_skill` is called for a GitHub registry skill that contains `SKILL.md`
  and a `references/guide.md` companion file
- **THEN** `content` contains the full SKILL.md text and `files` contains `["references/guide.md"]`

#### Scenario: Returns SKILL.md content from HTTP registry
- **WHEN** `get_skill` is called for an HTTP registry
- **THEN** `content` contains the fetched text and `files` is an empty list

#### Scenario: Missing skill raises error
- **WHEN** `get_skill` is called for a skill that does not exist in the registry
- **THEN** the tool returns an `is_error=True` result (a `SkillNotFoundError` is raised)

### Requirement: Get Skill File Tool
`get_skill_file(registry: str, skill: str, file_path: str)` SHALL return the raw text
content of the named companion file for the given skill in a GitHub registry.
For HTTP registries the tool SHALL raise a `ValueError` describing that the operation
is unsupported. `file_path` values not present in the skill's enumerated file tree
SHALL raise a `ValueError`. Path traversal attempts (paths containing `..` or rooted
outside the skill) SHALL raise a `ValueError`.

#### Scenario: Returns companion file content from GitHub
- **WHEN** `get_skill_file` is called for a valid GitHub registry, skill, and companion file path
- **THEN** the raw text of that file is returned

#### Scenario: Unsupported on HTTP registry
- **WHEN** `get_skill_file` is called for an HTTP registry
- **THEN** the tool returns an `is_error=True` result describing the operation as unsupported

#### Scenario: Unknown file path raises error
- **WHEN** `get_skill_file` is called with a `file_path` not listed in the skill's file tree
- **THEN** the tool returns an `is_error=True` result

#### Scenario: Path traversal is rejected
- **WHEN** `get_skill_file` is called with `file_path` containing `..` segments that escape the skill root
- **THEN** the tool returns an `is_error=True` result (a `PathTraversalError` is raised)

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

## Scenarios
