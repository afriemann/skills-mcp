# Tasks: skill-access-consolidation

## 1. Config model

- [ ] 1.1 Add `description: str | None = None` field to `GithubRegistry` frozen dataclass in `config/model.py`
- [ ] 1.2 Add `description: str | None = None` field to `HttpRegistry` frozen dataclass in `config/model.py`
- [ ] 1.3 Update `_parse_github_registry` in `config/loader.py` to read optional `description` key
- [ ] 1.4 Update `_parse_http_registry` in `config/loader.py` to read optional `description` key

## 2. Dispatcher

- [ ] 2.1 Update `Dispatcher.list_registries()` in `dispatch.py` to include `description` in each registry dict (omit key when `None`)
- [ ] 2.2 Update `Dispatcher.get_skill()` signature in `dispatch.py` to accept `file: str | None = None`; when `file` is present route directly to `get_skill_file` (no prior `fetch_skill` call); when absent, keep existing behaviour
- [ ] 2.3 Update `dispatch.py` docstring/comment to reflect 3 tool operations (remove "four")

## 3. Server — tool consolidation

- [ ] 3.1 Remove the `get_skill_file` tool registration from `server.py`
- [ ] 3.2 Add `file: str | None = None` parameter to the `get_skill` tool in `server.py`; when `file` is present: call `urllib.parse.unquote(file)`, route to `_disp().get_skill(..., file=decoded)`, return raw text; when absent: keep existing JSON-envelope behaviour
- [ ] 3.3 Update all tool `description=` strings to be richer and more actionable (aws-mcp style); note `list_resource_templates` as discovery path in `get_skill` description
- [ ] 3.4 Update `build_app` docstring to reflect 3 tools

## 4. Server — resource template

- [ ] 4.1 Register resource template `skill://{registry}/{+skill}{?file}` in `server.py` using `@mcp.resource(...)`; handler calls `_disp().get_skill(registry, skill, file=unquote(file))` for skill or `_disp().get_skill(registry, skill)` depending on `file`; catch `RegistryUnavailableError` and re-raise as `ValueError`; return raw text in both cases

## 5. Tests (red → green)

- [ ] 5.1 Write failing test `test_tool_list_is_exactly_three` asserting tool names are `{list_registries, list_skills, get_skill}` (replaces `test_tool_list_is_exactly_four`)
- [ ] 5.2 Write failing test `test_resource_template_is_advertised` asserting `list_resource_templates` returns one template matching `skill://{registry}/{+skill}{?file}`
- [ ] 5.3 Write failing test `test_list_registries_returns_description` asserting `description` appears when configured
- [ ] 5.4 Write failing test `test_list_registries_omits_description_when_absent` asserting `description` key is absent when not configured
- [ ] 5.5 Write failing test `test_get_skill_with_file_returns_raw_text` asserting `get_skill(file=...)` returns raw companion file text (not JSON)
- [ ] 5.6 Write failing test `test_get_skill_with_file_url_decodes_percent_encoded_slash` asserting `file="references%2Fguide.md"` decodes correctly
- [ ] 5.7 Write failing test `test_get_skill_with_file_http_registry_is_error` asserting HTTP registry + `file` returns `is_error=True`
- [ ] 5.8 Write failing test `test_get_skill_with_file_traversal_is_error` asserting `..` in `file` returns `is_error=True`
- [ ] 5.9 Write failing test `test_read_resource_skill_md` asserting `read_resource("skill://registry/skill-a")` returns SKILL.md raw text
- [ ] 5.10 Write failing test `test_read_resource_companion_file` asserting `read_resource("skill://registry/skill-a?file=references%2Fguide.md")` returns companion file raw text
- [ ] 5.11 Write failing test `test_read_resource_unknown_registry_error_content` asserting unknown registry returns error content item (not crash)
- [ ] 5.12 Migrate `test_get_skill_file_github_returns_content` → delete or replace with new `test_get_skill_with_file_returns_raw_text` (task 5.5)
- [ ] 5.13 Migrate `test_get_skill_file_http_registry_is_error` → replaced by task 5.7
- [ ] 5.14 Migrate `test_get_skill_file_path_traversal_is_error` → replaced by task 5.8
- [ ] 5.15 Migrate `test_get_skill_file_unknown_path_is_error` → add equivalent test for `get_skill(file=...)` path
- [ ] 5.16 Delete `test_tool_list_is_exactly_four`; implement `test_tool_list_is_exactly_three` (task 5.1)
- [ ] 5.17 Run full test suite (`uv run pytest tests/ -q`) — all tests green

## 6. Linting and type checking

- [ ] 6.1 Run `uv run ruff check src/ tests/` — zero errors
- [ ] 6.2 Run `uv run mypy src/` — zero errors

## 7. Documentation

- [ ] 7.1 Update `README.md` tools table (remove `get_skill_file` row, add `file` param to `get_skill`, add resource template entry)
- [ ] 7.2 Update README opencode permission names (remove `skills_mcp_get_skill_file`)
- [ ] 7.3 Add `description` field example to README config snippet
