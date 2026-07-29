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
Use the full slash-delimited path as the `skill` argument to `get_skill` and `get_skill_file`.

## MCP Tools

| Tool | Parameters | Returns |
|---|---|---|
| `list_registries` | — | JSON array: `[{name, type, ref?}]` |
| `list_skills` | `registry` | JSON array: `["skill-a", "skill-b"]` |
| `get_skill` | `registry`, `skill` | JSON object: `{content: "…SKILL.md text…", files: ["references/guide.md"]}` |
| `get_skill_file` | `registry`, `skill`, `file_path` | Raw text of the companion file |

`get_skill_file` is only supported for GitHub registries. `file_path` must be a path relative to the skill root (as listed in `get_skill`'s `files` array); path traversal attempts are rejected.

### Error handling

Each tool uses a consistent error format for its response type:

- **Model-recoverable errors** (skill not found, unknown registry, unsupported operation, path traversal) — FastMCP marks the result `is_error=True`; the agent reads the message and may retry with corrected arguments.
- **Infrastructure failures** (registry unreachable, auth failure, rate-limited) — caught at the tool boundary and returned as a per-tool error value (`{"error": "…"}` JSON for `list_skills`/`get_skill`; plain `"Error: …"` string for `get_skill_file`). The server and other registries continue serving normally — one registry failure does not cascade.

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

Tools are exposed as `skills_mcp_list_registries`, `skills_mcp_list_skills`, `skills_mcp_get_skill`, and `skills_mcp_get_skill_file` in opencode's permission system.

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
uv run pytest tests/ -q          # 77 tests
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
