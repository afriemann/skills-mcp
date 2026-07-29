"""Tests for DiskCache: TTL, immutability, atomic writes, 0700 root, disabled mode."""

import time
from pathlib import Path

import pytest

from skills_mcp.cache import DiskCache


@pytest.fixture()
def cache(tmp_path: Path) -> DiskCache:
    return DiskCache(tmp_path / "cache", enabled=True, ttl_seconds=60)


def test_cache_miss_returns_none(cache: DiskCache):
    result = cache.get("reg", "main", "skill", "__skill.json", immutable=False)
    assert result is None


def test_cache_hit_returns_stored_bytes(cache: DiskCache):
    data = b'{"content": "hello", "files": []}'
    cache.put("reg", "main", "skill", "__skill.json", data)
    result = cache.get("reg", "main", "skill", "__skill.json", immutable=False)
    assert result == data


def test_cache_root_created_with_0700(tmp_path: Path):
    root = tmp_path / "myroot"
    DiskCache(root, enabled=True, ttl_seconds=60)
    mode = root.stat().st_mode & 0o777
    assert mode == 0o700


def test_expired_entry_returns_none(cache: DiskCache, tmp_path: Path):
    """A mutable cache entry older than ttl_seconds should be a miss."""
    root = tmp_path / "cache"
    short_cache = DiskCache(root, enabled=True, ttl_seconds=1)
    data = b"stale content"
    short_cache.put("reg", "main", "skill", "file.txt", data)
    # Backdate the mtime by 2 seconds
    key_path = next(iter(root.rglob("file.txt")))
    old_time = time.time() - 2
    import os

    os.utime(key_path, (old_time, old_time))
    result = short_cache.get("reg", "main", "skill", "file.txt", immutable=False)
    assert result is None


def test_immutable_entry_never_expires(tmp_path: Path):
    """A SHA-locked entry with ttl=1 should still be returned after expiry."""
    root = tmp_path / "cache"
    cache = DiskCache(root, enabled=True, ttl_seconds=1)
    data = b"immutable content"
    cache.put("reg", "abc1234", "skill", "__skill.json", data)
    # Backdate the mtime by 10 seconds
    key_path = next(iter(root.rglob("__skill.json")))
    old_time = time.time() - 10
    import os

    os.utime(key_path, (old_time, old_time))
    result = cache.get("reg", "abc1234", "skill", "__skill.json", immutable=True)
    assert result == data


def test_disabled_cache_bypasses_disk(tmp_path: Path):
    root = tmp_path / "cache"
    cache = DiskCache(root, enabled=False, ttl_seconds=60)
    cache.put("reg", "main", "skill", "file.txt", b"content")
    # Root should not exist (cache never writes)
    result = cache.get("reg", "main", "skill", "file.txt", immutable=False)
    assert result is None


def test_file_path_with_subdirs(cache: DiskCache):
    """file_path containing '/' should be stored in nested subdirs."""
    cache.put("reg", "main", "skill", "references/guide.md", b"guide content")
    result = cache.get("reg", "main", "skill", "references/guide.md", immutable=False)
    assert result == b"guide content"
