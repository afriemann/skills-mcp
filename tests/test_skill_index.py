# spec: openspec/changes/skill-listing-frontmatter-index/specs/skill-index/spec.md
"""Unit tests for the incremental skill index in CachingRegistry."""

from pathlib import Path

import anyio

from skills_mcp.cache import DiskCache
from skills_mcp.errors import RegistryUnavailableError
from skills_mcp.registries import CachingRegistry, SkillContent

# ---------------------------------------------------------------------------
# Fake inner adapters
# ---------------------------------------------------------------------------

_FRONTMATTER = "---\ndescription: 'Desc for {name}'\ntags:\n  - test\n---\n# {name}"


class FakeInnerWithFrontmatter:
    """Adapter whose SKILL.md content includes parseable frontmatter."""

    type = "github"
    ref: str | None = "main"

    def __init__(self, name: str = "reg", skills: list[str] | None = None) -> None:
        self.name = name
        self._skills = skills if skills is not None else ["skill-a", "skill-b"]
        self.list_calls = 0
        self.fetch_calls: dict[str, int] = {}

    async def list_skills(self) -> list[str]:
        self.list_calls += 1
        return list(self._skills)

    async def fetch_skill(self, skill: str) -> SkillContent:
        self.fetch_calls[skill] = self.fetch_calls.get(skill, 0) + 1
        content = _FRONTMATTER.format(name=skill)
        return SkillContent(content=content, files=())

    async def fetch_file(self, skill: str, file_path: str) -> str:
        return "content"


def _total_fetches(inner: FakeInnerWithFrontmatter) -> int:
    return sum(inner.fetch_calls.values())


def _make_caching(
    inner: FakeInnerWithFrontmatter,
    tmp_path: Path,
    *,
    enabled: bool = True,
    ttl: int = 3600,
) -> CachingRegistry:
    cache = DiskCache(tmp_path / "cache", enabled=enabled, ttl_seconds=ttl)
    return CachingRegistry(inner, cache, immutable=False, enabled=enabled)


# ---------------------------------------------------------------------------
# Scenario: list_skills_metadata returns list[dict] with name + frontmatter
# ---------------------------------------------------------------------------


async def test_list_skills_metadata_returns_dicts_with_name(tmp_path: Path):
    """list_skills_metadata returns a list[dict], each with at least 'name'."""
    inner = FakeInnerWithFrontmatter()
    caching = _make_caching(inner, tmp_path)

    result = await caching.list_skills_metadata()

    assert isinstance(result, list)
    assert all(isinstance(item, dict) for item in result)
    assert all("name" in item for item in result)


async def test_list_skills_metadata_includes_frontmatter_fields(tmp_path: Path):
    """Description and tags from frontmatter appear in the returned dicts."""
    inner = FakeInnerWithFrontmatter()
    caching = _make_caching(inner, tmp_path)

    result = await caching.list_skills_metadata()

    skill_a = next(r for r in result if r["name"] == "skill-a")
    assert skill_a.get("description") == "Desc for skill-a"
    assert skill_a.get("tags") == ["test"]


async def test_list_skills_metadata_identifier_wins_over_frontmatter_name(tmp_path: Path):
    """The skill identifier (from list_skills) is always authoritative as 'name'.

    Even when frontmatter contains a name: field, the identifier overrides it.
    """

    class IdentifierMismatchAdapter(FakeInnerWithFrontmatter):
        async def fetch_skill(self, skill: str) -> SkillContent:
            self.fetch_calls[skill] = self.fetch_calls.get(skill, 0) + 1
            content = "---\nname: wrong-name\ndescription: 'desc'\n---\n# content"
            return SkillContent(content=content, files=())

    inner = IdentifierMismatchAdapter()
    caching = _make_caching(inner, tmp_path)

    result = await caching.list_skills_metadata()

    names = {r["name"] for r in result}
    assert "wrong-name" not in names
    assert "skill-a" in names
    assert "skill-b" in names


