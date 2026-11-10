# Tasks

## 1. Migration

- [x] 1.1 Pin `mcp[cli]>=2.3.0,<3`, refresh `uv.lock`; `uv sync` succeeds
- [x] 1.2 Port in-memory tests to the SDK `Client`; error scenarios ("Unknown registry produces is_error result", "Unknown registry produces error content item") fail before the code change
- [x] 1.3 Move `server.py` to the renamed server class and module tree; register the resource template through the public decorator and delete `_SkillResourceTemplate`
- [x] 1.4 Translate model-recoverable and infrastructure errors to the SDK tool/resource error types at the server boundary; scenarios from 1.2 pass
- [x] 1.5 Update README, AGENTS.md and `errors.py` wording; `grep -ri fastmcp` over non-archive files returns nothing
- [x] 1.6 `uv run pytest`, `ruff check`, `ruff format --check` and `mypy src/` all pass
