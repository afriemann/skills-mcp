# AGENTS.md — skills-mcp

Guidelines for AI agents working on this codebase.

## Project overview

`skills-mcp` is a Python MCP server (stdio transport) that lets agents browse and fetch skill files from remote registries — GitHub repositories or direct HTTP URLs — without local installation. It exposes four MCP tools: `list_registries`, `list_skills`, `get_skill`, `get_skill_file`.

## Development commands

```bash
# Install dependencies (creates .venv automatically)
uv sync

# Run tests
uv run pytest tests/ -q

# Lint
uv run ruff check src/ tests/

# Type check
uv run mypy src/

# Format check (do not auto-format manually — pre-commit handles this at commit time)
uv run ruff format --check src/ tests/
```

Pre-commit hooks run automatically on `git commit`. Install once with `pre-commit install --install-hooks`.

## Architecture

Strict one-directional layering — never import from a higher layer into a lower one:

```
L0  errors.py              — exception types (ValueError subclasses for model-recoverable; RegistryUnavailableError for infra)
L1  config/                — frozen-dataclass config model, JSONC loader (fail-fast with sys.exit on bad config)
    auth.py                — AuthResolver (headers_for), gh_cli token cached in-process
    cache.py               — DiskCache (mtime TTL, atomic writes, 0700 root, percent-encoded paths)
L2  registries/            — RegistryAdapter Protocol; CachingRegistry decorator; GithubAdapter; HttpAdapter
L3  dispatch.py            — Dispatcher: routes operations to named adapters
L4  server.py              — build_app() factory; four MCP tools; FastMCP lifespan (shared httpx.AsyncClient)
L5  __main__.py            — CLI entry (argparse); anyio.run(_run_with_graceful_shutdown)
```

Key invariants:
- Adapters are pure source-fetchers — caching is in `CachingRegistry`, not embedded in adapters
- Tools never call adapters directly — they go through `Dispatcher`
- `_fatal(msg)` in `loader.py` calls `sys.exit(1)` — used only for unrecoverable config errors at startup

## Error taxonomy

| Situation | Raise / return | What the agent sees |
|---|---|---|
| Skill not found, unknown registry, path traversal, unsupported operation | `raise SkillNotFoundError(...)` etc. (ValueError subclass) | `is_error=True`; message readable; agent may retry |
| Registry unreachable, auth failure, rate limit | Caught at tool boundary; return error string | Plain `"Error: …"` or `{"error": "…"}` JSON; other registries unaffected |

## Code conventions

- Python ≥ 3.11; `uv` for all dependency management (never `pip install`)
- All config dataclasses are frozen; use `dataclasses.replace()` to produce variants
- No magic numbers — constants belong in `config/model.py`
- `strip_jsonc()` in `loader.py` is string-aware — do not replace it with regex; it handles `//` inside URL strings
- `anyio` throughout for async — do not mix `asyncio` primitives (except `asyncio.subprocess.PIPE` → use `subprocess.PIPE` instead)
- Tests use `httpx.MockTransport` / fake adapters — no real network calls

## Branching

Feature branches with descriptive names. There is no ticket-ID convention; branch names should be `feat/…`, `fix/…`, `docs/…` etc. Merge into `main` via PR or direct merge with a merge commit.

## OpenSpec

Behaviour spec lives in `openspec/`. The initial change is archived at `openspec/archive/2026-07-29-skills-mcp-server/`. Before any change that modifies tool surface or registry behaviour, check `openspec/specs/skills-mcp/spec.md` to anchor current behaviour, then use `openspec new change "…"` to scaffold a delta.

## What NOT to do

- Do not add `print()` to server code — stdout carries MCP JSON-RPC framing; any stray byte breaks the connection. Use `logging` to stderr.
- Do not write inline secret values to `config.jsonc` — config stores env var names only.
- Do not bypass `CachingRegistry` by calling adapters directly from the server layer.
- Do not add `sys.exit` calls outside `config/loader.py`.
- Do not modify `openspec/specs/` directly — only the archive workflow or `openspec archive` should write to those files.
