# Bounded committed content references

`snapshot_chunked_repository` is a separate, explicit producer. It discovers the
complete committed population through metadata preflight, reads each unique
Git blob once, and verifies its full Git object hash and raw SHA-256 source CID.
Repeated paths retain their individual entries while sharing one blob manifest.
Symlink blob bytes are hashed without following their targets. Gitlinks retain
their exact commit references and require separate forest acquisition.

```python
from .chunked_snapshot import (
    ChunkedSnapshotLimits, snapshot_chunked_repository, project_chunked_repository,
)

chunked = snapshot_chunked_repository(
    root, repository_id=repository_id, expected_commit=commit, expected_tree=tree,
    limits=ChunkedSnapshotLimits(),
)
root_cid, manifest_blocks = chunked.manifest_blocks()
projection = project_chunked_repository(root, chunked)
# Feed projection.snapshot to the ordinary scanner, and separately bind
# projection.chunked_snapshot_cid into the native reconstruction request.
```

Blob data stays in Git object storage. No working-tree contents, object copies,
new packs, persistent database or content cache are created. Frames have a fixed
1 MiB ceiling. Blob manifests record contiguous offsets, lengths and raw chunk
CIDs. Inventory and blob indexes are paged so every structured manifest block
also fits within 1 MiB. Metadata, entry count, chunk reference count and unique
streaming work are independently bounded before content reads. The default work
budget is 128 MiB; qualifying a larger total stream does not enlarge a frame or
retained-content limit. A full object must be consumed, hash-checked and the
source reobserved before a snapshot is returned.

`read_chunked_blob_frame` retrieves one frame from immutable Git storage. It
hashes the entire requested blob and verifies every chunk reference before
returning the selected frame, retaining only that frame. Corruption in a later
chunk cannot be hidden by reading only the beginning. Compressed Git objects
currently require a whole-blob stream per call; this is bounded-memory access,
not a persistent random-access cache or verification of other blobs.

`project_chunked_repository` re-reads **every** unique blob and compares all
manifest identities before returning the existing snapshot representation.
It never treats a serialized hash claim as verified content. Inputs at most
4 MiB may be retained for the existing scanner, within a fixed 128 MiB total
retained-source ceiling. Larger inputs remain present as opaque entries with
their fully verified source CID and `analysis_budget_exceeded`. These entries
establish exact content equality; they do not establish semantic analysis of
oversized code. If the ordinary input population exceeds 128 MiB, projection
refuses the whole request instead of silently selecting fewer files.

The manifest DAG is metadata only and does not guarantee future Git object
availability. Missing objects, replacement objects, source/index drift, wrong
blob bytes, truncated streams, contradictory population claims, or changed
chunk references fail closed. Git replacement objects are ignored. Subprocess
streams are time-bounded and their owned children are reaped on failure.
The trusted isolated Python launcher also gives Git a fixed 128 MiB address-space
limit before execution. This bounds hidden Git decoder allocations; delta-packed
objects that cannot decode within that limit fail closed. Packed Git windows
are fixed at 8 MiB, the packed-window cache at 32 MiB, and the delta-base cache
at 16 MiB so default large mmap windows do not consume the address-space bound.
These settings are included in the manifest root. The Python memory test
does not measure the child. Actual large packed-object behavior still needs
qualification under this fixed limit before a live population is admitted.
Decoder errors use `GitBlobDecoderError`, report the configured address-space
limit, and return no verified manifest. This records a decoder refusal without
assuming every subprocess failure was caused by memory pressure.

## Consumer and qualification work still required

The existing scanner retains a dictionary of all verified source bytes and a
second Python/pytest source mapping. A streaming scanner and a compatible pytest
frontend are still needed when the aggregate ordinary-source population exceeds
128 MiB. The current AST frontend also needs a qualified large-source strategy;
opaque large code cannot be promoted to positive analysis coverage.

`semantic_state/source.py` materialization APIs still require whole byte values.
They need a bounded chunk-backed range reader with the same source identity and
freshness guarantees. The state builder can consume a bounded projection today,
but the native request and persisted state must explicitly bind the chunked
manifest root and store/validate its complete DAG. This change provides no
untrusted transport deserializer or automatic block-store admission. A future
consumer must validate closed schemas, frame limits, every reference and full
population equality before re-verifying Git content.
The current builder preserves opaque artifacts transitively, but plain
`RepositoryState` does not supply formal `AnalysisLimitation` records. A qualified
adapter must explicitly populate that index from the known limitations; an
empty formal index must not be read as evidence that opaque code was analyzed.

The supervisor PR215 reconstruction consumer still uses the bounded captured
snapshot API. It has not been switched automatically to this new representation.
Native producer/import qualification, mutation/owner fences, forest admission,
independent execution evidence and completion settlement remain required.
Neither a matching chunked manifest nor an opaque content hash supplies these
authorities. Ordinary snapshot/scanner behavior is unchanged.
