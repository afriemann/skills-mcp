## Why

Agents that use opencode need to load skills during sessions. Currently, skills must be
manually installed to `~/.agents/skills/` before they can be used. There is no mechanism
for agents to discover or fetch skill content from remote sources at runtime — every skill
must be present on disk at session start. A skills-mcp server addresses this by letting
agents read skill content (SKILL.md and companion files) directly from configurable remote
registries via MCP tools, without requiring local installation.

## What Changes

- **New Python MCP server** (`skills-mcp`) built with FastMCP + anyio SIGTERM-safe
  shutdown, exposing four tools: `list_registries`, `list_skills`, `get_skill`,
  `get_skill_file`
- **JSONC configuration file** at `~/.config/opencode/skills-mcp.jsonc` declares named
  registries, authentication, and cache settings; config holds env-var *names* only —
  never inline secret values
- **GitHub registry adapter**: fetches skill content from a multi-skill GitHub repository
  (one skill per subdirectory) using the GitHub Contents API; supports ref-locking to a
  branch, tag, or SHA; supports public repos (no auth), token auth via env var
  (`github_token`), and token auth via the `gh` CLI (`gh_cli` — runs `gh auth token`,
  cached per-session, degrades gracefully when `gh` is absent)
  > **Rate limits**: unauthenticated access is 60 requests/hour; meaningful use of
  > private registries or large listing operations effectively requires auth. The adapter
  > handles `429`/`Retry-After` responses.
- **HTTP registry adapter**: fetches a single skill's `SKILL.md` directly from a declared
  URL; `list_skills` returns that one skill; `get_skill_file` is **not supported** (no
  directory to traverse). Supports unauthenticated, bearer-token, and HTTP-basic auth.
- **Default-on read-through disk cache** at `~/.cache/opencode/skills-mcp/` (mode 0700);
  cache key = `{registry}/{ref}/{skill}/{file}`; **SHA-locked refs cache indefinitely**
  (immutable content); branch/tag refs use the configured TTL (default: 3600 s). Cache
  can be disabled globally or per registry.
- Skills are **never installed locally** — content is always fetched from the source
  (subject to caching). `get_skill` returns the raw SKILL.md text **plus the list of
  available companion files** so agents can discover what to request via `get_skill_file`.
  Fetched skill content is raw text in the tool result; it is not activated as a
  natively-installed skill with a resolved base directory.

## Tool Surface

| Tool | Arguments | Returns |
|---|---|---|
| `list_registries` | — | `[{name, type, ref?}]` |
| `list_skills` | `registry` | `[name]` (names only; call `get_skill` for description) |
| `get_skill` | `registry, skill` | `{content: str, files: [str]}` |
| `get_skill_file` | `registry, skill, file_path` | raw text (GitHub only; error for HTTP) |

Path traversal must be validated: `file_path` in `get_skill_file` must resolve within
the skill's directory; `..` traversal outside the skill root is rejected.

## Registry Trust Model

The config file is the **allow-list**: agents can only access registries named in
`skills-mcp.jsonc`; they cannot pass arbitrary URLs to tools. SHA-pinning a GitHub ref
to a specific commit SHA is the **recommended posture** for sensitive or production
registries — a SHA ref is immutable and cached indefinitely. Branch and tag refs are
allowed but are mutable; a compromised or updated upstream would be served on the next
cache miss.

## Capabilities

### New Capabilities

- `skills-mcp`: Full MCP server including the four tools, both registry adapters (GitHub
  and HTTP), JSONC configuration loading and validation, authentication handling
  (`none`, `github_token`, `gh_cli` for GitHub; `none`, `bearer`, `basic` for HTTP),
  and the read-through disk cache with immutable-vs-mutable TTL differentiation.

### Modified Capabilities

*(none — new project)*

## Non-Goals (v1)

- Writing, publishing, or updating skills to registries
- Skill execution or activation (installing to `~/.agents/skills/`)
- Non-GitHub git hosts (GitLab, Bitbucket, gists)
- GitHub App authentication or OAuth flows
- Content-hash integrity verification / signed skills
- Update notifications or change detection
- Size cap or LRU eviction for the disk cache
- Concurrent multi-writer locking (single-process cache; advisory temp-file rename)

## Impact

- **New repository**: `opencode-skills-mcp` (Python, uv, hatchling, `src/` layout)
- **New config file**: `~/.config/opencode/skills-mcp.jsonc` (user-created; documented
  in README)
- **opencode.jsonc**: users add a `skills-mcp` entry under `mcp` to enable the server
- **Dependencies**: `mcp[cli]>=1.27.2,<2`, `httpx>=0.27`, `anyio>=4.0,<5`
  (versions to be verified against current releases before implementation)
- **Runtime requirement**: `uv` (for `uv run --project`), optionally `gh` CLI (for
  `gh_cli` auth type)
- **opencode permission block**: MCP tools (`skills_mcp_list_registries`, etc.) bypass
  native `edit`/`write` guards and must be gated explicitly — documented in README
