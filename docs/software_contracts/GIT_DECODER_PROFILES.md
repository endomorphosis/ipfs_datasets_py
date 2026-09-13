# Explicit Git decoder profiles

Committed chunk acquisition uses a 128 MiB address-space limit for each Git
blob decoder by default. A large packed or delta-compressed object can exceed
that limit even when the caller retains only 1 MiB frames. Such a refusal does
not establish a complete acquisition.

Callers may explicitly request the separately admitted, fixed 256 MiB profile:

```python
from ipfs_datasets_py.logic.software_contracts.semantic_index.git_decoder_profile import (
    GitBlobDecoderBudget, GitBlobDecoderProfile,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.chunked_snapshot import (
    ChunkedSnapshotLimits, snapshot_chunked_repository,
)

profile = GitBlobDecoderProfile(address_space_bytes=256 * 1024**2)
budget = GitBlobDecoderBudget(max_address_space_bytes=256 * 1024**2)
snapshot = snapshot_chunked_repository(
    repository,
    repository_id=repository_id,
    expected_commit=full_commit_oid,
    expected_tree=full_tree_oid,
    limits=ChunkedSnapshotLimits(max_stream_bytes=qualified_unique_blob_bytes),
    decoder_profile=profile,
    decoder_budget=budget,
)
```

The caller must establish resource availability and pin its request and imported
producer source before acquisition. Only the exact typed 128 MiB and 256 MiB
profiles and budgets are supported. The manifest cannot grant its own budget.
Pass the same requested profile and an admitted caller budget to manifest
parsing/admission, frame reads, projection, streaming scans, and semantic
reconstruction. Omitting either explicit argument when consuming a 256 MiB
manifest refuses before content is decoded. Requesting 256 MiB with a 128 MiB
budget also refuses before observing the repository.

Default acquisition retains the existing `git-chunked-snapshot@1` manifest.
Explicit 256 MiB acquisition produces `git-chunked-snapshot@2`, whose root binds
the complete decoder profile: address-space limit, fixed Git cache settings,
command timeout, launcher hash, decoder source hashes, and absence of target
imports or execution. The parser requires exact equality to the separately
requested profile, including source identity. A v1 manifest cannot be
reinterpreted as a 256 MiB acquisition. An old v2 manifest cannot be silently
reinterpreted using changed decoder source. Caller-level commit, import-root,
and before/after source checks remain necessary; the profile does not replace
those checks.

The Git child retains its 10 second command timeout, 8 MiB packed window, 32 MiB
packed cache, and 16 MiB delta cache. Frame and bundle blocks remain at most
1 MiB, materialized individual sources at most 4 MiB, and legacy retained
sources at most 128 MiB. Metadata, AST, fact, and streaming worker bounds remain
unchanged. The cumulative byte-work limit is a separate typed acquisition
budget; it must cover the complete unique Git blob population. Enlarging the
decoder profile does not enlarge that budget or make an oversized source
eligible for semantic analysis.

The reconstruction consumer binds the profile and caller budget in its
configuration digest and emits observation schema `chunked-semantic-reconstruction@4`
when either differs from the default. Default observations and configurations
retain their existing schemas. All content is still independently rehashed;
gitlinks remain opaque entries. Acquisition, resource admission, and
reconstruction confer no task completion, goal acceptance, or complete
semantic analysis authority.
