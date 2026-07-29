## 1. Project Scaffolding

- [x] 1.1 Create `pyproject.toml` (hatchling build, uv, entry point `skills-mcp`, dev deps: pytest, pytest-asyncio, ruff, mypy)
- [x] 1.2 Create package skeleton: `src/skills_mcp/__init__.py`, `src/skills_mcp/__main__.py` (stub), `tests/__init__.py`
- [x] 1.3 Run `uv sync` to generate `uv.lock` and confirm the dev environment installs cleanly
- [x] 1.4 Configure `pre-commit` with ruff lint/format and mypy hooks; add `.pre-commit-config.yaml`
- [x] 1.5 Confirm `httpx` version floor against current PyPI release; update `pyproject.toml` pin if needed

## 2. Error Taxonomy (`errors.py`)

- [x] 2.1 Define `RegistryUnavailableError` (infra) and `ValueError` subclasses: `RegistryNotFoundError`, `SkillNotFoundError`, `SkillFileNotFoundError`, `PathTraversalError`, `UnsupportedOperationError`
- [x] 2.2 Write unit tests covering that each error is the correct base type (ValueError vs not)

## 3. Config Model (`config/model.py`)

- [x] 3.1 Implement frozen dataclass hierarchy: `Config`, `GithubRegistry`, `HttpRegistry`, `CacheConfig`, and all auth variants (`NoAuth`, `GithubTokenAuth`, `GhCliAuth`, `BearerAuth`, `BasicAuth`)
- [x] 3.2 Add `ref_is_sha: bool` derived field to `GithubRegistry` (computed from ref matching `^[0-9a-f]{7,40}$`)

## 4. Config Loader (`config/loader.py`)

- [x] 4.1 Implement stdlib string-aware JSONC comment stripper (tracks in-string state, handles `//` in URL literals, strips `//` and `/* */` comments, tolerates one trailing comma before `]`/`}`)
- [x] 4.2 Write table-driven unit tests for the JSONC stripper: URL-in-string, comment-in-string, trailing comma, block comment, nested objects
- [x] 4.3 Implement `load_config(path=None) -> Config` with `_fatal`/`sys.exit(1)` on any error; resolve default path via `XDG_CONFIG_HOME` → `~/.config/opencode/skills-mcp.jsonc`
- [x] 4.4 Write unit tests: missing file exits 1; bad JSON exits 1; unknown registry type exits 1; valid minimal config loads successfully
- [x] 4.5 Ensure auth env-var names are validated as non-empty strings at load time

## 5. Authentication (`auth.py`)

- [x] 5.1 Implement `AuthResolver` with `headers_for(auth) -> dict[str, str]`: `NoAuth`→`{}`, `GithubTokenAuth`→Bearer, `BearerAuth`→Bearer, `BasicAuth`→Basic (base64 from env vars); missing env var → `RegistryUnavailableError`
- [x] 5.2 Implement `gh_cli` token fetching via `anyio.run_process` with an `asyncio.Lock` for in-process caching; graceful fallback to `NoAuth` when `gh` is absent or exits non-zero (log warning to stderr)
- [x] 5.3 Write unit tests: correct header per auth variant; missing env var raises `RegistryUnavailableError`; `gh_cli` calls subprocess once and caches token; absent `gh` falls back to `NoAuth`

## 6. Disk Cache (`cache.py`)

- [x] 6.1 Implement `DiskCache` with `get(key, immutable, ttl) -> bytes | None` and `put(key, data: bytes) -> None`; atomic write via temp-file + `os.replace`; create cache root with mode `0700`
- [x] 6.2 Implement cache key → disk path mapping: percent-encode `registry`, `ref`, `skill` components; keep `file_path` as nested dirs; sentinel names `__skills.json` and `__skill.json`
- [x] 6.3 TTL logic: `immutable=True` → always hit; `immutable=False` → compare file mtime to `now - ttl`
- [x] 6.4 Write unit tests: cache hit returns stored bytes; expired entry returns None; immutable entry never expires; atomic write (interleaved writes produce complete files); 0700 root creation; disabled cache bypasses disk

## 7. Registry Adapters Protocol + CachingRegistry (`registries/__init__.py`)

- [x] 7.1 Define `SkillContent` (NamedTuple: `content: str`, `files: tuple[str, ...]`) and `RegistryAdapter` Protocol (`name`, `type`, `ref`, `list_skills`, `fetch_skill`, `fetch_file`)
- [x] 7.2 Implement `CachingRegistry` decorator: wraps any `RegistryAdapter`; caches `list_skills`, `fetch_skill`, `fetch_file`; never caches errors; bypasses cache when `enabled=False`
- [x] 7.3 Implement `build_adapters(config, http_client, auth_resolver) -> dict[str, RegistryAdapter]`
- [x] 7.4 Write unit tests for `CachingRegistry`: cache miss fetches from inner; cache hit skips inner; errors not cached; disabled bypasses cache

## 8. HTTP Adapter (`registries/http.py`)

