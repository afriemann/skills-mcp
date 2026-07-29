## 1. Path validation helpers

- [x] 1.1 Extract shared path-normalisation logic from `_validate_file_path` into a reusable
      `_validate_path(value, label)` helper that rejects empty, absolute, and `..`-escaping
      paths with a descriptive `PathTraversalError`
- [x] 1.2 Add `_validate_skill_path(skill)` that delegates to the shared helper and raises
      `PathTraversalError` for any unsafe `skill` value (covers the new agent-supplied path
      traversal vector)
- [x] 1.3 Write failing tests: empty skill, absolute skill (`/etc/passwd`), `..`-escaping
      skill (`../secrets`), valid flat (`my-skill`) and valid nested
      (`engineering/testing/tdd`) — all via `_validate_skill_path`

## 2. Tree SHA resolution helper

- [x] 2.1 Implement `_get_tree_sha_for_dir(path: str) -> str` that splits the path into
      parent + name, calls `_get_contents(parent)`, finds the directory entry, and returns
      its `sha`; propagates `_NotFoundError` on a 404 parent or missing entry
- [x] 2.2 Handle the `skills_dir == ""` (repo-root) edge case via Option B:
      `GET /repos/{o}/{r}/commits/{ref}` → `commit.tree.sha`
- [x] 2.3 Write failing tests: flat dir (parent = root), nested dir
      (`skills/engineering/testing`, looking up `tdd-development`), missing parent (404),
      entry absent (name not in listing), and root case

## 3. `list_skills` rewrite

- [x] 3.1 Replace the one-level Contents scan with: resolve `skills_dir` tree SHA via
      `_get_tree_sha_for_dir` → `_get_tree_recursive` → filter blobs ending `/SKILL.md`
      → strip the `/SKILL.md` suffix → `prune_nested` → `sorted()`
- [x] 3.2 Implement `_prune_nested(candidates: list[str]) -> list[str]` that drops any
      candidate whose parent directory is itself a candidate (keeps shallowest SKILL.md
      on each ancestor path); add a DEBUG log for each pruned phantom
- [x] 3.3 Reword the `_get_tree_recursive` `truncated` warning in the `list_skills` context
      to say that skills (not just companion files) may be missing
- [x] 3.4 Write failing tests: flat layout (returns same names as today), nested layout
      (slash-delimited names), mixed flat+nested, non-skill subdirs excluded, bundled
      `SKILL.md` pruned, empty `skills_dir` (root)

## 4. `fetch_skill` and `fetch_file` rewrite

- [x] 4.1 Add `_validate_skill_path(skill)` call at the top of both `fetch_skill` and
      `fetch_file` before any I/O
- [x] 4.2 Replace the two-step `_get_contents(skills_dir)` + entry-lookup in `fetch_skill`
      with `_get_tree_sha_for_dir(f"{skills_dir}/{skill}".strip("/"))`, applying the
      error-classification matrix from the design: 404 with parent == `skills_dir` →
      `RegistryUnavailableError`; otherwise → `SkillNotFoundError`
- [x] 4.3 Apply the same replacement in `fetch_file`
- [x] 4.4 Write failing tests: nested `fetch_skill` (slash-delimited name), nested
      `fetch_file`, traversal rejection via `skill` in both methods, missing nested skill
      returns `SkillNotFoundError`, missing `skills_dir` returns `RegistryUnavailableError`

## 5. Existing tests stay green

- [x] 5.1 Run the full test suite and confirm all pre-existing flat-adapter tests still pass
      (no fixture changes should be required; verify `_skills_dir_response` and
      `_skill_tree_response` fixtures are still exercised by the updated code)
- [x] 5.2 Run `ruff check` and `mypy` — fix any lint or type errors introduced by the change

## 6. Documentation

- [x] 6.1 Check whether the README's "GitHub repository layout" section implies flat-only;
      if so, update it to show a nested example and note the slash-delimited skill name
