## 1. server.py

- [x] 1.1 Rename `_build_list_registries_description` → `_build_list_skills_description`; update static intro text to match `list_skills`
- [x] 1.2 Remove `list_registries` tool (`@mcp.tool` block and its function)
- [x] 1.3 Register `list_skills` with `description=_build_list_skills_description(cfg)`

## 2. dispatch.py

- [x] 2.1 Remove `list_registries()` method from `Dispatcher`
- [x] 2.2 Remove `descriptions` parameter from `Dispatcher.__init__`; remove `descriptions` dict from lifespan wiring in `server.py`

## 3. Tests (red step)

- [x] 3.1 Update `test_registry_instructions.py`: rename import and all references from `_build_list_registries_description` → `_build_list_skills_description`; update test names to match new scenario titles
- [x] 3.2 Remove or update integration tests that call the `list_registries` tool
- [x] 3.3 Add integration test asserting `list_registries` is NOT in the advertised tool list

## 4. Verify

- [x] 4.1 Run `uv run pytest tests/ -q` — all tests pass
- [x] 4.2 Run `uv run ruff check src/ tests/` — no lint errors
- [x] 4.3 Run `uv run mypy src/` — no type errors