- [x] 8.1 Implement `HttpAdapter`: `list_skills`→`[skill_name]`; `fetch_skill`→GET url with auth header; `fetch_file`→raise `UnsupportedOperationError`; non-2xx response → `RegistryUnavailableError`
- [x] 8.2 Write unit tests using a fake `httpx` transport: correct skill name; successful fetch; 404 response → `RegistryUnavailableError`; wrong skill name → `SkillNotFoundError`; `fetch_file` → `UnsupportedOperationError`

## 9. GitHub Adapter (`registries/github.py`)

- [x] 9.1 Implement Contents API call for `list_skills`: GET `/repos/{owner}/{repo}/contents/{skills_dir}?ref={ref}`, keep entries with `type=="dir"`, return names; log stderr warning when result is 1,000 entries (potential truncation)
- [x] 9.2 Implement `fetch_skill`: GET Contents listing to obtain skill dir's `tree_sha`; recursive Trees API `/git/trees/{sha}?recursive=1`; locate `SKILL.md` in tree; fetch raw blob via `/git/blobs/{sha}` with `Accept: application/vnd.github.raw`; populate `files` from remaining blobs
- [x] 9.3 Implement `fetch_file`: validate `file_path` using `PurePosixPath` normalisation (reject absolute paths and `..`-escaping paths → `PathTraversalError`); look up SHA in enumerated tree (not found → `SkillFileNotFoundError`); fetch raw blob
- [x] 9.4 Implement `Retry-After` handling: on `429`/`403` with `Retry-After` header, wait once (cap at 5 s); second failure → `RegistryUnavailableError`
- [x] 9.5 Non-2xx responses other than rate-limit → `RegistryUnavailableError`; 404 on skill dir → `SkillNotFoundError`
- [x] 9.6 Write unit tests using a fake `httpx` transport: list_skills returns subdirs; fetch_skill gets tree + blob; fetch_file path guard rejects `../../`; fetch_file rejects unlisted path; Retry-After respected once; second 429 → error; >1 MB blob fetched via raw endpoint

## 10. Dispatcher (`dispatch.py`)

- [x] 10.1 Implement `Dispatcher(adapters: dict[str, RegistryAdapter])` with `list_registries()` (pure, no I/O) and async `list_skills`, `get_skill`, `get_skill_file` delegating to the named adapter (unknown name → `RegistryNotFoundError`)
- [x] 10.2 Write unit tests: unknown registry raises `RegistryNotFoundError`; delegation to correct adapter; `list_registries` returns all adapters' metadata

## 11. Server Wiring + Entry Point (`server.py`, `__main__.py`)

- [x] 11.1 Implement `build_app(config_path=None) -> FastMCP` with lifespan (open/close shared `httpx.AsyncClient`), `AuthResolver`, `DiskCache`, `build_adapters`, `Dispatcher`
- [x] 11.2 Register all four tools as thin async wrappers with explicit `description=` parameters; translate `ValueError` subclasses to `is_error=True`; catch `RegistryUnavailableError` and return error strings
- [x] 11.3 Implement `_run_with_graceful_shutdown(app)` (anyio SIGTERM receiver + 1 s `os._exit(0)` watchdog, following `md-mcp` pattern)
- [x] 11.4 Implement `__main__.main()`: argparse (`--config`, `--log-level`); `logging.basicConfig(stream=sys.stderr)`; `build_app()`; `anyio.run(_run_with_graceful_shutdown, app)`

## 12. Integration Tests (`tests/`)

- [x] 12.1 Write in-memory MCP client tests (`Client(mcp, raise_exceptions=True)`) covering the full tool surface with fake GitHub and HTTP transports: `list_registries`, `list_skills`, `get_skill`, `get_skill_file` happy paths
- [x] 12.2 Write integration tests for error-taxonomy routing: unknown registry → `is_error=True`; network error → plain error string; path traversal → `is_error=True`; HTTP `fetch_file` → `is_error=True`
- [x] 12.3 Run the full test suite; ensure all tests pass and all linter/type errors are resolved

## 13. Documentation + opencode Integration

- [x] 13.1 Write `README.md`: installation; `opencode.jsonc` MCP block with `uv run --project` pattern; full `skills-mcp.jsonc` example (GitHub + HTTP registries, all auth variants); SHA-pinning recommendation; rate-limit/auth guidance; cache location and TTL explanation; `permission` gating example
- [x] 13.2 Add `opencode.jsonc` stub to the repo root wiring `skills-mcp` to opencode via `uv run --project`
- [x] 13.3 Verify the server can be launched manually with `uv run skills-mcp --help`

## 14. Final Verification

- [x] 14.1 Run `ruff check` and `ruff format --check`; fix all issues
- [x] 14.2 Run `mypy src/`; resolve all type errors
- [x] 14.3 Run the full test suite via `pytest`; confirm all pass
- [x] 14.4 Run `openspec validate skills-mcp-server`; confirm no errors
