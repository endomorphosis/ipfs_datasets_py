# Abby Voice Hugging Face Publication Evidence

Date: 2026-07-30

Goal: `ABBY-VOICE-G021`

This package-owned receipt makes the immutable Abby voice publication boundary
self-contained when `ipfs_datasets_py` is tested or released independently of
the 211-AI parent repository. It supplements the parent supervisor receipt:

`residual scan closure: data/abby_voice/agent_supervisor/discovery/2026-07-26-abby-voice-auto-030-objective-validation-repair.md`

Residual acceptance terms: `post-publication verification` and
`pinned redownload validation`.

## Enforced publication contract

- Dry-run planning is network-free and remote-write-free by default.
- The audited Hugging Face parent commit and target revision are included in
  the approved plan digest.
- Live publication confirms that parent is still current, rejects any
  pre-existing path under the immutable release prefix, and passes the same SHA
  as `create_commit(parent_commit=...)` so a concurrent update fails closed.
- Upload operations use local file paths. The publisher never assembles the
  audio corpus in memory.
- The post-publication verification inventories every planned path at the returned
  commit SHA. LFS SHA-256 metadata is checked directly; regular Git objects are
  downloaded by the pinned SHA and hashed from disk.
- The pinned redownload validation starts with an empty verified cache, downloads
  every planned object at the returned commit SHA, and rehashes the files from
  disk.
- A failed verification gate preserves a blocked receipt containing the
  immutable commit SHA. It does not promote, delete, or overwrite the candidate.
- Canary promotion remains a separate reviewed operation.

## Validation

The package-focused suite exercises deterministic dry runs, exact-plan approval,
parent-race rejection, release-prefix collision rejection, path-backed upload
operations, real pinned test downloads, post-publication digest failures,
empty-cache enforcement, and blocked post-commit receipts:

```text
python -m pytest -q \
  tests/unit/voice/test_abby_voice_hf_publish.py \
  tests/unit/voice/test_abby_voice_hf_release.py
```

This evidence does not authorize a remote write. A live upload still requires
an explicit human approval record matching the exact plan digest, byte/cost
bounds, repository credential scope, and audited parent commit.
