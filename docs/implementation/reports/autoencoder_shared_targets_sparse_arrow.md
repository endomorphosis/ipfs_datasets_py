# Shared targets, accepted sparse patches and mapped feature weights

Implementation and qualification milestone, 2026-09-25, for the
[federal-law training plan](../plans/FEDERAL_LAW_END_TO_END_TRAINING_PLAN.md).
This is a bounded implementation of its next training slice, not completion of
the all-corpus program or production DuckLake/Hugging Face deployment.

## Outcome

Two alternating fresh/shared comparisons on the pinned restart12 checkpoint
reduced median complete-job wall time from **15.0955 to 9.7913 seconds**
(35.1% less). Every run produced identical complete candidate bytes, before/after
numeric evaluations and one accepted epoch. Each evaluation retained three
targets. The workload is the three public semantic gates, used in-sample;
these are not held-out results or legal admissions.

Accepted sparse capture and owner replay passed with the same final candidate.
Mapped Arrow feature rows also preserved that candidate, but did not improve
complete-job latency in this small comparison. Both remain explicit options;
full recovery checkpoints are still retained.

Follow-up: [lossless target bundles and selective hydration](autoencoder_target_bundles.md)
addresses the target artifact/load overhead measured below. This report retains
the original JSON-snapshot benchmark as historical evidence.

Evidence: [native benchmark receipt](evidence/autoencoder_control_plane_plan/shared-target-sparse-arrow-20260925.json).
The [first failed qualification attempt](evidence/autoencoder_control_plane_plan/shared-target-first-attempt-20260925.json)
is separate. It exposed duplicate dependency discovery through repeated Python
search paths; identical distribution name/version entries are now deduplicated,
with a regression test. The successful comparison rebuilt targets and restarted
all workers after that fix.

## Implemented paths

Paths below are relative to `ipfs_datasets_py/optimizers/logic_theorem_optimizer/`
unless qualified otherwise.

| Component | Behavior |
|---|---|
| `legal_ir_target_snapshot.py` | Seals complete documents, rich grammar inputs, exact sample payloads, configurations and status inventories; verifies digests and reconstructs compatible target objects |
| `autoencoder_target_preparation.py` | Builds targets directly with metric and multiview caches bypassed; binds package Python contents, runtime dependency inventory, exact embeddings and bridge settings |
| `modal_autoencoder_patch_codec.py` | Encodes exact typed postimages, before hashes, base/result logical identities, local revisions, sequence and provenance; verifies transactional replay |
| `modal_autoencoder.py` | Calls the optional accepted-patch sink after successful commit, including deadline-retained acceptance; permits a reconciled mapped legacy feature table during normal state construction |
| `modal_autoencoder_arrow_weights.py` | Writes/verifies uncompressed IPC for `feature_embedding_weights`; maps readonly float64 buffers and supplies private tracked row overlays |
| `modal_autoencoder_state_version.py` | Explicit exact-type adapter preserves ordinary mutation callbacks without eagerly expanding the mapped table |
| `autoencoder_training_worker.py` | v2 jobs accept staged targets, sparse capture and optional Arrow artifacts; retain complete JSON candidates and detailed receipts; v1 serialization keeps its original fields and canonical hash behavior |
| `autoencoder_training_coordinator.py` | Requires owner-staged inputs, replays patches against the base, compares directly with persisted candidate JSON, stages segments and binds completion to the live attempt/fence |
| `logic/legal_document.py` | Monotone clause selectors distinguish repeated text and map normalized whitespace to exact source codepoint/UTF-8 offsets |
| `scripts/ops/legal_ir/run_constitution_on_state.py` | Uses source/version/span-bound compiler document IDs; refuses overwriting existing receipts |

Target snapshots preserve full graph timestamps and document hashes. Plain JSON
dict targets, unknown object types and ordinary lossy metric-cache summaries
are rejected; explicit timeout fallback objects retain their failure status.
Target `accepted` remains optimizer metadata. The worker checks target/sample
membership, full source/configuration binding and the sealed snapshot identity.
Ready and timeout target counts are reported separately.

