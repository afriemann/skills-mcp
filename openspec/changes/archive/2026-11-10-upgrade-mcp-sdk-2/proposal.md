# Proposal

## Product intent

Actors: MCP-speaking agents (trusted) and the operator who configures registries. Job: browse and fetch skills and repository files from allow-listed remote registries over stdio. Must keep: the five tools, the `skill://` resource template, readable model-recoverable errors, isolation of one failing registry from others. Trust model: agents are trusted; registry content is untrusted data.

## Why

The server pins the MCP Python SDK to 1.x. SDK 2.x is the maintained line, and 1.x internals (private resource-manager injection) block upgrading.

## What Changes

- Depend on `mcp[cli]>=2.3.0,<3`.
- Move to the SDK's renamed server class and module tree.
- Model-recoverable errors reach the agent with readable messages through the SDK's tool and resource error types, since 2.x hides other exception text.
- Register the `skill://{registry}/{+skill}{?file}` template through the SDK's public API, deleting the custom template subclass and private-state injection.
- In-memory tests use the SDK's `Client`.

## Capabilities

### Modified Capabilities

- `skills-mcp`: requirements name no SDK; resource-read failures surface as protocol errors instead of "error content items".

## Impact

`pyproject.toml`, `uv.lock`, `src/skills_mcp/server.py`, `src/skills_mcp/errors.py`, tests, README and AGENTS.md wording.
