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
    stderr_log = tmp_path / "stderr.log"
    client_end, server_end = socket.socketpair()
    proc = subprocess.Popen(
        [sys.executable, "-m", "skills_mcp", "--config", str(config)],
        stdin=server_end.fileno(),
        stdout=subprocess.DEVNULL,
        stderr=stderr_log.open("wb"),
    )
    server_end.close()
    client_end.close()
    try:
        assert proc.wait(timeout=_EXIT_TIMEOUT_SECONDS) == 0, stderr_log.read_text()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