The source manifest conservatively hashes the package's Python files, including
working-tree content, before and after work. It does not attest bytecode loaded
before the first check or external dependency bytes merely from their installed
version labels. Source changes in resident processes fail instead of silently
switching parsers. Unrelated package changes also invalidate this conservative
manifest; a smaller qualified dependency closure remains future work.

Sparse capture does not serialize rejected line-search trials. Callback failures
prevent candidate registration. The owner checks segment order, size, hashes,
job/spec provenance, identities and revisions, then compares replayed state with
the **raw parsed candidate JSON**. It does not normalize the candidate through a
loader that could discard extra fields. Reads are bounded; oversized segments
fail at the codec's 64 MiB limit. Owner completion records the ordered artifacts
with its run attempt, generation and fence.

Qualification covers the optimizer's accepted-patch replay path. Existing
transaction patches do not encode arbitrary outer-table insertion/reinsertion
order, so this is not a guarantee for arbitrary user-authored transaction logs.
Nested postimage mapping order and float64 bits are preserved. Existing logical
identity hashing can scan dirty components; receipts expose that cost. Full
candidate replay/staging remains synchronous and can delay lease renewal for
unusually short leases or large artifacts; production supervision is still
required before scaling those cases.

The Arrow codec is a separate **private legacy** representation. It preserves
source-like keys and never relaxes the typed-key validator. Only the feature
embedding table is mapped. JSON startup parsing, Python key/index objects,
identity hashing, structured targets and final serialization still allocate.
The constructor reconciles original keys/order/values, including negative zero,
and rejects overlays that would evade ordinary float normalization. Worker
cleanup closes the mapped base on success or failure.

## Measured wall times and scope

Every row below uses three samples and all five bridges:
`modal_frame_logic`, `deontic_norms`, `fol_tdfol`, `cec_dcec`,
`external_prover_router`. Provers false; metric disk cache 0; sample memory false;
one training process and one bridge worker; fresh process per job;
`python_sparse_batch`; CUDA disabled; BLAS/OpenMP threads 1; temperature 0;
one epoch, one update family, one line-search attempt, max seconds 180.
OS file-cache warmth was uncontrolled.

Fresh rows construct targets with initially empty process target caches.
Shared rows reuse a previously sealed complete snapshot. They are explicitly
**not cold target-generation measurements**. All before/after target counts are
3/3; all shared targets have status `ready`. The profiler's
`before_holdout_evaluation` label refers to these in-sample rows, not a holdout.

| Mode | Observations | Complete job wall time | Wall time / training span | Initial bridge-on evaluate | Evaluate / span |
|---|---:|---:|---:|---:|---:|
| Fresh targets, JSON weights | 2 | 15.0955 s median | 5.0318 s | 10.7017 s median | 3.5672 s |
| Shared targets, JSON weights | 2 | 9.7913 s median | 3.2638 s | 1.6688 s median | 0.5563 s |
| Shared targets + sparse capture/replay | 1 | 12.1534 s | 4.0511 s | 1.7154 s | 0.5718 s |
| Shared targets + sparse capture/replay + Arrow feature table | 1 | 12.7500 s | 4.2500 s | 1.5821 s | 0.5274 s |

Complete-job timings include worker startup and owner persistence/replay. Bridge
evaluation timings exclude target loading. Shared target verification/loading
took 3.054–3.189 seconds in the paired JSON-weight runs. The smaller evaluate
number therefore cannot be substituted for the whole job's speedup.

One-time target preparation took 15.7159 seconds inside its preparation process,
including 11.5083 seconds generating three targets (3.8361 seconds/span).
That cost is excluded from reuse-job timings and must be amortized across jobs.
On this tiny fixture, the observed 5.3042-second saving per reuse puts approximate
break-even around three to four equivalent jobs once startup/staging is included;
this is an estimate, not a corpus forecast.

Sparse segments were 2,381 bytes for the JSON worker and 2,393 bytes for the Arrow
worker, versus a 25,895,897-byte full candidate. Their job provenance differs.
Both replayed to that same candidate and survived owner reopen. These are patch
sizes, **not measured reductions in total I/O**: this qualification still writes
and stages the full candidate, and replay verification adds latency.

