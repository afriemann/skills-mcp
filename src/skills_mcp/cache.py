"""Read-through disk cache for skills-mcp.

Cache root: platform cache dir / skills-mcp (0700), e.g. ~/.cache/skills-mcp on Linux.
Atomic writes: temp file + os.replace().
TTL: mtime-based (no sidecar metadata).
Immutable (SHA refs): never expire.
"""

from __future__ import annotations

import logging
import os
import stat
import time
import uuid
from pathlib import Path, PurePosixPath

logger = logging.getLogger(__name__)

# Sentinel filenames used for list_skills and fetch_skill results
_SKILLS_LIST_FILE = "__skills.json"
_SKILL_CONTENT_FILE = "__skill.json"


def _percent_encode(component: str) -> str:
    """Percent-encode characters unsafe in filesystem paths (preserves [a-zA-Z0-9._-])."""
    safe = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
    return "".join(ch if ch in safe else f"%{ord(ch):02X}" for ch in component)


class DiskCache:
    """Disk-backed cache with atomic writes and mtime-based TTL.

    Key hierarchy on disk:
        <root>/<registry>/<ref>/<skill>/<artifact>

    where:
      - ``registry``, ``ref``, and ``skill`` are percent-encoded.
      - ``<skill>/__skills.json``  → list_skills result
      - ``<skill>/__skill.json``   → fetch_skill result (SkillContent as JSON)
      - ``<skill>/<file_path>``    → fetch_file result (raw text, nested dirs preserved)
    """

    def __init__(self, cache_dir: Path, *, enabled: bool = True, ttl_seconds: int = 3600) -> None:
        self._root = cache_dir
        self._enabled = enabled
        self._ttl = ttl_seconds
        if enabled:
            self._ensure_root()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get(
        self,
        registry: str,
        ref: str,
        skill: str,
        artifact: str,
        *,
        immutable: bool,
    ) -> bytes | None:
        """Return cached bytes, or *None* on miss/expiry/disabled."""
        if not self._enabled:
            return None
        path = self._path(registry, ref, skill, artifact)
        if not path.exists():
            return None
        if not immutable:
            try:
                mtime = path.stat().st_mtime
            except OSError:
                return None
            if (time.time() - mtime) > self._ttl:
                return None
        try:
            return path.read_bytes()
        except OSError as exc:
            logger.warning("cache read failed for %s: %s", path, exc)
            return None

    def put(
        self,
        registry: str,
        ref: str,
        skill: str,
        artifact: str,
        data: bytes,
    ) -> None:
        """Atomically write *data* to the cache.  Errors are logged but not raised."""
        if not self._enabled:
            return
        path = self._path(registry, ref, skill, artifact)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.parent / f".tmp-{uuid.uuid4().hex}"
            tmp.write_bytes(data)
            try:
                tmp_fd = os.open(tmp, os.O_WRONLY)
                try:
                    os.fsync(tmp_fd)
                finally:
                    os.close(tmp_fd)
            except OSError:
                pass  # fsync best-effort
            os.replace(tmp, path)
        except OSError as exc:
            logger.warning("cache write failed for %s: %s", path, exc)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _path(self, registry: str, ref: str, skill: str, artifact: str) -> Path:
        """Convert logical key components to an absolute filesystem path.

        *artifact* may contain '/' for nested file paths (e.g. ``references/guide.md``).
        """
        enc_reg = _percent_encode(registry)
        enc_ref = _percent_encode(ref)
        enc_skill = _percent_encode(skill)
        # Keep internal slashes in artifact (mirrors skill directory layout)
        art_path = PurePosixPath(artifact)
        return self._root / enc_reg / enc_ref / enc_skill / Path(*art_path.parts)

    def _ensure_root(self) -> None:
        """Create the cache root with mode 0700, defeating the umask."""
        self._root.mkdir(parents=True, exist_ok=True)
        try:
            self._root.chmod(stat.S_IRWXU)
        except OSError as exc:
            logger.warning("could not set cache dir permissions: %s", exc)
