"""Server wiring: build_app(), 3 MCP tools + 1 resource template, graceful shutdown runner."""

from __future__ import annotations

import json
import logging
import os
import re
import signal
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import anyio
import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.resources.templates import ResourceTemplate

from .auth import AuthResolver
from .config import load_config
from .dispatch import Dispatcher
from .errors import RegistryUnavailableError
from .registries import SkillContent, build_adapters

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0)

# URI template advertised to clients for skill resource access.
_SKILL_URI_TEMPLATE = "skill://{registry}/{+skill}{?file}"


class _SkillResourceTemplate(ResourceTemplate):
    """ResourceTemplate subclass supporting slash-containing skill paths and ?file query params.

    FastMCP 1.29.0's default ``matches`` uses ``[^/]+`` which rejects slashes.  This
    subclass replaces the match logic to allow any characters (including ``/``) in the
    ``skill`` capture group and extracts the optional ``file`` value from the query string.
    """

    def matches(self, uri: str) -> dict[str, Any] | None:
        """Return extracted params if *uri* matches ``skill://{registry}/{skill}[?file=…]``."""
        path, _, qs = uri.partition("?")
        m = re.fullmatch(r"skill://(?P<registry>[^/]+)/(?P<skill>.+)", path)
        if not m:
            return None
        d: dict[str, Any] = {
            "registry": m.group("registry"),
            "skill": m.group("skill"),
        }
        file_val: str | None = None
        for part in qs.split("&") if qs else []:
            if "=" in part:
                k, v = part.split("=", 1)
                if k == "file":
                    file_val = v
                    break
        d["file"] = file_val
        return d


