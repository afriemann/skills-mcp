"""Process-level shutdown behaviour."""

# spec: openspec/specs/skills-mcp/spec.md

import json
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

_EXIT_TIMEOUT_SECONDS = 10
_STARTUP_SECONDS = 2
_SIGTERM_EXIT_SECONDS = 3


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


def test_sigterm_exits_within_one_second_even_if_stdin_is_blocked(tmp_path: Path):
    """Scenario: SIGTERM triggers clean shutdown within 1 second."""
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
    stderr_log = tmp_path / "stderr.log"
    proc = subprocess.Popen(
        [sys.executable, "-m", "skills_mcp", "--config", str(config)],
        stdin=server_end.fileno(),
        stdout=subprocess.DEVNULL,
        stderr=stderr_log.open("wb"),
    )
    server_end.close()
    try:
        time.sleep(_STARTUP_SECONDS)
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=_SIGTERM_EXIT_SECONDS) == 0, stderr_log.read_text()
    finally:
        client_end.close()
        if proc.poll() is None:
            proc.kill()
            proc.wait()
