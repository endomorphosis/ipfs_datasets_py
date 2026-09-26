# Checkpoint field validation without weight materialization

The worker and sparse checkpoint resolver previously called `state.to_dict()` to
obtain a set of top-level field names. That copies every numeric table, including
Arrow-backed feature rows, even though the temporary values are discarded.
The implementation replaces those key-only copies with the
native schema's fixed field set: 38 state components and two schema markers.
The artifact inventory uses the same field contract.

The checks remain after native state loading, preserving validation and error
ordering. Mapped feature weights still undergo exact source-row reconciliation;
state identity, patch replay and complete candidate byte checks remain in place.
The resolver's separate `from_dict(state.to_dict())` reload at a sparse job
boundary remains necessary for its documented normalization and revision reset.

This removes unnecessary materialization during input validation. It does not
make the entire training path zero-copy, remove full candidate serialization,
merge independently trained patches or change sparse/Arrow defaults. The owner
still independently verifies accepted patches before candidate registration.
The final full checkpoint and existing promotion requirements remain authoritative.

The [synthetic diagnostic](../../../workspace/test-logs/federal-corpus-audits/checkpoint-field-validation-20260925/field-profile-receipt.json)
used 2,048 feature rows with 131,072 numeric values, both ordinary dictionaries
and a verified mapped Arrow table. Six counterbalanced observations per arm
measured only the key check, excluding fixture construction, loading, audits and
allocation tracing. The measured operation did not run training or evaluation
and did not load a protected checkpoint.

| Representation | Previous median | Fixed-field median | Previous peak traced allocation | Fixed-field peak |
| --- | ---: | ---: | ---: | ---: |
| Ordinary weights | 0.996 ms | 0.000664 ms | 1,355,768 bytes | 272 bytes |
| Mapped weights | 12.094 ms | 0.001040 ms | 4,502,369 bytes | 272 bytes |

The mapped check previously accessed all 2,048 rows; the fixed-field check
accessed none. Both returned exactly the same field set and unknown-field
result. Allocation numbers come from separate single-call `tracemalloc`
observations; they are not whole-process RSS savings. The overlay's
`row_materializations` counter stayed zero in both cases because it counts
copy-on-write rows, not the scalar/list allocations made by `to_dict()`.
GC policy was unchanged during timing, and the fixture was already loaded.
All 7,743 package-source hashes stayed unchanged during this pre-edit capture;
the diagnostic's resource reservation was released.

The [native state contract](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py)
now supplies `MODAL_AUTOENCODER_STATE_SERIALIZED_FIELDS`; the
[worker](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_training_worker.py)
and [sparse resolver/inventory](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder_sparse_checkpoint.py)
use it only to validate names in their existing validation order.

The [focused regression](../../../workspace/test-logs/federal-corpus-audits/checkpoint-field-validation-20260925/fields-r2-receipt.json)
passed 236 checks in 8.81 pytest seconds, including 35 new
[field-contract tests](../../../tests/unit/optimizers/logic_theorem_optimizer/test_checkpoint_field_validation.py),
54 existing sparse-checkpoint tests and 147 worker tests. The new tests forbid
`to_dict()` through native full/mapped input loading and stop at an injected
model-constructor sentinel. They verify the fixed 40-field contract across
compatible architectures, empty/populated/hidden-proof states, default schema
fields, unknown-field rejection, malformed-known-field error ordering, mapped
cleanup and sparse-chain revision resets. Existing worker optimization fixtures
use injected training logic.

The first focused capture is retained with six fixture failures: expected
values overlooked the existing legacy architecture upgrade and int-to-float
normalization, and one test built an Arrow sidecar in an order that differed
from its sorted JSON source. The fixtures were corrected; no production loader
or Arrow verification rule changed to make them pass. The final focused capture
kept all three changed production files and the new test unchanged.

The [combined regression](../../../workspace/test-logs/federal-corpus-audits/checkpoint-field-validation-20260925/combined-r1-receipt.json)
passed **812 checks across 15 files** in 41.11 pytest seconds (43.123077 seconds
for the bounded subprocess), with zero failures, errors or skips. All 7,743
canonical package Python files and selected tests stayed unchanged during
capture. Protected checkpoint and historical receipt sizes and SHA-256 values
remained exact. The selection includes owner replay/compaction, worker and
sparse loading, Arrow weights, identity/transaction semantics, exact compact
checkpoint bytes, HF package reopening, the pinned-tree semantic gates and the
round-trip pilot. Focused and combined counts overlap and must not be added.

Combined receipt SHA-256:
`421fe08ab0d8d4e9fa16fac2e8e4ea338ea22b2a1d4e5c1212b42f48666d9568`.
Producer source changes still invalidate previously sealed source-bound inputs
where their existing guards require fresh preparation; this change does not
relax those guards.

Native training and bridge evaluation remain deferred at the user's request.
These local measurements do not establish complete-job throughput or new bridge
wall time per span. Only `lake build <Lib>` constitutes a Lean admit; the
Constitution remains unformalized.

A separate remaining cost is full serialization twice during owner compaction:
first to calculate the replayed candidate's exact byte identity, then to write
the same candidate. A follow-up can write one exclusive temporary full candidate,
validate its descriptor against the unchanged receipt/manifest checks, and stage
it only after those checks pass. Such a change must retain failure cleanup and
the owner's independent artifact verification. It is not part of this change.
