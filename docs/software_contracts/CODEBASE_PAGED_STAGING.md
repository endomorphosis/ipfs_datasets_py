# Bounded resumable CodebaseIR staging

`CodebasePagedStager` stages source and Python AST artifacts from a complete,
sealed committed Git inventory. It uses the existing chunked snapshot reader,
immutable CAS, Python frontend, shared resource scheduler, and the dedicated
DuckDB connection owned by `CodebaseCatalog`.

This lane is additive to `RepositoryCodebaseIndex`. It writes the separate
`codebase_staging_control` journal and **does not publish a current CodebaseHead
or active AST generation**. A completed staging inventory is not a formalized
repository, resolved dependency graph, training corpus, or checked proof index.
The existing `codebase-ir-structural-manifest@1` keeps its completeness contract.

## Owner API

```python
from ipfs_datasets_py.logic.software_contracts.codebase_paged_staging import (
    CodebasePagedStager, CodebaseStagingLimits,
)

# index is an existing catalog-owned RepositoryCodebaseIndex with a dedicated
# file-backed DuckDB connection and immutable CAS outside the target repository.
stager = CodebasePagedStager(index)
state = stager.prepare(
    repository,
    repository_id="project:committed-view",
    expected_commit=full_commit_oid,
    expected_tree=full_tree_oid,
    limits=CodebaseStagingLimits(max_entries=2048, max_batch_entries=16),
)
while not state["complete_inventory_staged"]:
    state = stager.advance(
        repository,
        generation_cid=state["generation_cid"],
        expected_cursor=state["cursor"],
    )
```

`prepare` hashes the complete committed population in bounded frames before
publishing its immutable metadata references. Its generation identity includes
source commit/tree/population, complete chunked manifest, parser implementation,
and declared limits. An exact repeated preparation returns the existing cursor.

`advance` processes one deterministic contiguous shard. It reobserves the exact
clean committed population, rehashes every source blob it captures, extracts ASTs
without importing or executing target modules, and seals source/AST/shard objects
before atomically advancing the cursor. The cursor and its receipt chain commit
in the same native DuckDB transaction. A transaction failure cannot leave a
partial cursor; a lost response can retry the same previous shard boundary.
A concurrent cursor change rejects the losing advancement.

Close and reopen the native catalog connection, reconstruct the same stager and
call `status(generation_cid)` to recover immutable history. Status replays the
inventory, receipts, source bodies and AST bindings; it performs no live scan,
training, inference or source execution. Its `source_observed_live` is false.
An advancement performs fresh source observations and can return that flag true
only for its point-in-time observation. A later edit still requires reobservation.

## Coverage and bounds

Every inventory entry has exactly one staged disposition: a captured Python AST
with its actual parse status, captured unindexed source, an oversized deferred
file, or an opaque gitlink/symlink/malformed path. `pending_entries` counts units
not processed yet. `deferred_entries` counts processed oversized files that
still lack captured analysis artifacts. Neither disappears from the inventory.

| Limit | Default | Ceiling |
| --- | --- | --- |
| Inventory entries | 2,048 | 20,000 |
| Unique blob bytes hashed during preparation | 64 MiB | 128 MiB |
| Inventory metadata | 8 MiB | 16 MiB |
| Captured source size per unit | 64 KiB | 64 KiB |
| Units per advancement | 16 | 32 |
| Staging generations in the local journal | 128 | 128 |
| Sealed shards in the local journal | 65,536 | 65,536 |

The resource owner reserves 512 MiB, one CPU and one process slot per operation.
An existing datasets parent lease can be supplied. Admission and stage deadlines
are cooperative at the owner boundary; Git has its existing process bounds.
These reservations do not provide a kernel memory limit on the entire owner.
Configure the native DuckDB connection's memory, threads and temporary-space
limits separately. Whole-history status replay remains bounded by this profile;
no constant-time lookup claim is made.

An optional in-process decoding cache retains one parsed inventory and at most
512 AST binding summaries with 32 MiB of canonical AST bodies. Every hit rereads
and compares the exact current CAS bytes; current producer identities are also
checked before reuse. Missing, changed or same-size substituted bodies reject
the lookup. Eviction returns to full native decoding, and a fresh process always
reconstructs the complete typed records. No persisted success flag, warmed
dictionary or numerical reconstruction score is required for correctness.
`replay_cache_stats()` reports decoding/hit/eviction counters as diagnostics.
The cache reduces repeated typed/CID reconstruction; the full-history byte walk
and global inventory checks remain a larger-scale I/O concern.

## Remaining integration

The supported acquisition profile is **complete clean committed source**. Dirty,
staged, untracked, hidden-index and changed-HEAD states refuse advancement.
Submodule gitlinks remain explicit opaque references. This version has no vendor
exclusions, dirty-overlay paging, global cross-shard relation resolution,
source-conditioned inference shards, DuckLake publication, or promotion to the
current structural/proof head. Those require separately qualified integrations;
this staging API must not be substituted for complete current-head admission.

Executable qualification is in
[`test_codebase_paged_staging.py`](../../tests/integration/logic/software_contracts/test_codebase_paged_staging.py).
It exercises native source hashing, bounded shards, fresh-process restart,
Unicode/CRLF source, malformed Python, nonexecuting extraction, dirty-source
refusal, exact retry, missing artifacts, forged dispositions, entry bounds,
rollback, post-commit cancellation recovery, cached-artifact substitution and
bounded cache eviction.
