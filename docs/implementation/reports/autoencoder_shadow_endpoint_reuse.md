# Reusing verified checkpoint endpoints for sparse shadow replay

The optional sparse shadow in the
[independent daemon verifier](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_invocation_worker.py)
previously hydrated five full checkpoint graphs: the mandatory base and final
candidate, then a second base/final pair for shadow capture, followed by a fresh
base for independent replay. The shadow remains diagnostic, off by default, and
the full compact candidate remains authoritative.

The verifier now retains its two loader-origin endpoints in a private,
single-use holder. Ordinary candidate validation, metadata/provenance checks,
observations and sample-memory checks still finish before shadow work begins.
The holder records the original descriptors and revisions at loading time;
consumption checks the creating process/thread, exact references, native/full
float64 shape, absence of delta recovery or active transactions, unchanged
revisions and current artifact bytes. It supplies no serialized authority token
and adds no caller-provided `verified` flag or public loading bypass.

The [shadow implementation](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_sparse_shadow.py)
uses the same capture, independent replay and complete-state comparisons for
both entry paths. It consumes and clears the holder, drops the original base,
collects it, and only then reloads the immutable base for independent replay.
Every raw native component, revision, canonical state and metric identity must
match, and the compact candidate must regenerate byte-for-byte using its exact
metadata and lineage. Descriptor checks before and after publication remain.
The final source/input/weight-session guards in the supervised verifier remain
mandatory. A passing shadow receipt cannot replace those guards or register a
candidate by itself.

The public `write_checkpoint_shadow` API and its standalone three-load behavior
remain unchanged. The opted-in verifier needs three hydrations in total rather
than five: its original base/final pair and the independent replay base. The
default verifier still uses only its mandatory base/final pair. Request and
receipt top-level schemas, sparse codec, compaction policy, registration and
admission rules are unchanged.

Timing separates prior endpoint loading from the shadow interval. The reuse
path records `reused_endpoint_load_seconds`, `reused_endpoint_count`, and
`endpoint_handoff_check_seconds`; it does not report a fictitious zero-cost
`load_endpoints_seconds`. The standalone path retains that original load timer.
Prior load time overlaps the caller's verification duration and must not be
added to total duration a second time.

The memory tradeoff is longer retention of the original base through final
candidate validation. Ownership transfer and release before independent replay
prevent an additional live endpoint graph at that boundary, but load counts
alone do not establish a lower RSS or process-tree peak. The option remains
bounded by existing resource admission and artifact limits. The required independent base scan, patch encoding, complete-state comparison
and compact-byte regeneration remain; the removed work is redundant endpoint
hydration and its associated loader reads.

The [synthetic storage profile](../../../workspace/test-logs/federal-corpus-audits/shadow-endpoint-reuse-20260925/shadow-profile-receipt.json)
used 131,072 feature values and all 38 native components, with six scalar changes
in the final checkpoint. Three alternating observations per arm measured median
wall time of **1.655960 to 1.409213 seconds**, 14.90% lower for this slice. It
includes endpoint hydration, selected plain/metric/manifest checks, complete
shadow reconstruction and durable patch/receipt writes. It excludes actual
owner input/observation validation, leases, training and evaluation. Filesystem
cache state was uncontrolled; this is not a cold-cache or end-to-end claim.

All six timed calls and two separate instrumentation calls emitted the same
2,790-byte patch, SHA-256
`57bcbcd660ef87f4ef054d627cf6038c652de8509c2845dc0c68760dab903171`.
All semantic receipt fields matched after excluding only documented timing and
output-reference fields. The compact final artifact stayed exactly bound to its
original 267,057 bytes and checksum. An untimed loader audit counted **five to
three** loads, with at most two loaded state graphs observed at loader returns
in both arms. Both retained two normal cyclic state graphs until final garbage
collection, then zero. The whole diagnostic's peak RSS was 82,305,024 bytes;
that is not an arm-specific memory saving. The timed calls were uninstrumented.

