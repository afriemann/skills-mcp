"""Process-level shutdown behaviour."""

# spec: openspec/specs/skills-mcp/spec.md

import json
import socket
import subprocess
import sys
from pathlib import Path

_EXIT_TIMEOUT_SECONDS = 10


def test_server_exits_when_stdin_closes(tmp_path: Path):
    """Scenario: Server exits when the client closes stdin."""
    config = tmp_path / "skills-mcp.jsonc"
    config.write_text(
        json.dumps(
            {
                "registries": {
                    "r": {"type": "http", "url": "https://x.invalid/SKILL.md", "skill_name": "s"}
                },
                "cache": {"enabled": False},
            }
        )
    )
    client_end, server_end = socket.socketpair()
    proc = subprocess.Popen(
        [sys.executable, "-m", "skills_mcp", "--config", str(config)],
        stdin=server_end.fileno(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    server_end.close()
    client_end.close()
    try:
        assert proc.wait(timeout=_EXIT_TIMEOUT_SECONDS) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
