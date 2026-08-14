## MODIFIED Requirements

### Requirement: Skill Index
The server SHALL maintain a persistent **skill index** in the disk cache, keyed per
`(registry, ref)`, that maps each skill identifier to its parsed frontmatter fields.
The index SHALL be stored at the key `(registry_name, ref, "__meta__", "__skill_index.json")`
using the existing `DiskCache` put/get interface.

On each `list_skills` call the index SHALL be updated incrementally:
— Skills present in the current names list but absent from the cached index SHALL have
  their SKILL.md fetched (via the per-skill content cache) and their frontmatter parsed;
  successful results are added to the index.
— Skills present in the cached index but absent from the current names list (deleted skills)
  SHALL be retired from the index.
— Skills already present in both the names list and the index SHALL not trigger a fetch.

The index SHALL be persisted after every reconciliation pass, capturing only successfully
fetched-and-parsed entries. When a skill's SKILL.md fetch fails (transient error), the
skill SHALL appear in the response as a name-only object but SHALL NOT be written to the
index; the next `list_skills` call will retry the fetch.

The index SHALL share the same `immutable` and TTL semantics as all other cache entries for
that registry: a SHA-locked ref produces an immutable index (never expires); a branch/tag
ref produces a TTL-bounded index that expires in lockstep with the names list, causing a
full rebuild on the next call — this is the mechanism by which in-place frontmatter edits
on mutable refs are eventually picked up without a manual `refresh_cache=True`.

Concurrent `list_skills` calls for the same registry within the same process SHALL be
serialised via an `anyio.Lock` (one per `CachingRegistry` instance) to prevent lost index
updates and redundant fetch storms.

Skill identifiers SHALL be preserved verbatim through all cache paths, including identifiers
that contain forward slashes (e.g. `quality/reviewing/code-review`). The index key, the
`"name"` field in returned metadata, and the per-skill content cache key SHALL all use the
full, unmodified identifier string.

#### Scenario: New skill is added to index on first listing
- **WHEN** `list_skills` is called and a skill identifier is not yet in the cached index
- **THEN** the skill's SKILL.md is fetched, its frontmatter is parsed, and the entry is persisted in the index

#### Scenario: Deleted skill is retired from index
- **WHEN** `list_skills` is called after a skill has been removed from the registry
- **THEN** the skill's entry is removed from the index and the skill does not appear in the result

#### Scenario: Existing index entry is reused without a fetch
- **WHEN** `list_skills` is called and a skill is already in the cached index (within TTL)
- **THEN** no upstream SKILL.md fetch is made for that skill

#### Scenario: Index TTL expiry triggers full rebuild
- **WHEN** `list_skills` is called after the index TTL has elapsed (mutable ref)
- **THEN** the stale index is treated as a miss and a full index rebuild is performed

#### Scenario: Fetch failure leaves skill absent from index and retried next call
- **WHEN** one skill's SKILL.md fetch fails during an incremental update
- **THEN** that skill appears in the response as a name-only object, is not written to the index, and is retried on the next `list_skills` call

#### Scenario: Partial index is persisted on batch fetch failure
- **WHEN** some skills succeed and some fail during a reconciliation pass
- **THEN** the successfully-fetched entries are persisted to the index and the failed skills are retried next call

#### Scenario: refresh_cache rebuilds index from empty
- **WHEN** `list_skills` is called with `refresh_cache=True`
- **THEN** the existing index is discarded and a full rebuild is performed from the freshly-discovered names list

#### Scenario: Concurrent list_skills calls are serialised per registry
- **WHEN** two concurrent `list_skills` calls target the same registry
- **THEN** the second call waits for the first to complete before reading or writing the index

#### Scenario: Nested-path identifier preserved verbatim on cold index
- **WHEN** `list_skills_metadata` is called for the first time and a skill identifier contains a forward slash
- **THEN** the returned entry's `"name"` field equals the full identifier string including the slash

#### Scenario: Nested-path identifier preserved verbatim from warm index
- **WHEN** `list_skills_metadata` is called a second time and the index was populated with a slash-containing identifier on the first call
- **THEN** the returned entry's `"name"` field still equals the full identifier string

#### Scenario: Stale flat identifier retired when registry renames skill to nested path
- **WHEN** `list_skills_metadata` is called after the registry returns a new nested-path identifier for a skill that previously had a flat (slash-free) name
- **THEN** the old flat-name entry is absent from the result and the new nested-path entry is present with the correct `"name"` field