The feature-table IPC file was 6,656,154 bytes: 52,142 rows and 417,136 float64
values, with 3,337,088 numeric buffer bytes. Construction from the original JSON
feature mapping took 0.2278 seconds in its process. The native Arrow run performed
2,463 additional mapped-row reads during training with zero reported row
materializations. Its selected update family was `legal_ir_view_global_logits`,
so this benchmark did not mutate feature rows; focused tests separately exercise
feature updates, rollback and projection parity.

After-training PSS was 953,342 KiB in the single shared+sparse JSON run and
941,079 KiB in the Arrow run. Before-training Arrow PSS was higher. These are
single-process observations with different allocation histories, not a qualified
parallel-memory saving. Arrow's extra complete-job time and this limited evidence
do not justify making it the default backend yet.

## What the profile says to do next

The full three-target snapshot was **20,525,163 bytes**. A separate native
one-sentence size inspection found a 13,176,965-byte snapshot for the backup
sentence: about 1.09 MB of package/configuration manifest and 12.08 MB of target
document. Modal graph views dominated: Neo4j graph data 5.60 MB, modal IR 3.52 MB
and frame logic 1.46 MB. An exact 1.37 MB triple subtree was duplicated. That
inspection ran beside tests; no timing claim is made from it.

Before any all-Code campaign, prioritize content-addressed shared manifests,
lossless subtree deduplication/compression, bounded target shards and avoiding
repeated graph hydration. Reconstruct the identical complete target; do not
remove fields, grammar inputs or bridges to make artifacts smaller. The current
whole-snapshot JSON codec is a qualified compatibility baseline, not a claim of
corpus-scale memory efficiency.

Then qualify sparse-only version artifacts with periodic full compaction, a
nonblocking owner staging path, Arrow samples/targets and broader weight
components. Keep typed source/sample manifests, authoritative split membership,
embedding chunk joins, source-aware Constitution samples and complete child-clause
enumeration as explicit remaining corpus prerequisites. Worker dataset/split
labels remain unverified caller labels; no held-out promotion is enabled.

## Validation and use

The final combined selection passed **270 tests in 31.66 seconds**: complete/rich
target parity and failure handling; exact embeddings/content hashes; sparse
accepted/deadline/rollback/recovery cases; Arrow readonly-buffer and copy-on-write
behavior; state identity/checkpoint compatibility; worker/owner integration;
source selectors; Constitution safeguards; and the mandatory semantic gates.
This is a focused selection, not the entire repository test suite.

The native benchmark used the actual checkpoint, optimizer, spawned workers and
durable DuckDB owner. It preserved branch heads, reopened all completed runs and
verified the pinned checkpoint remained SHA-256
`1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd`.
It uses the local owner API; it does not claim native Quack routing, production
DuckLake materialization or HF upload occurred in this measurement.

To reproduce, choose a new receipt path from this source tree:

```bash
PYTHONPATH="$PWD" python3 scripts/ops/legal_ir/benchmark_shared_autoencoder_training.py --pairs 2 --output /tmp/shared-target-benchmark-new.json
```

For persistent jobs, call `prepare_training_targets()` on `SampleRecord` inputs,
stage its artifact through `AutoencoderRegistry.stage_artifact()`, and place its
snapshot ID plus owner-staged `{path, sha256, bytes}` in the v2 job's
`target_snapshot_id` and `target_snapshot_artifact`. Set
`capture_sparse_patches=True` to qualify accepted replay. For mapped feature
weights, build one IPC artifact against the exact base-checkpoint SHA, stage it,
and supply `arrow_feature_weights_artifact` using the same descriptor shape.
Dispatch through the existing `run_training_jobs()` path. These options do not
promote a model head or publish a release.

No full Constitution run was started, historical receipts were not overwritten,
and no Constitution span was marked `roundtrip_ok`. The corrected per-span
vocabulary identity requires a separately labeled future census; historical
counts are not reinterpreted here. No weights were downloaded, context window or
temperature changed, Mathlib imported, or HACC/`hallucinate_app` edited. No Lean
admission occurred: **only actual `lake build <Lib>` remains the Lean admit**.
