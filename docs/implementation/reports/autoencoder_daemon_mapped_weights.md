# Optional mapped feature weights in owned daemon invocations

An owned invocation can now explicitly bind the existing private Arrow
`feature_embedding_weights` artifact to its full base checkpoint. Ordinary
parameter storage remains the default. This changes one component's initial
representation; it does not change the optimizer, numeric precision, legal
semantics or full-checkpoint candidate authority.

Native validation is **deferred at the user's request**. The implementation and
focused fixture coverage below do not qualify a complete native owner cycle or
a performance improvement.

## Immutable owner opt-in

[`prepare_daemon_invocation`](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_invocation.py)
accepts `arrow_feature_weights={"path": ..., "sha256": ..., "bytes": ...}`.
The owner stages those exact bytes and seals them into the closed
`autoencoder-daemon-invocation-request-v3` request. V3 also contains the explicit
boolean `sparse_shadow`; mapped weights do not require shadow mode. Omitting the
weight descriptor preserves ordinary v1 or optional-shadow v2 request behavior.
There is no execution-time switch that can replace the bound artifact or silently
fall back when its verification fails.

The supervised describe and independent verification paths reconcile the sidecar
with the independently loaded authoritative base. Its declared base SHA alone
is insufficient: the actual feature key order, row lengths and float64 bits must
match, including empty rows and signed zero. Checkpoint provenance binds the
sidecar content, full base artifact and base identity; canonical comparisons
preserve JSON type distinctions. Historical completed-operation replay retains
its recorded result and does not repeat mapping or diagnostic work.

The sidecar is private legacy storage. Original keys remain intact; this is not a
typed-key migration or a public-export qualification. It covers only
`feature_embedding_weights`, not all model parameters.

## Attachment, mutation and native detachment

[`VerifiedDaemonWeightSession`](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_weight_session.py)
attaches before startup capacity compaction. It requires an exact native state,
the creating thread and no active state transaction. It replaces the feature
map in the same state object through the existing tracking adapter without
advancing the revision. Other native fields remain untouched. Fixture validation
checks all 38 fields, identities, revision and full compact checkpoint bytes at
this attachment boundary.

Reads use immutable mapped float64 buffers; mutations use the existing private
tracked-row overlays. Ordinary transaction rollback and portable patch replay
retain their semantics. Attachment does not imply that later training leaves
the state unchanged.

Startup pruning, TODO rollback or another native state replacement may produce
an ordinary tracked dictionary. The session records `detached_native` and its
first observed phase; it does not automatically reattach the original table.
A mapped table belonging to another base is rejected rather than labeled as a
native detachment. A run must not be described as fully mapped merely because
its initial attachment succeeded.

After native state replacement the session keeps detached counters and releases
the old tracked map. Otherwise its callbacks could retain the discarded state.
Close also releases the latest state and tracked map; weak-reference fixtures
verify that those graphs can be collected.

## File and asynchronous lifetimes

The [feature-weight codec](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder_arrow_weights.py)
retains a read-only file descriptor and maps that descriptor. It rejects symlink
aliases and nonregular files, pins pathname/stat/inode identity, checks the exact
SHA and verifies numeric buffer addresses lie within the mapping. Bounded IPC
preflight rejects compression and forged batch extents before batch decoding.
Existing empty and multi-batch ragged layouts retain the same wire schema.

`verify_unchanged()` rechecks the staged file at consumption and persistence
boundaries. A failed check poisons the session and follows the daemon's existing
failure gates; it cannot produce a newly qualified clean-shutdown candidate.
Previously valid queued writes or promotions are not retroactively erased.
The 512 MiB artifact cap is a byte bound, not a bound on Python memory or RSS.
These checks do not detect every concurrent mutation-and-restoration interval;
the caller must keep the file immutable throughout use.

Close ownership remains with the caller. The session context installs the
binding but does not close it. The supervised worker retains the session through
daemon cleanup and closes it afterward. All tracked bindings sharing that base
then reject new mapped access. Exported read-only arrays can retain their backing
buffer lifetime after the descriptor closes; storage retirement must respect
those users too.

Asynchronous evaluation state is already serialized into immutable bytes, and
checkpoint handles are serialized before enqueue. Feature-row deepcopy also
materializes ordinary independent values. Those boundaries intentionally copy;
the implementation does not claim whole-training zero-copy or synchronization
between concurrent copying and owner closure.

## Validation status

The [codec-focused capture](../../../workspace/test-logs/federal-corpus-audits/daemon-arrow-weights-20260925/focused-r1-receipt.json)
records **45 passing tests**: 23 existing cases and 22 added boundary cases.
They cover exact row/float behavior, overlays and rollback, persistent byte
changes, replacement/unlink/symlink paths, load-time changes, descriptor cleanup,
exported-array lifetime, and pre-decoder compression/forged-length rejection.
The capture includes the exact source hashes and test command.

- Session and asynchronous-lifecycle final focused result: **20 passed in
  4.60 seconds**, including state and mapping release after detachment/close.
- [Owner/request/worker final focused capture](../../../workspace/test-logs/federal-corpus-audits/daemon-mapped-weights-20260925/owned-final-freeze.json):
  **203 current cases covered**, including 44 new cases. The initial combined
  focused run passed 200; after a malformed-query compatibility refinement, all
  65 worker cases passed. These are overlapping runs, not 265 distinct cases.
- [Root combined regression capture](../../../workspace/test-logs/federal-corpus-audits/daemon-mapped-weights-20260925/combined-r1-receipt.json):
  **772 passed, zero failures/errors/skips** across 22 files, in 134.13 pytest
  seconds (136.084739 seconds for the subprocess wrapper). All 7,737 package
  source files and all selected test files were unchanged during the capture.
  Protected checkpoint and historical receipt size/SHA checks passed, as did the
  semantic gates and round-trip pilot. The receipt SHA-256 is
  `6803b2c78097fd00a377c592c6a0016e6065287631427984e9e4a2aca33b890d`.

These fixture suites use synthetic states and disclosed optimizer callbacks.
Their counts remain distinct from native training, bridge-on
evaluation, learned improvement or formalization evidence. No native validation
or performance run is authorized by this milestone.

## Cost and remaining qualification

Every declared file boundary hashes the sidecar again. Base reconciliation,
key/index construction, scalar boxing, identity calculation, snapshots and full
checkpoint serialization also allocate or scan data. Native detachment can
eliminate subsequent mapped reads. Those costs belong in any future complete
invocation comparison; isolated mapped-buffer access is insufficient evidence.

The historical [worker feature-table comparison](autoencoder_shared_targets_sparse_arrow.md)
was slower overall: **12.7500 versus 12.1534 seconds**. That run did not mutate
feature rows, and its limited memory observations did not establish a parallel
memory saving. The historical
[mapped-input comparison](autoencoder_produced_corpus_arrow_training.md) was also
slower overall. Neither measurement predicts the newly connected daemon path.

When native validation is separately authorized, compare ordinary and mapped
feature storage with the same full base, inputs, five bridge names, prover flag
false, metric disk cache zero, one bridge worker, optimizer/snapshot settings and
explicit per-pass sample-memory policy. Report detachment phases, materialized
rows, repeated verification cost, complete-cycle time, per-evaluation time,
memory and bytes written. Preserve full checkpoints as authority and retain
defaults unless measured benefit justifies changing them.

No DuckLake consumer, Hugging Face publication or branch promotion is enabled by
this representation change. The Constitution remains unformalized. Only
`lake build <Lib>` constitutes a Lean admit; this slice performs no Lake work.
