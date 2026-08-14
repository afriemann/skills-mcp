# Tasks: nested-skill-path-cache-test-coverage

- [x] Add `test_nested_path_identifier_preserved_verbatim_on_cold_index` to `tests/test_skill_index.py`
- [x] Add `test_nested_path_identifier_preserved_verbatim_from_warm_index` to `tests/test_skill_index.py`
- [x] Add `test_stale_flat_identifier_retired_when_registry_renames_skill_to_nested_path` to `tests/test_skill_index.py`
- [x] Run `uv run pytest tests/test_skill_index.py -q` and confirm all three new tests pass
- [x] Run `uv run ruff check src/ tests/` and `uv run mypy src/` — no errors
