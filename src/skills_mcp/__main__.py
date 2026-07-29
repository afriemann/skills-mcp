"""Entry point for skills-mcp server."""

from __future__ import annotations

import argparse
import logging
import sys

import anyio

from .server import _run_with_graceful_shutdown, build_app


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="skills-mcp",
        description="MCP server for fetching skills from remote registries",
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        help="Path to config.jsonc (default: platform config dir / skills-mcp / config.jsonc)",
    )
    parser.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level (default: WARNING)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        stream=sys.stderr,
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    from pathlib import Path

    config_path = Path(args.config) if args.config else None
    app = build_app(config_path=config_path)
    anyio.run(_run_with_graceful_shutdown, app)


if __name__ == "__main__":
    main()
