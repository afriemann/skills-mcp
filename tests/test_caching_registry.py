# spec: openspec/specs/skills-mcp/spec.md
"""Tests for the CachingRegistry decorator (§Read-Through Disk Cache)."""

from pathlib import Path

import pytest

from skills_mcp.cache import DiskCache
from skills_mcp.errors import RegistryUnavailableError
from skills_mcp.registries import CachingRegistry, SkillContent

# ---------------------------------------------------------------------------
# Fake inner adapter
# ---------------------------------------------------------------------------


class FakeInnerAdapter:
    """Minimal RegistryAdapter stand-in with a call counter per operation."""

    type = "github"
    ref: str | None = "main"

    def __init__(self, name: str = "reg") -> None:
        self.name = name
        self.list_calls = 0
        self.fetch_calls = 0
        self.file_calls = 0
        self.repo_calls = 0

    async def get_registry_source(self) -> dict[str, object]:
        self.repo_calls += 1
        return {"call": self.repo_calls}

    async def list_repo_entries(self, path: str = "") -> dict[str, object]:
        self.repo_calls += 1
        return {"path": path, "call": self.repo_calls}

    async def read_repo_text_file(self, path: str) -> dict[str, object]:
        self.repo_calls += 1
        return {"path": path, "call": self.repo_calls}

    async def list_skills(self) -> list[str]:
        self.list_calls += 1
        return ["skill-a"]

    async def fetch_skill(self, skill: str) -> SkillContent:
        self.fetch_calls += 1
        return SkillContent(content="# Skill content", files=("references/guide.md",))

    async def fetch_file(self, skill: str, file_path: str) -> str:
        self.file_calls += 1
        return "guide content"


class FailOnFirstFetchAdapter(FakeInnerAdapter):
    """Raises RegistryUnavailableError on the first fetch_skill; succeeds after that."""

    def __init__(self) -> None:
        super().__init__()

    async def fetch_skill(self, skill: str) -> SkillContent:
        self.fetch_calls += 1
        if self.fetch_calls == 1:
            raise RegistryUnavailableError("upstream down")
        return SkillContent(content="# Recovered", files=())


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_caching(inner: FakeInnerAdapter, tmp_path: Path, enabled: bool = True) -> CachingRegistry:
    cache = DiskCache(tmp_path / "cache", enabled=enabled, ttl_seconds=3600)
    return CachingRegistry(inner, cache, immutable=False, enabled=enabled)


# spec: openspec/specs/skills-mcp/spec.md
@pytest.mark.parametrize("immutable", [False, True])
@pytest.mark.parametrize(
    "method", ["get_registry_source", "list_repo_entries", "read_repo_text_file"]
)
async def test_repository_operations_bypass_disk_cache(tmp_path, monkeypatch, method, immutable):
    inner = FakeInnerAdapter()
    cache = DiskCache(tmp_path / "cache", enabled=True, ttl_seconds=3600)

    def forbidden(*args, **kwargs):
        pytest.fail("Repository operation accessed the disk cache")

    monkeypatch.setattr(cache, "get", forbidden)
    monkeypatch.setattr(cache, "put", forbidden)
    registry = CachingRegistry(inner, cache, immutable=immutable, enabled=True)
    args = () if method == "get_registry_source" else ("tools/check.py",)
    first = await getattr(registry, method)(*args)
    second = await getattr(registry, method)(*args)
    assert first.get("call") == 1
    assert second.get("call") == 2
    if args:
        assert second["path"] == args[0]


# ---------------------------------------------------------------------------
# Scenario: Subsequent call returns cached result (BLOCKER fix)
# ---------------------------------------------------------------------------


async def test_cache_hit_skips_inner_adapter(tmp_path: Path):
    """A second fetch_skill call within TTL must return the cached value without
    calling the inner adapter again."""
    inner = FakeInnerAdapter()
    caching = _make_caching(inner, tmp_path)

    r1 = await caching.fetch_skill("skill-a")
    r2 = await caching.fetch_skill("skill-a")

    assert inner.fetch_calls == 1, "inner adapter should be called exactly once"
    assert r1.content == r2.content == "# Skill content"


async def test_list_skills_cache_hit_skips_inner(tmp_path: Path):
    """list_skills is also cached; second call should not hit the inner adapter."""
    inner = FakeInnerAdapter()
    caching = _make_caching(inner, tmp_path)

    r1 = await caching.list_skills()
    r2 = await caching.list_skills()

    assert inner.list_calls == 1
    assert r1 == r2 == ["skill-a"]


async def test_fetch_file_cache_hit_skips_inner(tmp_path: Path):
    """fetch_file results are also cached per (registry, ref, skill, path)."""
    inner = FakeInnerAdapter()
    caching = _make_caching(inner, tmp_path)

    r1 = await caching.fetch_file("skill-a", "references/guide.md")
    r2 = await caching.fetch_file("skill-a", "references/guide.md")

    assert inner.file_calls == 1
    assert r1 == r2 == "guide content"


# ---------------------------------------------------------------------------
# Scenario: Failed upstream fetch is not cached (BLOCKER fix)
# ---------------------------------------------------------------------------


async def test_error_is_not_cached(tmp_path: Path):
    """An error from the inner adapter must not be written to cache; the next
    call must attempt the upstream again (not serve a bad cache entry)."""
    inner = FailOnFirstFetchAdapter()
    caching = _make_caching(inner, tmp_path)

    with pytest.raises(RegistryUnavailableError):
        await caching.fetch_skill("skill-a")  # first call → error

    result = await caching.fetch_skill("skill-a")  # second call → hits inner again
    assert result.content == "# Recovered"
    assert inner.fetch_calls == 2, "inner should have been called twice (error was not cached)"


# ---------------------------------------------------------------------------
# Scenario: Cache is bypassed when disabled per-registry
# ---------------------------------------------------------------------------


async def test_disabled_caching_always_hits_inner(tmp_path: Path):
    """With caching disabled, every call must reach the inner adapter."""
    inner = FakeInnerAdapter()
    caching = _make_caching(inner, tmp_path, enabled=False)

    await caching.fetch_skill("skill-a")
    await caching.fetch_skill("skill-a")

    assert inner.fetch_calls == 2, "inner should be called every time when caching is disabled"
