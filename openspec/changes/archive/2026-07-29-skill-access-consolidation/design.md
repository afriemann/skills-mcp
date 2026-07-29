# Design — skill-access-consolidation

Design companion to `proposal.md`. Covers *how* the four consolidation changes
land against the existing layered architecture; does not restate the *what/why*.

## Ground-truth corrections to the proposal

Three names/paths in the proposal do not match the current code. The engineer
must follow reality here:

- The registry dataclasses are **`GithubRegistry`** and **`HttpRegistry`**
  (`config/model.py`), not `GithubRegistryConfig` / `HttpRegistryConfig`. Add
  `description` to those two classes.
- Adding the field to the model is not enough — **`config/loader.py`** must
  parse it too, in `_parse_github_registry` and `_parse_http_registry`. The
  proposal's code-impact list omits `loader.py`; it is in scope.
- `adapter.type` is a **class attribute** (`type = "github"` / `"http"`);
  `name`/`ref` are instance attributes. Description does **not** join them (see
  "Config → list_registries flow").

## Where each change lives

Every change is confined to the top two layers plus the config model/loader. The
fetch/cache/auth core (L0–L2 adapters) is untouched — the design's central
constraint.

| Change | Layer / file | Why here |
|---|---|---|
| `get_skill` gains `file`; `get_skill_file` tool removed | L4 `server.py` | Tool registration and the MCP boundary live only here |
| URL-decode of `file` | L4 `server.py` | Boundary responsibility — dispatch stays byte-exact |
| Resource template `skill://…` + handler | L4 `server.py` | Resource registration is a FastMCP boundary concern |
| `description` surfaced in `list_registries` | L3 `dispatch.py` (+ wiring in `server.py`) | `list_registries` is assembled in the Dispatcher |
| `description` field | L1 `config/model.py` + `config/loader.py` | Model shape + JSONC parsing |
| Richer tool descriptions | L4 `server.py` | Descriptions are tool-registration text |

`dispatch.get_skill_file()` **stays** as an internal method — it is now called
by the `get_skill` tool's file-branch and by the resource handler, but is no
longer bound as its own MCP tool. Only the `@mcp.tool` registration is deleted.

## `get_skill` unified call flow

Single tool, one optional parameter, two return shapes. The branch is decided at
the L4 boundary; the Dispatcher keeps its two existing methods unchanged.

```
get_skill(registry, skill, file: str | None = None) -> str
│
├─ file is None ──▶ dispatch.get_skill(registry, skill)      → fetch_skill
│                   returns JSON  {"content": str, "files": [str]}
│
└─ file present ──▶ file = urllib.parse.unquote(file)
                    dispatch.get_skill_file(registry, skill, file)  → fetch_file
                    returns RAW TEXT (no JSON envelope)
```

Key decisions:

- **No `fetch_skill` pre-call on the file path.** `file` routes straight to
  `fetch_file`; the file list is not needed to fetch a known path, and
  `fetch_file` already raises `SkillFileNotFoundError` when the path is absent.
- **Return type is `str` in both branches** — a JSON document string when
  `file is None`, raw file text otherwise. This preserves the exact shapes the
  two old tools returned, so migration is a pure parameter rename.
- **Decode lives at the boundary only.** `unquote` is applied in `server.py`
  before the dispatch call. `dispatch`/adapters receive an already-decoded path
  and are not modified. `RegistryUnavailableError` is caught here exactly as
  today and returned as `"Error: …"` (raw-text branch) or `{"error": …}` (JSON
  branch, when `file is None`).

## Resource template `skill://{registry}/{+skill}{?file}`

### URI scheme

- `{+skill}` is a reserved-expansion segment: it preserves `/`, so a nested
  skill name survives without client-side encoding. The MCP SDK's default path
  safety rejects `..` on this segment automatically — no `ResourceSecurity`
  exemption is added.
- `{?file}` is an optional trailing query variable. Its handler parameter
  therefore **must** carry a Python default: `file: str | None = None`.
- Clients percent-encode `/` inside `file` as `%2F`
  (`skill://reg/my-skill?file=references%2Fguide.md`).

### Handler wiring

