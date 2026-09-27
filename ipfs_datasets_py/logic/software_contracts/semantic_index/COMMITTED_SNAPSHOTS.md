# Complete committed snapshots

The ordinary `snapshot_repository` API retains its existing traversal exclusions.
For an independent reconstruction that must account for every committed path,
use the explicitly named APIs from `semantic_index.committed_snapshot`:

```python
plan = preflight_committed_repository(
    repository, repository_id=repository_id,
    expected_commit=commit_oid, expected_tree=tree_oid,
)
# plan.entries contains exact raw paths, modes, object IDs and blob sizes.
# A deficiency returns the full metadata plan, never a reduced population.
if not plan.budget_violations:
    snapshot = snapshot_committed_repository(
        repository, repository_id=repository_id,
        expected_commit=commit_oid, expected_tree=tree_oid,
        expected_population_cid=plan.population_cid,
    )
```

Both APIs require the exact repository root, a clean checkout, full HEAD commit
and tree IDs, and an index without skip-worktree or assume-unchanged hints. They
observe source identity before and after acquisition, ignore Git replacement
objects and ambient `GIT_*` overrides, and preserve every committed raw path.
These checks detect ordinary drift; the native caller still owns mutation fences
and must independently qualify the actual loaded producer and execution request.

Preflight reads bounded Git metadata, without requesting blob contents. Its
population CID binds the repository identity, commit, tree and all entries.
Blob totals count every path, including repeated object IDs. Gitlinks have no
local blob size; symlinks count their committed blob bytes. Metadata overflow or
unavailable object sizes fail closed. Entry, per-blob and total size deficiencies
are reported together, and acquisition refuses them before requesting any blob.

Complete scope bypasses traversal exclusions only. Existing opaque handling for
malformed paths, symlinks, gitlinks and unsupported contents remains visible.
Gitlinks require separate admitted repository acquisitions for forest coverage.
Blob acquisition checks both the recorded size and Git object hash.

The snapshot and semantic pipeline still retain content in memory. Increasing
the 128 MiB aggregate default does not qualify a multi-gigabyte producer. Such a
producer needs bounded streaming or chunked content storage, streaming hashes,
parser limits, and a compatible scanner/state builder before its larger limits
can be admitted. A plan or matching snapshot is diagnostic content; neither
grants semantic acceptance, runtime settlement or completion authority.