def build_app(config_path: Path | None = None) -> FastMCP:
    """Build and return the FastMCP application.

    Loads config, wires adapters, and registers three tools and one resource template.
    Exits via sys.exit(1) on any config error (before the MCP handshake).
    """
    cfg = load_config(config_path)
    auth_resolver = AuthResolver()

    # Mutable box shared between lifespan (writer) and tools (readers).
    _dispatcher: list[Dispatcher] = []

    @asynccontextmanager
    async def lifespan(_app: FastMCP) -> AsyncIterator[None]:
        async with httpx.AsyncClient(
            timeout=_DEFAULT_TIMEOUT,
            follow_redirects=False,
        ) as client:
            adapters = build_adapters(cfg, client, auth_resolver)
            descriptions = {name: reg.description for name, reg in cfg.registries.items()}
            _dispatcher.append(Dispatcher(adapters, descriptions))
            try:
                yield
            finally:
                _dispatcher.clear()

    mcp: FastMCP = FastMCP(
        "skills-mcp",
        lifespan=lifespan,
    )

    def _disp() -> Dispatcher:
        if not _dispatcher:
            raise RuntimeError("Dispatcher not initialised — lifespan not started")
        return _dispatcher[0]

    # ------------------------------------------------------------------
    # Tool: list_registries
    # ------------------------------------------------------------------

    @mcp.tool(
        description=(
            "List all configured skill registries. "
            "Returns a JSON array of objects, one per registry, with: "
            "'name' (registry identifier), "
            "'type' ('github' or 'http'), "
            "optionally 'ref' (branch/tag/SHA for GitHub registries), "
            "and optionally 'description' (human-readable registry purpose, when configured). "
            "Call this first to discover available registries before listing or fetching skills."
        )
    )
    async def list_registries() -> str:
        return json.dumps(_disp().list_registries())

    # ------------------------------------------------------------------
    # Tool: list_skills
    # ------------------------------------------------------------------

    @mcp.tool(
        description=(
            "List the skill names available in a named registry. "
            "Skills are identified by their name — for GitHub registries: a slash-delimited "
            "path relative to skills_dir (e.g. 'engineering/testing/tdd-development'); "
            "for HTTP registries: the declared skill name. "
            "Returns a JSON array of objects, one per skill, each with at least 'name' "
            "and optionally 'description', 'tags', and other keys parsed from the skill's "
            "SKILL.md frontmatter. "
            "An incrementally-maintained DiskCache index is used so only new skills require "
            "upstream fetches; a warm index incurs no blob-fetch traffic. "
            "Set refresh_cache=true to bypass the index and re-fetch all skills from upstream. "
            "Use get_skill(registry, skill) to fetch the full SKILL.md content of a skill."
        )
    )
    async def list_skills(registry: str, refresh_cache: bool = False) -> str:
        try:
            result = await _disp().list_skills_metadata(registry, refresh=refresh_cache)
            return json.dumps(result)
        except RegistryUnavailableError as exc:
            return json.dumps({"error": f"Error: {exc}"})

    # ------------------------------------------------------------------
    # Tool: get_skill
    # ------------------------------------------------------------------

    @mcp.tool(
        description=(
            "Retrieve a skill's SKILL.md content and companion file list from a named registry. "
            "Skills provide workflows, best practices, procedures, and reference materials for agents. "
            "\n\n"
            "When called without 'file': returns a JSON object with "
            "'content' (the full SKILL.md text) and "
            "'files' (companion file paths relative to the skill root, "
            "e.g. ['references/guide.md']). For HTTP registries 'files' is always empty. "
            "\n\n"
            "When called with 'file' (a path from the 'files' list, "
            "e.g. 'references/guide.md'): returns the raw text of that companion file directly. "
            "Percent-encoded slashes are decoded automatically "
            "(e.g. 'references%2Fguide.md' → 'references/guide.md'). "
            "\n\n"
            "Set refresh_cache=true to bypass the per-skill disk cache and fetch fresh content "
            "from the upstream registry; the repaired result is written back to cache. "
            "refresh_cache is ignored when 'file' is provided. "
            "\n\n"
            "URI-based access: skills and companion files are also readable via the "
            "skill://{registry}/{skill}[?file=...] resource template "
            "(discover it with list_resource_templates)."
        )
    )
    async def get_skill(
        registry: str, skill: str, file: str | None = None, refresh_cache: bool = False
    ) -> str:
        try:
            if file is not None:
                decoded_file = unquote(file)
                raw = await _disp().get_skill(registry, skill, file=decoded_file)
                return raw if isinstance(raw, str) else json.dumps(raw)
            result = await _disp().get_skill(registry, skill, refresh=refresh_cache)
            assert isinstance(result, SkillContent)
            return json.dumps(result.to_dict())
        except RegistryUnavailableError as exc:
            if file is not None:
                return f"Error: {exc}"
            return json.dumps({"error": f"Error: {exc}"})

    # ------------------------------------------------------------------
    # Resource template: skill://{registry}/{+skill}{?file}
    #
    # FastMCP 1.29.0's @mcp.resource decorator validates that URI template
    # params exactly match function params using re.findall(r"{(\w+)}", uri),
    # which misses {+skill} and {?file}.  We bypass the decorator entirely:
    # create a _SkillResourceTemplate directly (no validation) and inject it
    # into the resource manager's internal template dict.
    # ------------------------------------------------------------------

    async def _skill_resource_fn(registry: str, skill: str, file: str | None = None) -> str:
        try:
            if file is not None:
                decoded_file = unquote(file)
                raw = await _disp().get_skill(registry, skill, file=decoded_file)
                return raw if isinstance(raw, str) else str(raw)
            result = await _disp().get_skill(registry, skill)
            assert isinstance(result, SkillContent)
            return result.content  # raw SKILL.md text (not a JSON envelope)
        except RegistryUnavailableError as exc:
            raise ValueError(f"Registry unavailable: {exc}") from exc

    skill_tmpl = _SkillResourceTemplate.from_function(
        fn=_skill_resource_fn,
        uri_template=_SKILL_URI_TEMPLATE,
        name="skill-resource",
        description=(
            "Access a skill's SKILL.md or a companion file by URI. "
            "Without ?file: returns the raw SKILL.md text. "
            "With ?file=references%2Fguide.md: returns the raw companion file text. "
            "Discover available skills with the list_skills tool."
        ),
    )
    mcp._resource_manager._templates[skill_tmpl.uri_template] = skill_tmpl

    return mcp


# ---------------------------------------------------------------------------
# Graceful shutdown runner (md-mcp pattern)
# ---------------------------------------------------------------------------


async def _run_with_graceful_shutdown(app: FastMCP) -> None:
    """Run the MCP server with a cooperative SIGTERM handler.

    On SIGTERM: signals the task group to cancel, then starts a 1-second
    watchdog that calls os._exit(0) so a blocked stdin reader cannot hang.
    """
    with anyio.open_signal_receiver(signal.SIGTERM) as signals:
        async with anyio.create_task_group() as tg:

            async def _serve() -> None:
                await app.run_stdio_async()

            async def _wait_for_term() -> None:
                async for _sig in signals:
                    logger.info("SIGTERM received; shutting down")

                    async def _watchdog() -> None:
                        await anyio.sleep(1.0)
                        os._exit(0)

                    tg.start_soon(_watchdog)
                    tg.cancel_scope.cancel()
                    break

            tg.start_soon(_serve)
            tg.start_soon(_wait_for_term)