```
@mcp.resource("skill://{registry}/{+skill}{?file}")
async def skill_resource(registry, skill, file: str | None = None) -> str
│
├─ file is None ──▶ dispatch.get_skill(registry, skill).content   (raw SKILL.md text)
└─ file present ──▶ dispatch.get_skill_file(registry, skill, unquote(file))
```

- **Resources return raw text, never the JSON envelope.** When `file is None`
  the handler returns only `SkillContent.content` (the SKILL.md body); the
  `files` list is intentionally dropped, because a resource read yields document
  text, not a discovery envelope. This is the one place the resource and the
  `get_skill` tool diverge: the tool wraps `{content, files}`, the resource does
  not. Callers that need the file list use the tool.
- **FastMCP does not auto-decode query params** — the handler calls
  `urllib.parse.unquote(file)` itself, mirroring the tool. The `{+skill}`
  segment is decoded by the SDK's template expansion and is not re-decoded.
- Discovery: the template is advertised by **`list_resource_templates`**;
  `list_resources` stays empty (there is no fixed enumerable resource set).

### Error surface

Resources have no "catch-and-return-string" boundary like tools do; FastMCP
turns raised exceptions into error content items only for the recognised
`ValueError` family. Therefore:

- `ValueError` subclasses (`SkillNotFoundError`, `SkillFileNotFoundError`,
  `PathTraversalError`, `UnsupportedOperationError`, `RegistryNotFoundError`)
  propagate as-is → surfaced as `is_error` content items.
- **`RegistryUnavailableError` is caught at the resource boundary and re-raised
  as a `ValueError`** (message preserved), because it is *not* a `ValueError`
  and would otherwise escape as an unclassified error. This is the resource-side
  analogue of the tool boundary's `"Error: …"` conversion.

## Config → `list_registries` flow

`description` is optional metadata that plays no part in fetching or caching. How
it reaches the `list_registries` output is the one non-trivial decision here.

**Option A — thread through the adapter protocol.** Add `description` to the
`RegistryAdapter` Protocol, set `self.description` in both adapters, re-expose it
in `CachingRegistry` (mirroring `name`/`type`/`ref`). `dispatch.list_registries`
reads `adapter.description`.
*Trade-off:* consistent with the existing metadata fields, but touches L2 — the
Protocol, both adapter classes, and the caching decorator — to carry a value
none of them use. Widens the fetch-oriented adapter surface with a
presentation-only concern.

**Option B — Dispatcher holds a name→description map (recommended).** `server.py`
builds `{name: cfg_entry.description}` from `cfg.registries` in the lifespan and
passes it to `Dispatcher(adapters, descriptions=…)`. `list_registries` adds
`description` to each entry from that map when non-`None`.
*Trade-off:* the Dispatcher constructor grows one argument, but L2 stays
completely untouched and the config-metadata concern stays out of the fetch
path. Description lives with the other config-derived presentation logic.

**Recommendation: Option B.** It honours the "adapters untouched" constraint,
keeps `description` (pure config presentation) off the fetch/cache protocol, and
matches the proposal's own code-impact set (`server.py`, `dispatch.py`,
`config/model.py` — plus `loader.py`). Output contract: `description` is included
in a registry's entry **only when set** — absent, not `null`, when unconfigured,
consistent with how `ref` is already omitted for HTTP registries.

Model change is a backward-compatible optional field:

```python
description: str | None = None   # on GithubRegistry and HttpRegistry, independently
```

No shared base class (proposal is explicit). `dataclasses.replace()` is not
needed in production wiring — the loader constructs each instance once with the
parsed value; `replace()` is only relevant if tests build variants.

## Tool-description style

Applied to all three surviving tool descriptions:

- **State the return shape precisely** — type and, for JSON, the keys
  (`list_registries` → array of `{name, type, ref?, description?}`).
- **State the next step** — e.g. `get_skill` notes that a companion file is
  fetched with the `file` parameter, and that the `skill://` scheme is
  discoverable via `list_resource_templates`.
- **Name the divergent branches** — `get_skill` returns JSON when `file` is
  omitted and raw text when supplied; say so.
- **Do not** document internal layering, caching, adapter mechanics, or error
  taxonomy internals. Describe observable behaviour only.
