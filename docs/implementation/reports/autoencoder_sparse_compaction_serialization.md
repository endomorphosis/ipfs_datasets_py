# Single serialization during sparse checkpoint compaction

The [training coordinator](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_training_coordinator.py)
previously serialized the independently replayed state twice when sparse-chain
compaction was required: once to calculate the canonical full checkpoint's byte
identity and again to write that same checkpoint. It now serializes once into
an exclusive temporary directory and uses that file's descriptor for the
existing receipt, parent and exact manifest checks.

Full candidate staging still occurs only after those comparisons succeed.
The registry independently hashes and copies the scratch file using its expected
SHA-256, and the staged descriptor must equal the replayed candidate descriptor.
The worker manifest remains retained audit evidence. Normal completion still
rechecks the run lease/fence before the existing `CompleteRun` transaction.
No worker claim becomes owner verification, promotion or Lean admission.

Compaction thresholds remain the owner's existing depth and patch-fraction
policy. Noncompacting sparse jobs still hash without writing a full candidate;
legacy/full candidate branches retain their existing checks and output. Parent
closure resolution, independent patch replay, revision resets, canonical JSON,
registry schema and optional-storage defaults are unchanged. The public sparse
checkpoint writer API is unchanged.

The temporary-directory context encloses compaction validation and staging.
Ordinary validation, write, fsync or staging failures unwind that context;
cleanup retains the standard `TemporaryDirectory` behavior, including its
possibility of raising on a cleanup failure. A process crash is not a guarantee
of automatic scratch deletion. The `sparse_replay_seconds` timer is finalized
after successful context exit, so it still includes scratch cleanup.

There is a tradeoff: an invalid compaction receipt or manifest can now incur a
private write/fsync before rejection, where the old path performed only a
serialization/hash before rejection. Those bytes are not staged as a full
candidate before validation and cannot complete the run. This change does not
add a new independent scratch-size quota; existing artifact/state limits and
resource accounting continue to apply. Accepted compacted candidates retain the
same full-checkpoint authority boundary.

The [synthetic profile](../../../workspace/test-logs/federal-corpus-audits/sparse-compaction-serialization-20260925/compaction-profile-receipt.json)
compares duplicate identity-plus-write with a single write using a deterministic
state containing 131,072 feature values. Three alternating observations per arm
include serialization, file writing and fsync. Median time was **58.554 ms to
31.996 ms**, about 45.36% lower for this storage slice. Each paired file compared
byte-for-byte equal: 2,051,765 bytes, SHA-256
`2cd1c10cd859af1522809adcb316c53f7b2997719f42eb7191817dcf11310782`.
The receipt stores descriptors and equality outcomes, not those full files.

This profile excludes owner replay, CAS staging, completion transactions,
training and bridge evaluation. Filesystem cache state was uncontrolled. It is
not a whole-compaction or end-to-end throughput claim. All 7,743 package-source
hashes stayed unchanged during this pre-edit capture; synthetic output files
were removed after comparison and the shared resource reservation was released.
The [pre-edit coordinator](../../../workspace/test-logs/federal-corpus-audits/sparse-compaction-serialization-20260925/autoencoder_training_coordinator.before.py)
is retained at SHA-256
`db12aaf0faf6ef7c0deace1ff17fe0f3fd7dcbd424b5c06a510cc81ec611e93a`.

The [focused checks](../../../tests/unit/optimizers/logic_theorem_optimizer/test_sparse_compaction_serialization.py)
passed **20 tests in 3.75 seconds**; their
[receipt](../../../workspace/test-logs/federal-corpus-audits/sparse-compaction-serialization-20260925/compaction-r2-receipt.json)
records unchanged coordinator, codec and test hashes during capture. An embedded
pre-edit helper compares exact summaries apart from timing, descriptors and full
bytes across depth/fraction policies, no-compaction, full and legacy modes.
Serialization counters distinguish the final endpoint from parent-chain checks:
compaction changes only the endpoint from two serializations to one. Actual
owner completion and reopen fixtures preserve the exact candidate and leave
branch heads unchanged. Failure tests cover forged bindings, interrupted writes,
fsync failures, staging failures, corrupted staging input and a wrong returned
staging descriptor; no failing case can call `CompleteRun`. A deterministic
clock confirms cleanup remains within the existing owner-phase timer.

The first test capture retained nine passes and eleven fixture-setup failures.
Those fixtures wrote worker output before dispatch and correctly hit the
owner's existing empty-attempt-directory preflight. Moving their synthetic
production into the injected worker callback corrected the fixtures without
changing that guard. The final focused capture is separate from those retained
failures.

The [combined regression](../../../workspace/test-logs/federal-corpus-audits/sparse-compaction-serialization-20260925/combined-r1-receipt.json)
passed **531 checks across 11 files** in 42.49 pytest seconds (44.421463 seconds
for the bounded subprocess), with zero failures, errors or skips. All 7,743
canonical package Python files and selected tests stayed unchanged during
capture. Protected checkpoint and historical receipt sizes and SHA-256 values
remained exact. The selection includes owner/registry completion and recovery,
worker and sparse codecs, field validation, HF package reopening, pinned-tree
semantic gates and the round-trip pilot. Focused and combined counts overlap
and must not be added.

Combined receipt SHA-256:
`b406eb489e537fe3b2b0a15bb2a971f9ff8b02edbc1d9be0723ec54077ca5633`.

Native training validation remains deferred at the user's request. No new wall time per legal span or bridge-on evaluate is
claimed. Only `lake build <Lib>` is a Lean admit, and the Constitution remains
unformalized.
