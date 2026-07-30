## 1. Frontmatter Parser

- [x] 1.1 Create `src/skills_mcp/frontmatter.py` with `parse_frontmatter(content: str) -> dict[str, object]` line-by-line state machine (D1 grammar: scalar strings, single/double-quoted values with `''` escape, block lists, comment skipping, nested-mapping skip, never raises)
- [x] 1.2 Write failing unit tests in `tests/test_frontmatter.py` covering: description+tags parse, no-fence → `{}`, partial/malformed → partial dict + no raise, colon/hash inside quotes preserved, `''` escape, nested mapping skipped, arbitrary input never raises

## 2. Cache Constant

- [x] 2.1 Add `_SKILL_INDEX_FILE = "__skill_index.json"` constant to `src/skills_mcp/cache.py`

## 3. MetadataRegistry Protocol and CachingRegistry

- [x] 3.1 Add `MetadataRegistry(RegistryAdapter, Protocol)` to `src/skills_mcp/registries/__init__.py` with `list_skills_metadata(*, refresh: bool = False) -> list[dict[str, object]]` and `fetch_skill(skill: str, *, refresh: bool = False) -> SkillContent`
- [x] 3.2 Add `self._index_lock: anyio.Lock` to `CachingRegistry.__init__`
- [x] 3.3 Extend `CachingRegistry.fetch_skill` with `refresh: bool = False` keyword: when `True`, skip cache read, fetch from `_inner`, write fresh result back to per-skill cache entry
- [x] 3.4 Implement `CachingRegistry.list_skills_metadata(*, refresh: bool = False)`: acquire `_index_lock`; determine authoritative names (cached or bypass per `refresh`); load index from `DiskCache` (miss/TTL-expired → empty); retire deleted skills; gather `to_fetch`; fan out `fetch_skill` calls concurrently (anyio task group with per-skill error isolation); parse frontmatter per D1, apply D7 identifier-wins; persist reconciled index; return sorted listing
- [x] 3.5 Update `build_adapters` return type to `dict[str, MetadataRegistry]`
- [x] 3.6 Write failing unit tests in `tests/test_skill_index.py` covering: new skill added to index, deleted skill retired, existing entry reused (no upstream call), TTL-miss causes rebuild, fetch-failure → name-only not persisted, parse-failure → persisted, `refresh=True` rebuilds from empty, concurrent calls serialised

## 4. Dispatcher

- [x] 4.1 Add `Dispatcher.list_skills_metadata(registry: str, *, refresh: bool = False) -> list[dict[str, object]]` routing to `adapter.list_skills_metadata(refresh=refresh)`
- [x] 4.2 Extend `Dispatcher.get_skill` to accept `refresh: bool = False` and thread it to `fetch_skill(skill, refresh=refresh)` when `file` is absent

## 5. Server Tools

- [x] 5.1 Rewrite `list_skills` MCP tool: signature `(registry: str, refresh_cache: bool = False) -> str`; calls `_disp().list_skills_metadata(registry, refresh=refresh_cache)`; catches `RegistryUnavailableError` as before; update `description=` to advertise dict shape, `refresh_cache`, and the "warm-index = no upstream blob fetch" behaviour
- [x] 5.2 Extend `get_skill` MCP tool: add `refresh_cache: bool = False` parameter; thread to `_disp().get_skill(..., refresh=refresh_cache)`; update `description=` to document the `refresh_cache` parameter

## 6. Tests

- [x] 6.1 Update any existing tests that assert `list_skills` returns `list[str]` to expect `list[dict]`
- [x] 6.2 Add integration-level test: `list_skills` warm path returns correct dict shape and no upstream fetch; `list_skills` with `refresh_cache=True` re-fetches
- [x] 6.3 Add integration-level test: `get_skill` with `refresh_cache=True` re-fetches and warms cache

## 7. Lint and Type Check

- [x] 7.1 Run `uv run ruff check src/ tests/` and fix all lint errors
- [x] 7.2 Run `uv run mypy src/` and fix all type errors
- [x] 7.3 Run `uv run pytest tests/ -q` and confirm all tests pass
