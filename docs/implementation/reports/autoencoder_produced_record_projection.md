# Immutable produced-record projections

Implementation report, 2026-09-26. The new
[`autoencoder_produced_record_projection.py`](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_produced_record_projection.py)
binds an existing bounded corpus batch to its complete source partitions and
producer receipt set. This supplies the missing per-batch artifact for the
subsequent v8 owner/worker integration. It does not activate a training job,
change old job identities or create a new model qualification.

The [v8 integration follow-up](autoencoder_campaign_training_jobs.md) is now
implemented across worker, coordinator and daemon inputs. Its offline tests and
archived artifact probe passed separately; combined source/resource qualification
remains incomplete, and native validation remains deferred. The integration
outline below records the contract carried forward into that implementation.

The [receipt-set milestone](autoencoder_embedding_receipt_sets.md) preserves
the whole declared source population across producer batches, including failed
and unattempted inputs. The new projection stores only the requested batch's
record summaries, explicit source occurrences, original leaf receipt references
and result ordinals. Its root binds the exact receipt-set, source-partition and
corpus-manifest hashes and byte sizes, plus dataset and split snapshot IDs.
Text and vector payloads remain in the existing manifest and producer receipts.

Existing `CorpusManifest` v1 remains authoritative: records retain canonical
source-aware order and training/validation roles retain their explicit order.
The projection never rebuilds connected groups from the surviving embeddings.
Training roles must come from the frozen training partition; validation roles
must come from its validation partition. Both groups must pass authorization
before either resolver is called. Canary and holdout sources cannot enter this
training-batch projection. Their membership and other source exclusions remain
visible through the referenced full campaign, not a smaller denominator.

The codec accepts corpus mode with its existing qualified English U.S. Code
frontend and the pinned producer's 384-dimensional vectors. Diagnostic manifests,
injected producer profiles, absent/failed producer results and mismatched leaf
provenance reject. A `native` declaration remains an integrity claim from the
historical receipt, not cryptographic attestation of runtime execution.

Limits are 256 records, 4 MiB projection JSON, 64 MiB of selected leaf receipt
bytes and 64 MiB of distinct selected source bytes. Callers may lower these
bounds. All closures are preflighted before resolver I/O. Text and numeric
profile bounds are checked before further record serialization; the existing
manifest is revalidated with tighter batch limits. Duplicate record identities
and source occurrences reject. Selecting a different physical alias changes
the projection while preserving its original record, input, group and split.

`selected_artifacts()` returns detached, sorted, deduplicated receipt and source
descriptors. `EmbeddingReceiptSet.selected_leaf_artifacts()` supplies bounded
leaf references directly from its immutable metadata. It does not serialize the
full campaign or scan all input dispositions. A projection reuses an already
validated exact receipt-set object; the future worker must still load that
object from the job's trusted root descriptor and full inventory/partition
closure. Reusing in-memory immutable metadata does not verify current disk bytes.

`load_produced_record_projection()` verifies exact canonical root bytes and
their metadata bindings, with an expected SHA and optional exact byte size.
The caller must obtain the expected identity from a trusted descriptor. Metadata
loading alone does not authenticate an opaque record payload or its source text.
`verify_batch()` additionally requires the exact manifest identity, ordered
roles and summaries, then verifies supplied records against their selected
producer leaves and source bytes. A final rehash covers the union of selected
leaf/source files across both operation groups, catching a later group's
resolver mutating an earlier verified file. Unselected leaves and sources need
not be staged and are explicitly not reverified.
Each exact reference is resolved to a local path once per verification call.
The final rehash uses those captured paths without invoking caller callbacks
again, so a callback cannot mutate an already rechecked file during the final
pass. This caches paths only: file contents are still hashed afresh. Receipt-set
construction, full verification and selected-record verification use the same
rule. External concurrent writers still require immutable-artifact discipline;
sequential hash reads are not a filesystem transaction or runtime attestation.

Exclusive saves and directory synchronization preserve immutable artifacts.
Loaded metadata reports current leaf/source verification as false. Successful
batch verification reports only the supplied manifest and selected files as
verified. Every result keeps training eligibility, global holdout qualification,
source authority, runtime attestation and Lean admission false. The projection
is an input contract, not an owner lease or training completion receipt.

The [offline audit](../../../workspace/test-logs/federal-corpus-audits/produced-record-projection-20260926/probe-r1/audit-receipt.json)
passed **590 tests**, with no failures, errors or skips. The
[artifact probe](../../../workspace/test-logs/federal-corpus-audits/produced-record-projection-20260926/probe-r1/probe/projection-report.json)
selected the first three embedded training inputs and first three embedded
validation inputs in the archived receipt's order under the unchanged frozen
source assignments. It did not reseed or substitute another selection. Exact
source files came from the preceding 64-input materialization; this probe
freshly checked their bytes/selectors without decoding Parquet again.

The archived single-leaf native declaration remains historical. Unit cases
exercise multiple leaves using explicit injected vectors with native profile
declarations for contract testing only. No embedding runtime, training, bridge
evaluation, live Quack listener, production DuckLake activation or Hugging Face
upload ran. Native training validation remains deferred.