# ---------------------------------------------------------------------------
# Scenario: Incremental — existing entries are not re-fetched on second call
# ---------------------------------------------------------------------------


async def test_incremental_no_refetch_on_second_call(tmp_path: Path):
    """A warm index means the second list_skills_metadata call fetches nothing."""
    inner = FakeInnerWithFrontmatter()
    caching = _make_caching(inner, tmp_path)

    await caching.list_skills_metadata()
    fetches_after_first = _total_fetches(inner)

    await caching.list_skills_metadata()
    fetches_after_second = _total_fetches(inner)

    assert fetches_after_second == fetches_after_first, (
        "warm index: second call must not re-fetch any skills"
    )


# ---------------------------------------------------------------------------
# Scenario: New skill added to registry appears in next listing
# ---------------------------------------------------------------------------


async def test_new_skill_added_to_index_on_next_call(tmp_path: Path):
    """A new skill that appears in list_skills is fetched and added to the index."""
    inner = FakeInnerWithFrontmatter(skills=["skill-a"])
    caching = _make_caching(inner, tmp_path, ttl=0)  # ttl=0 so names cache expires

    await caching.list_skills_metadata()
    assert inner.fetch_calls.get("skill-a", 0) == 1
    assert inner.fetch_calls.get("skill-b", 0) == 0

    inner._skills = ["skill-a", "skill-b"]
    result = await caching.list_skills_metadata()

    names = [r["name"] for r in result]
    assert "skill-b" in names
    assert inner.fetch_calls.get("skill-b", 0) >= 1, "new skill must have been fetched"


# ---------------------------------------------------------------------------
# Scenario: Deleted skill retired from index
# ---------------------------------------------------------------------------


async def test_deleted_skill_retired_from_index(tmp_path: Path):
    """A skill no longer in list_skills is retired from the index."""
    inner = FakeInnerWithFrontmatter(skills=["skill-a", "skill-b"])
    caching = _make_caching(inner, tmp_path, ttl=0)

    await caching.list_skills_metadata()

    inner._skills = ["skill-a"]  # skill-b removed
    result = await caching.list_skills_metadata()

    names = [r["name"] for r in result]
    assert "skill-b" not in names
    assert "skill-a" in names


# ---------------------------------------------------------------------------
# Scenario: Fetch failure → name-only in response, NOT persisted
# ---------------------------------------------------------------------------


async def test_fetch_failure_name_only_not_persisted(tmp_path: Path):
    """A failed fetch produces a name-only entry in the response but is NOT persisted;
    the next call retries the upstream."""

    class FailFirstA(FakeInnerWithFrontmatter):
        _failed_once = False

        async def fetch_skill(self, skill: str) -> SkillContent:
            self.fetch_calls[skill] = self.fetch_calls.get(skill, 0) + 1
            if skill == "skill-a" and not self._failed_once:
                self._failed_once = True
                raise RegistryUnavailableError("upstream down")
            content = _FRONTMATTER.format(name=skill)
            return SkillContent(content=content, files=())

    inner = FailFirstA()
    caching = _make_caching(inner, tmp_path)

    # First call: skill-a fails → name-only in response
    result1 = await caching.list_skills_metadata()
    skill_a_1 = next(r for r in result1 if r["name"] == "skill-a")
    assert "description" not in skill_a_1, (
        "fetch failure must not persist frontmatter — entry should be name-only"
    )

    # Second call: skill-a NOT in index → retried
    result2 = await caching.list_skills_metadata()
    skill_a_2 = next(r for r in result2 if r["name"] == "skill-a")
    assert "description" in skill_a_2, (
        "skill-a should have been retried successfully on the second call"
    )
    assert inner.fetch_calls.get("skill-a", 0) == 2


# ---------------------------------------------------------------------------
# Scenario: refresh=True bypasses names cache and rebuilds index from empty
# ---------------------------------------------------------------------------