All 7,743 package source hashes, endpoint artifacts, frozen baseline and
scheduler configuration stayed unchanged during the profile. The dedicated
process denied network access and exited successfully. The existing shared
100 MB storage / 1 CPU / 1,024 MiB reservation was
[released](../../../workspace/test-logs/federal-corpus-audits/shadow-endpoint-reuse-20260925/shadow-resource-release.json)
after durable evidence. Its retained diagnostic files totaled 7,374,841 bytes.
The original failed reservations remain accounted for. Profile receipt SHA-256:
`1980914817b92d27199203eab12ec8b55ef6892f02eaa3b5b4a6dca4dafb07b6`.

The [new handoff tests](../../../tests/unit/optimizers/logic_theorem_optimizer/test_shadow_endpoint_reuse.py)
passed **32 checks in 0.91 pytest seconds**, with stable package/test hashes in
the [focused receipt](../../../workspace/test-logs/federal-corpus-audits/shadow-endpoint-reuse-20260925/focused-r2-receipt.json).
They compare exact public/private patch bytes and all 38-field evidence for
compact and legacy bases, multi-field changes, signed zero, deletion, unchanged
and revision-only states. They reject changed artifacts, descriptors, metadata,
tracked mutations even when normalized identity stays equal, wrong types,
wrong process/thread, and incomplete/reused holders. Tests
also check automatic cleanup, independent replay, full compact-byte comparison,
durable receipt failures, and actual verifier load counts/lifetimes.

The first focused run retained 150 passes and two fixture-only failures in
[its receipt](../../../workspace/test-logs/federal-corpus-audits/shadow-endpoint-reuse-20260925/focused-r1-receipt.json).
Both fixtures matched exact patch/evidence parity but expected row updates when
canonical key ordering correctly required a whole-component replacement.
Choosing an inserted key after the retained key makes the fixture exercise its
intended row insertion/deletion case. The revised cleanup helper checks automatic
closure before explicitly testing idempotent close. No production code changed
in response to these fixture corrections. The existing worker, public-shadow
and owner-shadow selections supplied 120 of the passing checks in that capture.

The [combined test execution](../../../workspace/test-logs/federal-corpus-audits/shadow-endpoint-reuse-20260925/combined-r1-receipt.json)
passed **504 checks across 15 files in 97.74 pytest seconds** (99.997264 seconds
for the bounded subprocess), with no test failures, errors or skips. However,
**the whole-package source guard failed**, so this is not a qualifying combined
capture. During the run, external edits changed:

- `ipfs_datasets_py/logic/autoformal/supervisor_todo.py`
- `ipfs_datasets_py/logic/deontic/ir.py`
- `ipfs_datasets_py/logic/deontic/utils/deontic_parser.py`

Both implementation files, selected tests and protected artifacts stayed
unchanged. The receipt retains all before/after hashes and `passed: false`.
Its test selection includes full checkpoint/patch/diff contracts, owner and
worker recovery, mapped-weight session boundaries, semantic gates and the
round-trip pilot. Passing test execution does not repair the source-provenance
failure. No guard was weakened and no alternate checkout was substituted.
The earlier focused tests and synthetic profile had stable source hashes during
their own captures; their evidence is limited to those captured sources.
Focused and combined counts overlap and must not be added.

Combined receipt SHA-256:
`b82f887c5adeeb6ab8c90091446c079b4688f1461cb3896cc71c2314abd428d6`.
The frozen [worker](../../../workspace/test-logs/federal-corpus-audits/shadow-endpoint-reuse-20260925/autoencoder_daemon_invocation_worker.before.py)
and [shadow implementation](../../../workspace/test-logs/federal-corpus-audits/shadow-endpoint-reuse-20260925/autoencoder_daemon_sparse_shadow.before.py)
remain available for review. The final implementation hashes are
`6f8d85259db92105eba40ab9c2779ddcc8aef674eb748af74d6d4f9c04774355`
(worker) and
`2dd926409674f2cf9b32b89bf5549a015c63377d6f51d4a6d5c86b3b91f7184c`
(shadow).

Native training validation remains deferred. This change does not establish an
end-to-end training speedup, wall time per legal span or bridge-on evaluation
time. It does not activate DuckLake, publish to Hugging Face, or promote a
model. Future native qualification needs fresh source-bound inputs; canonical
tree and producer guards are unchanged. The Constitution remains unformalized
with no new `roundtrip_ok` spans. Only `lake build <Lib>` is a Lean admit.