- Remove the `get_skill_file` reference from `get_skill`'s current description
  and the tool itself.

## What stays unchanged

- **Adapters** (`registries/github.py`, `registries/http.py`) — no edits;
  `fetch_skill` / `fetch_file` signatures and behaviour are stable.
- **Caching** (`CachingRegistry`) and **auth** (`AuthResolver`) — untouched; the
  file path already flows through `fetch_file`'s existing cache key.
- **Dispatcher fetch methods** — `get_skill` / `get_skill_file` keep their
  signatures; only `list_registries` and the constructor change (Option B).
- **Error taxonomy** (`errors.py`) — reused as-is; no new error types.
- **`HttpAdapter.fetch_file`** — still raises `UnsupportedOperationError`; via
  the new `file` param and the resource, this correctly surfaces as
  `is_error=True`.

## Resilience & failure modes

- **Blast radius:** confined to L3–L4 and config; the fetch/cache/auth core is
  not on the change path, so existing skill/file retrieval behaviour is
  regression-isolated to the boundary wiring.
- **Breaking change:** `get_skill_file` tool removal is intentional and
  guarded only by the trivial rename; no runtime failure mode — an old caller
  gets a "tool not found" from the MCP layer.
- **Malformed URIs:** unknown `registry` → `RegistryNotFoundError`; bad `file`
  path → `SkillFileNotFoundError`; `..` traversal → SDK-blocked on `{+skill}`,
  `PathTraversalError` on `file`. All are model-recoverable.
- **Registry down:** `RegistryUnavailableError` — returned as error string
  (tools) or re-raised as `ValueError` (resource); one registry's outage does
  not affect others (per-adapter isolation is unchanged).
- **Recovery:** no migration/state; the change is code-only. Rollback is
  reverting the diff.

## Component breakdown

Each part with its work-kind (all application code, Python) and done-criterion.
No agent assignment; no task sequencing.

1. **Config model** — add `description: str | None = None` to `GithubRegistry`
   and `HttpRegistry`. *Done:* both frozen dataclasses accept and default the
   field; existing construction sites unaffected.
2. **Config loader** — parse optional `description` in `_parse_github_registry`
   and `_parse_http_registry`. *Done:* a registry with a `description` in JSONC
   yields a model instance carrying it; absence yields `None`.
3. **Dispatcher** — accept a `descriptions` map (Option B); include
   `description` in each `list_registries` entry when non-`None`; update the
   docstring's tool-count. *Done:* `list_registries()` output carries
   `description` for configured registries and omits it otherwise.
4. **`get_skill` tool** — add `file: str | None = None`; branch to
   `fetch_skill` (JSON) or `unquote`+`get_skill_file` (raw text); remove the
   `get_skill_file` tool registration; build and pass the descriptions map in
   the lifespan. *Done:* single tool serves both shapes; `get_skill_file` no
   longer appears in the tool list.
5. **Resource template** — register `skill://{registry}/{+skill}{?file}`; handler
   returns raw SKILL.md text or raw file text, `unquote`s `file`, and re-raises
   `RegistryUnavailableError` as `ValueError`. *Done:*
   `list_resource_templates` advertises the template; `read_resource` resolves
   both a skill and a companion-file URI; `list_resources` stays empty.
6. **Tool descriptions** — rewrite all three per the style rules above. *Done:*
   descriptions state return shape and next step; no `get_skill_file` mention.
7. **Docs** — update `README.md` (tools table 4→3, `get_skill` `file` param,
   `skill://` scheme + `list_resource_templates`, per-registry `description`
   config example, opencode permission names). *Done:* README matches the new
   3-tool + resource surface.

Tests (`tests/test_integration.py`, `tests/test_adapters.py`) are the engineer's
under the TDD flow: migrate the five `get_skill_file` cases to
`get_skill(..., file=…)`, add resource-template + `read_resource` cases, add a
`description` surfacing case. No user-facing UI surface — no `ui-designer` pass.

## Research needs

None outstanding. All FastMCP template facts (`{+skill}`, `{?file}`, no
auto-decode, default `..` blocking, `ValueError` error surfacing) were supplied
in the task prompt as confirmed; no version/API fact was asserted from training
data.