async def test_refresh_true_bypasses_index_and_refetches(tmp_path: Path):
    """refresh=True must bypass the cached index and re-fetch all skills."""
    inner = FakeInnerWithFrontmatter()
    caching = _make_caching(inner, tmp_path)

    await caching.list_skills_metadata()
    fetches_after_first = _total_fetches(inner)

    await caching.list_skills_metadata(refresh=True)
    fetches_after_refresh = _total_fetches(inner)

    assert fetches_after_refresh > fetches_after_first, (
        "refresh=True must re-fetch all skills even when the index is warm"
    )


# ---------------------------------------------------------------------------
# Scenario: fetch_skill(refresh=True) bypasses cache and writes back
# ---------------------------------------------------------------------------


async def test_fetch_skill_refresh_false_hits_cache(tmp_path: Path):
    """fetch_skill with refresh=False (default) uses the cache on second call."""
    inner = FakeInnerWithFrontmatter()
    caching = _make_caching(inner, tmp_path)

    await caching.fetch_skill("skill-a")
    assert inner.fetch_calls.get("skill-a", 0) == 1

    await caching.fetch_skill("skill-a")  # refresh=False default
    assert inner.fetch_calls.get("skill-a", 0) == 1, "second call should hit cache"


async def test_fetch_skill_refresh_true_bypasses_and_writes_back(tmp_path: Path):
    """fetch_skill(refresh=True) skips cache, fetches fresh, writes back so next
    call with refresh=False can use the repaired cache entry."""
    inner = FakeInnerWithFrontmatter()
    caching = _make_caching(inner, tmp_path)

    await caching.fetch_skill("skill-a")  # warm cache
    assert inner.fetch_calls.get("skill-a", 0) == 1

    await caching.fetch_skill("skill-a", refresh=True)  # bypass + write back
    assert inner.fetch_calls.get("skill-a", 0) == 2

    await caching.fetch_skill("skill-a")  # should hit repaired cache
    assert inner.fetch_calls.get("skill-a", 0) == 2, "write-back cache used on fourth call"


# ---------------------------------------------------------------------------
# Scenario: Concurrent list_skills_metadata calls are serialised
# ---------------------------------------------------------------------------


async def test_concurrent_calls_serialised(tmp_path: Path):
    """Two concurrent list_skills_metadata calls must not result in double upstream fetches."""
    inner = FakeInnerWithFrontmatter()
    caching = _make_caching(inner, tmp_path)

    # Run two concurrent calls
    async with anyio.create_task_group() as tg:
        results: list[list[dict]] = []

        async def _call() -> None:
            r = await caching.list_skills_metadata()
            results.append(r)

        tg.start_soon(_call)
        tg.start_soon(_call)

    assert len(results) == 2
    # Each skill must be fetched exactly once: the lock serialises the two calls so the
    # second one finds a warm index and performs zero fetches.
    for skill in ["skill-a", "skill-b"]:
        assert inner.fetch_calls.get(skill, 0) == 1, (
            f"serialised calls: {skill!r} must be fetched exactly once"
        )


# ---------------------------------------------------------------------------
# Scenario: Index TTL expiry triggers full rebuild
# ---------------------------------------------------------------------------


async def test_ttl_expiry_triggers_full_rebuild(tmp_path: Path):
    """Scenario: After the index TTL elapses, the next call treats the index as a miss
    and re-fetches all skills — even when the skill list has not changed."""
    inner = FakeInnerWithFrontmatter()
    caching = _make_caching(inner, tmp_path, ttl=0)  # immediate expiry

    await caching.list_skills_metadata()
    fetches_first = dict(inner.fetch_calls)  # snapshot

    # Second call: index TTL already expired (ttl=0) — full rebuild
    await caching.list_skills_metadata()

    for skill in ["skill-a", "skill-b"]:
        assert inner.fetch_calls.get(skill, 0) > fetches_first.get(skill, 0), (
            f"TTL expiry: {skill!r} must be re-fetched on the second call"
        )