The saved projection is **9,566 bytes**, SHA-256
`c1475c512577888be5ab3309204dd8a10a36272b4fe65d990b80695026432bb4`.
It binds the existing 9,557,340-byte receipt-set root
`fdeb6de13bfa66914baad8703f2caa85694d17c2d2c6a3024e275f5984cf95c7`
and a 111,812-byte corpus manifest
`a7091d80cc84d45adf530b7c21d4d85a45b8a3aa3a97a119a373d80e150f7fa3`.
All six records preserve their original archived producer leaf provenance.
The campaign still accounts for 62,931 physical rows and 62,839 unique inputs:
51 embedded, 13 over-length and 62,775 unattempted. This six-record selection
does not replace that denominator or establish a held-out model result.

| Separately timed offline phase | Wall seconds |
|---|---:|
| Source inventory load | 1.174363 |
| Source partitions load/full inventory revalidation | 2.886917 |
| Receipt-set load/full partition revalidation | 3.146102 |
| Decode 51 archived records and check all 64 original source selectors | 0.045549 |
| Build six-record corpus manifest | 0.009615 |
| Build projection with fresh selected closure verification | 0.128776 |
| Save projection | 0.006045 |
| Reopen projection metadata against already loaded roots | 0.000456 |
| Verify exact six-record batch with fresh selected file checks | 0.114167 |

Projection construction and each fresh batch verification resolved one leaf
and six source paths exactly once, although file contents were checked again
during verification. The metadata-only reopen invoked neither resolver. Full
root setup remains necessary; the sub-millisecond projection reopen excludes
the inventory, partition and receipt-set loading above. These different scopes
must not be presented as an end-to-end speed comparison.

The probe took 9.154507 seconds, the tests 27.519948 seconds and the complete
resource-wrapped capture 46.875940 seconds. These enclosing durations are not
additive to the phase table. One worker used one reserved CPU slot, a 2,048 MiB
cooperative memory budget and a 250 MB disk reservation. Approximately 8.0 MB
of attempt artifacts remained at release. Five-second RSS samples do not
establish peak memory. OS page-cache state was uncontrolled; the run is not
claimed cold. Metric disk-cache flag was `0`, bridge names were `[]`, prover
evaluation was false and worker count was one. No per-span formalization or
bridge-on inference/training measurement was performed.

The [regression receipt](../../../workspace/test-logs/federal-corpus-audits/produced-record-projection-20260926/probe-r1/tests/produced-record-projection-tests-r1-receipt.json)
includes the original source, inventory, manifest, receipt-set and producer
suites plus projection cases. Checks cover exact manifest and role order,
multiple leaves, shared-leaf deduplication, aliases, split authorization before
I/O, signed zero and provenance drift, absent unrelated artifacts, strict
serialization and resource bounds. Mutation cases exercise later operation
groups changing earlier files; callback-count cases enforce captured-path final
verification. All **7,757 package source hashes**, test/harness inputs, archived
source artifacts and protected checkpoints stayed unchanged through capture.
The [immediate closeout](evidence/autoencoder_control_plane_plan/produced-record-projection-closeout-20260926-r1.json)
passed its final source/artifact guard. The
[resource receipt](../../../workspace/test-logs/federal-corpus-audits/produced-record-projection-20260926/probe-r1/resource-release.json)
confirms released reservations and no surviving child process.

The next integration must preserve separate scopes:

| Binding | Owner |
|---|---|
| Full inventory, source partitions and receipt-set revision | Explicit immutable campaign/variant binding shared across jobs |
| Exact manifest and produced-record projection | Individual bounded job |
| Selected original leaf receipts and text artifacts | Exact staged job closure |
| Complete shared targets, private weight view and accepted sparse patch | Existing independently checked training/candidate path |

Registry variants are immutable. Adding receipts changes the campaign root;
preseal the needed campaign or introduce explicit campaign revisions. Do not
silently replace a registered root, create unrelated model variants per shard
or put a batch's projection in the immutable campaign identity.

V8 requires explicit new job fields and separate owner/worker verification.
The current worker reads source bytes before v5 index authorization, so the
new branch must authorize projection roles before entering that read path.
Coordinator staging, completion receipts, daemon exports and checkpoint
provenance must recognize the new roots/projection instead of manufacturing
old `CorpusIndex` or single-production fields. The generic variant registry
stores manifest JSON and does not itself require a new SQL table for this binding.

Existing Arrow input v1 stores one production SHA. Multiple producer leaves
require an explicit new IPC contract bound to projection/manifest identity and
ordered records. Optional Arrow feature weights are independent; this projection
adds no zero-copy vectors or new weight backend. Keep v1–v7 job and Arrow v1
semantics unchanged. The current Hugging Face model package also does not publish
arbitrary transitive corpus artifacts merely because variant JSON names them;
complete corpus/provenance package closure remains separate work.

The efficiency opportunity is to keep large campaign metadata resident within
a qualified worker/owner session and stage only bounded selected artifacts.
That saves repeated whole-campaign serialization and unrelated source reads.
Fresh campaign loading still revalidates the full inventory and grouping, and
selected receipt files are still decoded in full. Measure these setup costs
separately from training; neither a small projection nor fast metadata verification
establishes a bridge-on speedup or improved model quality.

Source authority, complete federal-law coverage, semantic support and actual
Lake proofs remain outstanding. The Constitution remains unformalized and no
span may receive `roundtrip_ok`. Only `lake build <Lib>` supplies the required
Lean admission; temperature, context limits and no-weight-download constraints
remain unchanged.
