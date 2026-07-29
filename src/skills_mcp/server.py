"""Server wiring: build_app(), 4 MCP tools, graceful shutdown runner."""

from __future__ import annotations

import json
import logging
import os
import signal
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
import httpx
from mcp.server.fastmcp import FastMCP

from .auth import AuthResolver
from .config import load_config
from .dispatch import Dispatcher
from .errors import RegistryUnavailableError
from .registries import build_adapters

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0)


def build_app(config_path: Path | None = None) -> FastMCP:
    """Build and return the FastMCP application.

    Loads config, wires adapters, and registers the four tools.
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
            _dispatcher.append(Dispatcher(adapters))
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
            "Returns a JSON array of objects with 'name' (string), 'type' ('github' or 'http'), "
            "and optionally 'ref' (branch/tag/SHA for GitHub registries). "
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
            "Returns a JSON array of skill name strings. "
            "For GitHub registries: returns subdirectory names under skills_dir. "
            "For HTTP registries: returns a single-element array with the declared skill name. "
            "Use get_skill(registry, skill) to fetch the actual content of a skill."
        )
    )
    async def list_skills(registry: str) -> str:
        try:
            result = await _disp().list_skills(registry)
            return json.dumps(result)
        except RegistryUnavailableError as exc:
            return json.dumps({"error": f"Error: {exc}"})

    # ------------------------------------------------------------------
    # Tool: get_skill
    # ------------------------------------------------------------------

    @mcp.tool(
        description=(
            "Fetch a skill's SKILL.md text and its companion file list from a named registry. "
            "Returns a JSON object with: "
            "'content' (string — the full text of SKILL.md) and "
            "'files' (array of strings — companion file paths relative to the skill root, "
            "e.g. ['references/guide.md']). "
            "For HTTP registries 'files' is always empty. "
            "Use get_skill_file(registry, skill, file_path) to fetch a companion file."
        )
    )
    async def get_skill(registry: str, skill: str) -> str:
        try:
            result = await _disp().get_skill(registry, skill)
            return json.dumps(result.to_dict())
        except RegistryUnavailableError as exc:
            return json.dumps({"error": f"Error: {exc}"})

    # ------------------------------------------------------------------
    # Tool: get_skill_file
    # ------------------------------------------------------------------

    @mcp.tool(
        description=(
            "Fetch the raw text of one companion file for a skill in a GitHub registry. "
            "Parameters: registry (string), skill (string), file_path (string — path "
            "relative to the skill root as listed in get_skill's 'files' array, "
            "e.g. 'references/guide.md'). "
            "Not supported for HTTP registries. "
            "Returns the raw text content of the file."
        )
    )
    async def get_skill_file(registry: str, skill: str, file_path: str) -> str:
        try:
            return await _disp().get_skill_file(registry, skill, file_path)
        except RegistryUnavailableError as exc:
            return f"Error: {exc}"

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
