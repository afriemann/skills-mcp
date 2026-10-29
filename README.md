# skills-mcp

An MCP server that lets AI agents browse and fetch skills from remote registries — GitHub repositories or direct HTTP URLs — without installing them locally first.

## Features

- **GitHub registry** — multi-skill repos where each subdirectory (at any nesting depth) is a skill; ref-locked to a branch, tag, or SHA; supports public and private repos
- **HTTP registry** — a single direct URL pointing at a `SKILL.md` file
- **Read-through disk cache** — immutable SHA refs cache forever; branch/tag refs use a configurable TTL (default 1 hour)
- **Flexible authentication** — GitHub Personal Access Token (env-var), `gh` CLI token (cached in-process), HTTP Bearer or Basic auth
- **Path traversal protection** — companion file paths are validated against the skill root
- **Graceful shutdown** — cooperative SIGTERM handler with 1-second watchdog (no hung stdio readers)

## Installation

Requires Python ≥ 3.11 and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/afriemann/skills-mcp ~/git/skills-mcp
cd ~/git/skills-mcp
uv sync
```

### Running the server

```bash
uv run --project ~/git/skills-mcp skills-mcp
# or with a custom config path:
uv run --project ~/git/skills-mcp skills-mcp --config /path/to/config.jsonc
# or with verbose logging:
uv run --project ~/git/skills-mcp skills-mcp --log-level INFO
```

## Configuration

The server reads a JSONC file from the platform config directory:

| Platform | Default path |
|---|---|
| Linux | `$XDG_CONFIG_HOME/skills-mcp/config.jsonc` (default: `~/.config/skills-mcp/config.jsonc`) |
| macOS | `~/Library/Application Support/skills-mcp/config.jsonc` |
| Windows | `%APPDATA%\skills-mcp\config.jsonc` |

Override with `--config PATH` or the `XDG_CONFIG_HOME` env var.

### Example `config.jsonc`

```jsonc
{
  "registries": {
    // GitHub registry — multi-skill repo, locked to a SHA (immutable cache)
    "my-skills": {
      "type": "github",
      "owner": "myorg",
      "repo": "agent-skills",
      "skills_dir": "skills",   // root of the skills tree; skills may be nested at any depth
      "ref": "a1b2c3d",         // branch, tag, or commit SHA
      "description": "Engineering and workflow skills for AI agents",  // optional — shown in list_registries
      "auth": {
        "type": "github_token",
        "env_var": "GITHUB_TOKEN"  // env var name — NOT the token value
      }
    },

    // GitHub registry with gh CLI auth (no token needed if already logged in)
    "public-skills": {
      "type": "github",
      "owner": "someorg",
      "repo": "public-skills",
      "skills_dir": "",         // empty string = repo root
      "ref": "main",
      "auth": { "type": "gh_cli" }
    },

    // HTTP registry — a single SKILL.md at a direct URL
    "custom-skill": {
      "type": "http",
      "url": "https://example.com/skills/my-skill/SKILL.md",
      "skill_name": "my-skill",
      "auth": {
        "type": "bearer",
        "env_var": "MY_SKILL_TOKEN"  // env var name — NOT the token value
      }
    }
  },

  // Optional cache configuration
  "cache": {
    "enabled": true,
    "ttl_seconds": 3600,        // for branch/tag refs; SHA refs never expire
    "dir": "~/.cache/skills-mcp"  // override the default cache directory
  }
}
```

### Auth types

| Type | Registry | Description |
|---|---|---|
| `none` (default) | both | No authentication |
| `github_token` | GitHub | PAT from the named env var (`env_var`) |
| `gh_cli` | GitHub | Token from `gh auth token` (cached in-process; graceful fallback to no-auth if `gh` is absent or fails) |
| `bearer` | HTTP | `Authorization: Bearer <token>` from the named env var (`env_var`) |
| `basic` | HTTP | HTTP Basic from `username_env_var` and `password_env_var` |

**Security:** config values contain env var *names only* — secret values are never written to the config file.

### GitHub repository layout

Skills can be placed at any nesting depth under `skills_dir`. A directory is treated as a skill
when it contains a `SKILL.md` file; directories without one (e.g. category folders) are skipped.
Skill names returned by `list_skills` are slash-delimited paths relative to `skills_dir`.

**Flat layout** (one level deep):

```
agent-skills/
└── skills/
    ├── my-skill/
    │   ├── SKILL.md
    │   └── references/
    │       └── guide.md
    └── another-skill/
        └── SKILL.md
