# Proposal

## Why

Agents can read remote skills but cannot inspect repository-wide tooling or discover the configured source after an operator updates configuration and restarts the server following a repository rename. This forces separate source discovery and checkout even when reading tooling would suffice.

## What Changes

- Add `get_registry_source`, `list_repo_entries` and `read_repo_text_file` for configured GitHub registries, including paths outside skill directories; HTTP registries remain unsupported for these operations.
- Keep repository access read-only and bounded to the configured repository and ref; new reads bypass disk caching while existing skill tools and caching remain unchanged.
- Cover repository path, strict text/file-type, retrieval-size and incomplete-listing boundaries with actionable failures, without following symlinks or submodules.
- Leave configuration editing and restart requirements unchanged. Exclude automatic rename resolution, command execution, local checkout management, writes, arbitrary sources and dependencies.

## Capabilities

### Modified Capabilities

- `skills-mcp`: extend the public tool surface with configured GitHub source information and bounded repository browsing.

## Impact

Changes affect the server, dispatcher, registry adapter contract and implementations, shared limits/errors, adapter/cache/integration tests and README. Repository-wide reads expose tracked text files beyond skill roots using existing registry credentials; this broader read boundary is explicitly approved. No authentication configuration or existing skill response changes are intended.
