## 1. Config Model

- [x] 1.1 Add `instructions: str | None = None` to `GithubRegistry` in `config/model.py`
- [x] 1.2 Add `instructions: str | None = None` to `HttpRegistry` in `config/model.py`

## 2. Config Parsing

- [x] 2.1 Parse `instructions` in `_parse_github_registry` in `config/loader.py` (clone of `description` pattern)
- [x] 2.2 Parse `instructions` in `_parse_http_registry` in `config/loader.py` (clone of `description` pattern)

## 3. Tests (red step)

- [x] 3.1 Write failing tests for `_build_list_registries_description` covering all six scenarios in the spec
- [x] 3.2 Write failing tests for `instructions` config parsing (GitHub and HTTP registries, with/without field)

## 4. Description Assembly

- [x] 4.1 Extract `_build_list_registries_description(cfg: Config) -> str` as a module-level pure function in `server.py`
- [x] 4.2 Register `list_registries` tool using `_build_list_registries_description(cfg)` as its `description=` parameter

## 5. Verify

- [x] 5.1 Run `uv run pytest tests/ -q` — all tests pass
- [x] 5.2 Run `uv run ruff check src/ tests/` — no lint errors
- [x] 5.3 Run `uv run mypy src/` — no type errors