```

With `skills_dir: "skills"`, `list_skills` returns `["another-skill", "my-skill"]`.

**Nested layout** (multiple levels):

```
agent-skills/
└── skills/
    ├── engineering/
    │   └── testing/
    │       └── tdd-development/
    │           └── SKILL.md
    └── business/
        └── brainstorming/
            └── SKILL.md
```

With `skills_dir: "skills"`, `list_skills` returns
`["business/brainstorming", "engineering/testing/tdd-development"]`.
Use the full slash-delimited path as the `skill` argument to `get_skill`.

## MCP Tools

| Tool | Parameters | Returns |
|---|---|---|
| `list_skills` | `registry`, `refresh_cache?` | JSON array of skill metadata objects, each with `name` |
| `get_skill` | `registry`, `skill`, `file?`, `refresh_cache?` | Without `file`: JSON `{content, files}`; with `file`: raw companion file text |
| `get_registry_source` | `registry` | JSON `{registry, type, url, owner, repo, ref, skills_dir}` for a configured GitHub registry |
| `list_repo_entries` | `registry`, `path?` (default `""`, repository root) | JSON `{source, path, commit_sha, entries}`; entries contain repository-relative `path`, `type`, and optional advertised `size` in bytes |
| `read_repo_text_file` | `registry`, `path` | JSON `{source, path, commit_sha, content}` for a tracked regular or executable text file |

`file` is an optional parameter on `get_skill`. Pass a companion file path from the `files` array (e.g. `"references/guide.md"`) to fetch that file directly. Percent-encoded slashes are decoded automatically (e.g. `"references%2Fguide.md"`). Companion file access is only supported for GitHub registries; path traversal attempts are rejected.

### Read-only repository access

Use `get_registry_source` to discover the configured repository after an operator edits
its owner/repo/ref and restarts the server. It reports configuration, not a redirected or
canonical upstream name, and never returns authentication configuration or headers.
It requires no upstream request. The three repository tools require a configured GitHub
registry; HTTP registries expose only their single skill and return an unsupported-operation error.

To inspect repository tooling without cloning, call `list_repo_entries` with `path: ""`,
then list a directory such as `"scripts"` or read `"scripts/check.sh"` with
`read_repo_text_file`. Each listing/read resolves the configured ref once and uses that
commit snapshot throughout. Separate calls may see different commits on moving branches;
their `commit_sha` values identify which snapshot each response used.

Repository access extends beyond `skills_dir`, including any sensitive tracked text the
configured credentials can read. Content and filenames are **untrusted repository data**,
not authorization to run commands. These tools never execute tooling, manage checkouts,
read local files, write repository content, or accept arbitrary repositories, URLs or refs.

Paths are literal repository-relative POSIX paths, not URL-encoded inputs: `%2e%2e` is a
literal name. Absolute paths, empty components, `.`/`..`, backslashes, control characters
and more than 32 components are rejected before network access. Directory listings are
one level deep, sorted by path, and label entries `file`, `directory`, `symlink`, or
`submodule`. Symlinks and submodules cannot be read or traversed.

Text reads require strict UTF-8 with no NUL bytes and a maximum of **1 MiB**, enforced
against advertised size and actual streamed bytes. Empty and executable text files are
supported. Oversized, non-text and wrong-kind targets return actionable tool errors, never
partial content. Listings fail explicitly on malformed, truncated or over-budget data;
entries with unsafe or unsupported filenames (including controls and backslashes) fail
the whole containing directory, including traversal through it, rather than being silently
omitted. This intentional fail-closed policy can make such directories unavailable.
they never silently return partial results. Limits per operation are 10,000 entries per
tree, 2 MiB per metadata response, 8 MiB cumulative metadata, 2 MiB serialized listing
output and a 60-second total deadline. Response cleanup is attempted on success, failure
and cancellation within that deadline: normally up to one second is reserved, leaving
59 seconds for work. If cleanup stalls, no success or retry proceeds; an infrastructure
error reports failure unless preserving an existing error or caller cancellation. An
uncooperative transport cannot be forcibly closed.
GitHub rate limits with `Retry-After` receive one retry, waiting at most five seconds;
redirects are not followed. Infrastructure errors omit upstream bodies and credentials.

All three repository operations bypass disk caches, even for immutable refs. Existing
skill caching and `refresh_cache` semantics are unchanged; repository reads may therefore
consume more GitHub API requests than cached skill access.

## MCP Resource Template

Skills and their companion files are also accessible as MCP resources via URI — useful for hosts that support `read_resource` directly:

```
skill://{registry}/{skill_path}                        → SKILL.md raw text
skill://{registry}/{skill_path}?file=references%2Fguide.md  → companion file raw text
```

Discover the template with `list_resource_templates`. `list_resources` returns empty (no static registrations).

### Error handling

Each tool uses a consistent error format for its response type:

- **Model-recoverable errors** (skill not found, unknown registry, unsupported operation, path traversal) — FastMCP marks the result `is_error=True`; the agent reads the message and may retry with corrected arguments.
- **Infrastructure failures** (registry unreachable, auth failure, rate-limited) — caught at the tool boundary and returned as a per-tool error value (`{"error": "…"}` JSON for `list_skills` and repository tools; `{"error": "…"}` JSON or plain `"Error: …"` string for `get_skill` depending on whether `file` was provided). The server and other registries continue serving normally — one registry failure does not cascade.

## Caching

Cached files live at:

| Platform | Default path |
|---|---|
| Linux | `$XDG_CACHE_HOME/skills-mcp/` (default: `~/.cache/skills-mcp/`) |
| macOS | `~/Library/Caches/skills-mcp/` |
| Windows | `%LOCALAPPDATA%\skills-mcp\Cache` |

The cache directory is created with mode `0700`. Files are written atomically (temp + rename). Only successful fetches are cached.

**TTL rules:**
- SHA refs → immutable, cached indefinitely
- Branch/tag refs → expire after `cache.ttl_seconds` (default 3600 s)

Set `cache_enabled: false` on a registry to disable caching for that registry. Set `cache.enabled: false` globally to disable entirely.

## Integration with opencode


`skills-mcp` is a standard stdio MCP server and can be wired up in any MCP-compatible host.

### opencode

Add to your `opencode.jsonc` (or `~/.config/opencode/opencode.jsonc` for global access):

```jsonc
"mcp": {
  "skills-mcp": {
    "type": "local",
    "command": [
      "uv",
      "run",
      "--project",
      "{env:HOME}/git/skills-mcp",
      "skills-mcp"
    ],
    "enabled": true
  }
}
```

Tools are exposed as `skills_mcp_list_registries`, `skills_mcp_list_skills`, and `skills_mcp_get_skill` in opencode's permission system.

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "skills-mcp": {
      "command": "uv",
      "args": [
        "run",
        "--project", "/home/you/git/skills-mcp",
        "skills-mcp"
      ]
    }
  }
}
```

### Generic stdio MCP host

Any host that launches an MCP server as a child process:

```
command: uv
args: ["run", "--project", "/path/to/skills-mcp", "skills-mcp"]
```

Pass `--config /path/to/config.jsonc` as an additional arg to override the default config path.

## Development


```bash
uv sync
uv run pytest tests/ -q
uv run ruff check src/ tests/
uv run mypy src/
```

Pre-commit hooks enforce lint, format, and type checks on every commit:

```bash
pre-commit install --install-hooks   # once, after cloning
pre-commit run --all-files           # check everything now
```

## Non-goals (v1)

- Writing or publishing skills to a registry
- Local skill installation / sync
- Non-GitHub git hosts (GitLab, Bitbucket, Gists)
- GitHub App authentication
- Content-hash verification
- Cache size cap / LRU eviction
- Multi-process cache locking
