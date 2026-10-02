# Resumable dirty-source extraction

`CodebaseDirtyPagedStager` adds an opt-in dirty working-tree path to the existing
native `CodebasePagedStager` storage and `CodebaseCatalog` publication owners.
It does not change those owners or introduce another source head. A complete
capture seals the admitted inventory and source bytes before parsing. Subsequent
calls extract at most 16 inventory entries each, retaining explicit opaque,
deferred, unindexed, successful, partial and failed dispositions.

The declared profile admits one committed Git root, with clean or dirty native
snapshots, at most 512 entries, at most 64 KiB per captured file, and therefore
at most 32 MiB of captured source. Its aggregate staged analysis cap is 64 MiB,
and individual structured artifacts have an 8 MiB cap. These are input and
artifact bounds, not a hard RSS guarantee. The existing catalog's independently
configured entry/source/AST limits also apply at publication. A caller selecting
512 entries must construct that native owner with a matching entry limit; its
default 256-entry limit is unchanged.

```python
stager = CodebaseDirtyPagedStager(index)
state = stager.prepare(repository, repository_id="repository:worktree",
                       limits=DirtyStagingLimits(max_entries=512))
while not state["complete_inventory_staged"]:
    state = stager.advance(repository,
        generation_cid=state["generation_cid"],
        expected_cursor=state["cursor"])
receipt = stager.finalize(repository,
    generation_cid=state["generation_cid"],
    operation_id="independently-selected-operation",
    expected_head=previous_native_head)
```

The native database and CAS must be outside the scanned checkout. Resource
arguments accept the existing default shared scheduler or its native parent
lease and cancellation signal. The phase deadline is cooperative after resource
acquisition; Git commands and individual bounded parses retain their existing
operation limits. No target module is imported or executed.

## Complete inventory and extraction pages

The initial capture uses `snapshot_repository`, including exact dirty source,
HEAD/index identity, deleted/conflicted entries, nonregular boundaries, and the
existing native exclusions. Custom exclusions remain part of the snapshot root.
External ignore configuration and exact inactive global/info-exclude bytes are
bound using the existing scan-policy helpers; active external ignore patterns
are refused. Every relevant repository `.gitignore` must itself be captured.
The new profile does not issue a receipt under the older 256-entry scan-policy
schema, nor silently broaden that schema's consumers.

This is bounded whole-source capture. It is not arbitrary-size streaming capture
or a resumable filesystem read. Each live fence reobserves the complete bounded
source population. A changed dirty file, index state, admitted path population,
or ignore scope refuses further work on that generation. A new capture creates
a different generation. Historical `status` reads make no current-source claim.

Pages share the existing `codebase_staging_control` schema and exact cursor
writes. Their separate request/receipt schemas prevent interpreting a clean
committed stage as a dirty stage. An exact old page boundary replays without
extraction. A future/interior cursor or incomplete/corrupt history refuses.
Unreferenced immutable CAS objects may survive an interrupted page; the page and
cursor transaction either commits completely or rolls back. Restart replay reads
and checks the retained immutable bytes, producer hashes and Python runtime
identity; an in-memory parser cache is not required.

## Global semantic assembly and publication

Each page stores the existing frontend's AST records and local Python/pytest
facts. The adapter preserves raw local edges until all entries are staged.
Finalization reconstructs the entire inventory, then invokes the existing pytest
identity unifier, cross-file fixture resolution, dependency-lock wiring and
symbol-graph resolver. It does not reparse the source. Cold manifest equality is
checked against `RepositoryCodebaseIndex.prepare_current`, including cross-page
calls, tests/configuration, fixtures, failed parses, Unicode source and deletions.

Only the existing catalog publishes the complete manifest and AST projections.
Partial stages cannot publish. Live source/scope fences run at the catalog's
checkpoints, including inside its AST/head transaction before commit. A source
edit during actual AST SQL application therefore rolls back the complete batch.
The post-publication fence still detects later edits; these are point-in-time
observations and do not lock a checkout against subsequent writers.

Every catalog checkpoint currently repeats the bounded source/scope fence. This
adds I/O proportional to the number of checks and the full inventory and is a
remaining performance limitation. A successor snapshot currently re-extracts its
pages; this module does not claim cross-generation parse reuse. Global graph
assembly and native SQL publication remain bounded whole-generation operations.

The result retains structural authority only. ASTs, resolved static edges and
successful publication do not prove source behavior, authorize a task, train a
model, or complete a benchmark. This component does not qualify CUDA inference,
general pressure behavior, or the entire RPI-029 criterion. Tests and measurements
distinguish real Git/AST/DuckDB execution with an explicitly injected resource
sampler from separate attempts using the actual default resource owner.
