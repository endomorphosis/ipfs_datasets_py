# Sparse checkpoint persistence and bounded compaction

Implementation milestone, 2026-09-25, continuing
[target bundles](autoencoder_target_bundles.md) and the
[federal-law training plan](../plans/FEDERAL_LAW_END_TO_END_TRAINING_PLAN.md).

Subsequent update: [verified corpus batches](autoencoder_verified_corpus_batches.md)
replace reconstruction during input-descriptor preparation with a bounded
artifact inventory. Worker and owner replay remain required. Timings below
describe this earlier milestone before that preparation optimization.

## Implemented behavior

Training jobs can opt into `candidate_storage="sparse"` under the v3 schema.
They write only accepted postimage patches and a small manifest referencing
their immutable parent. They do not write a full `candidate.state.json`.
The manifest binds ordered patch hashes/sizes, parent bytes, base registry
version, job provenance, resulting logical identity/revision, and the exact
SHA-256/size of the canonical full checkpoint it reconstructs.

The worker still serializes the complete state temporarily to compute that
exact checkpoint hash. The owner independently reconstructs the candidate,
checks its exact serialized identity and accepted-patch provenance, and stages
the manifest/patches before its existing fenced completion transaction. This
reduces persistence bytes; it does not eliminate full-state serialization,
identity hashing, Python object allocations or replay CPU.

`modal_autoencoder_sparse_checkpoint.py` resolves manifests through a trusted
descriptor-to-local-path callback. Artifact contents never supply paths or
network locations. Hash, size, closed schema, sequence, base version, before
hashes, revision and result-byte checks fail closed. Missing or extra worker
dependencies are rejected. Unknown full-checkpoint fields cannot disappear
silently during resolver loading.
The manifest also carries an incompatible `schema_version`, so older full-state
loaders reject it instead of constructing default weights from its metadata.

Each manifest represents one job. At each parent/child boundary, replay follows
the same `from_dict` reload behavior as a full checkpoint, including revision
zero. Revisions within a job remain strict. A caller can request the terminal
replay revision for candidate validation or compaction. Canonical materialized
bytes and logical state identities are separate fields.
`ResolvedCheckpoint.state_identity` and `replayed_revision` describe that
terminal stored candidate; its default `.state` has undergone normal reload.
Consumers recompute the reloaded base identity before starting the next job.

That distinction matters for restart12: its protected original artifact is
25,895,338 bytes with SHA-256
`1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd`.
Normal loading followed by canonical serialization produces different bytes.
Full legacy roots therefore retain their original physical byte identity;
sparse manifests declare their canonical reconstructed identity. Arrow remains
bound to the applicable materialized checkpoint SHA, never a manifest SHA.

## Owner policy and compatibility

`SparseCheckpointPolicy` compacts when chain depth reaches eight jobs or total
patch bytes reach 50% of the full anchor's bytes. The owner chooses bounded
thresholds; workers cannot relax them. Compaction writes a new full checkpoint,
checks it against the reconstructed exact byte identity, then registers that
artifact through ordinary completion. The worker manifest remains audit
evidence. No existing checkpoint or mapped file is overwritten, and no old
anchor or segment is garbage-collected by this implementation.

Default resolver bounds are eight manifest edges, a 1 MiB manifest, a 512 MiB
full checkpoint, 64 MiB per patch, 256 MiB aggregate patches, 4,096 artifacts
and 4 GiB of referenced artifact bytes. These are input/acceptance bounds, not
peak-RSS guarantees or the campaign-wide quota. Reserve old and new anchors,
scratch, WAL, receipts and exports together under the existing storage ceiling.
Aggregate storage reservation/retention remains separate production work.

The registry schema and version-record shape are unchanged. Results record
`checkpoint_storage`, dependencies, materialized identity, chain depth, patch
bytes and compaction reasons. `registered_checkpoint_inputs(registry, version_id)`
verifies an existing version and returns its staged root plus explicit dependency
descriptors for a subsequent job. This preparation reconstructs the chain and
has a real CPU/memory cost.

Explicit v1/v2 job encodings preserve their canonical identities. Schema-less
job JSON retains v2 meaning. New sparse jobs must explicitly request v3; full
output remains the default. v3 full output additionally requires its physical
candidate descriptor to equal its claimed materialized byte identity.

The offline Hugging Face exact-resume packager rejects sparse manifests as
`state.json`. Materialize and register a verified full checkpoint first, then
use the existing package path. No upload, publication, inference promotion,
new language qualification or production DuckLake activation occurs here.

For a new sparse job, use the current worker's `SCHEMA_VERSION`, obtain its
`base_checkpoint` and `base_checkpoint_dependencies` from
`registered_checkpoint_inputs()`, and set `candidate_storage="sparse"` with
`capture_sparse_patches=True`. Supply the ordinary verified samples/targets
and dispatch through `run_training_jobs()`. The owner retains its default
compaction policy unless explicitly given a `SparseCheckpointPolicy`.

Owner replay/staging is still synchronous. Existing leases/fences reject stale
completion; short-lease liveness under slow staging still needs nonblocking
supervision. Independent candidate branches are supported; patches from
different optimizations are not merged.

## Qualification and measured costs

The [final-format native receipt](evidence/autoencoder_control_plane_plan/sparse-checkpoint-persistence-20260925-r2.json)
passed. The earlier
[pre-marker development receipt](evidence/autoencoder_control_plane_plan/sparse-checkpoint-persistence-20260925.json)
is retained separately; it predates the additional legacy-loader schema guard.
Only the final-format comparison supplies the measurements below.

| Output mode, with patch capture | Dispatch through completion | Input/job preparation | Combined job time | Combined / span | Initial bridge-on evaluate | Evaluate / span |
|---|---:|---:|---:|---:|---:|---:|
| Full checkpoint | 10.8253 s | 1.5270 s | 12.3524 s | 4.1175 s | 1.8066 s | 0.6022 s |
| Sparse manifest | 9.8845 s | 1.5198 s | 11.4043 s | 3.8014 s | 1.7663 s | 0.5888 s |

Each row is the median of two alternating observations, three samples per job.
Sparse persistence reduced dispatch-through-completion time **8.7%** and the
combined job time **7.7%** on this fixture. Initial bridge-on evaluation excludes
target loading and preparation. Its small timing difference is not the main
source of the improvement. Owner replay/comparison fell from 2.7509 to 1.8871
seconds; sparse output avoids reading and reparsing a full worker candidate.
Worker canonical serialization still took roughly 0.32–0.34 seconds.

The full worker persisted a 25,895,897-byte candidate plus a 2,377-byte patch:
**25,898,274 bytes** of model payload. The sparse worker persisted a 911-byte
manifest plus a 2,381-byte patch: **3,292 bytes**, or **99.987% fewer worker model
payload bytes**. These exclude worker receipts, job descriptions and owner WAL.
Patch sizes differ because their provenance contains different job identifiers.
Both reconstruct the identical 25,895,897-byte candidate, SHA-256
`23fa2a50725fa5afe3f96da9ae84ea686df5fb49262aa1b6614321023a91799c`.

Newly retained owner artifact bytes were 25,973,361 for the first full run,
78,416 and 78,415 for the sparse runs, and 77,453 for the repeated full run.
The repeated full candidate already existed in the content-addressed store.
Therefore the per-worker reduction cannot be reported as an equal reduction
in total retained storage or physical I/O for every run.

One-time bundle preparation took **13.4423 seconds**, including 10.9601 seconds
of target generation (3.6534 seconds/span), and is excluded from reuse-job
timings. All targets were `ready`; no timeout fallback was used. All six jobs
retained three before/after targets and accepted one optimizer epoch. Complete
evaluation dictionaries, logical identities and materialized checkpoint bytes
matched their full-output counterparts.

After owner restart, two independent resumed workers completed in 15.1835
seconds for six training spans (2.5306 seconds/span aggregate throughput).
Preparing their inputs/jobs took another 4.1485 seconds, giving 19.3320 seconds
combined. Their initial bridge-on evaluations were 1.8878 seconds for the full
input and 1.7388 seconds for the sparse input; these are concurrent observations,
not another isolated latency comparison. The sparse branch compacted at the
explicit depth-two test threshold. Its resulting full checkpoint exactly
matched the full-output branch: 25,895,896 bytes, SHA-256
`5ab4ba54bffc19850d575ff0e9589cb8e5b4ac4d72c731c358c9469e0d2eaef7`.
Reopening again returned depth zero, revision zero and no dependent artifacts.

Read amplification remains a cost. In that resumed pair, base reading plus
state construction took about 0.94 seconds for the full input and 2.47 seconds
for the sparse input; the underlying receipt splits those stages differently.
Sparse worker total elapsed was 8.19 seconds versus 6.52 seconds for full input.
Sparse owner replay plus compaction took 3.89 seconds versus 2.83 seconds for
the full branch. These are single concurrent observations, but they show why
the persistence saving is not a claim of faster repeated sequential training.
Depth eight is a bounded policy default, not a measured optimum. Keep sparse
storage opt-in while qualifying chain-length and read-frequency tradeoffs.

All runs survived owner restart. Source hashes, pinned checkpoint bytes and
branch heads were unchanged. Retained scratch just before cleanup was
167,887,521 bytes; it was removed. This records retained fixture size, not peak
scratch, campaign-wide quota enforcement, or physical write volume.

The combined regression selection passed **437 tests in 40.43 seconds**. After
the exact v3 receipt binding and final legacy-loader marker fixes, the affected
codec/worker/coordinator/HF selection passed **142 tests in 12.83 seconds**.
Those selections overlap; their counts are not additive. Coverage includes
corruption, missing/extra closure, restart, revision resets, byte-exact
compaction, Arrow bindings, legacy job compatibility, full-output descriptor
tampering, direct-loader/packager rejection, and the mandatory semantic gates.
This is a focused selection, not the whole repository test suite.

The benchmark compares full-output and sparse-output v3 jobs with accepted-patch
capture enabled in both, one shared complete target bundle, and the same pinned
base. Two pairs run in alternating order. It checks exact materialized checkpoint
identities, logical identities/revisions, complete before/after evaluations,
accepted epochs, three ready targets and absence of a worker full checkpoint in
sparse mode. It then restarts the owner, resumes one job from each persisted
version in two independent workers, forces compaction at depth two, compares
the resulting full checkpoints and reopens the owner again.

Every job uses three public gate sentences in-sample and all five bridges:
`modal_frame_logic`, `deontic_norms`, `fol_tdfol`, `cec_dcec`,
`external_prover_router`; provers false; metric disk cache 0; sample memory
false; one bridge worker per training process; CPU `python_sparse_batch`;
CUDA disabled; BLAS/OpenMP threads 1; temperature 0; one epoch, one update
family, one line-search attempt and max seconds 180. Paired jobs use one
training process; the resumed pair uses two. Shared-target reuse is explicit;
generation bypasses metric and multiview caches, and OS cache warmth is
uncontrolled. These are not held-out canary results.

The next costs to address are repeated base reconstruction, source/sample/split
manifest verification for real corpus jobs, nonblocking owner staging and
storage reservations. The current single-owner path preserves the control
boundary, but it has not qualified production Quack routing or DuckLake/HF
materialization for sparse chains. Compacted full artifacts use the existing
full-checkpoint boundary. No CUDA change is justified by these measurements.

Dispatch-through-completion timing includes worker startup, owner validation,
replay and persistence. The benchmark separately records input closure
resolution, job construction/staging and run creation, and adds these for a
prepared-job end-to-end figure. One-time target preparation and initial base
staging remain separate amortized costs. Per-worker payload bytes and newly
retained staged files are separate quantities: repeated full candidates can
deduplicate in the owner store, while sparse manifests contain run-specific
provenance. Neither quantity measures physical device I/O or WAL writes.

To reproduce from the pinned tree, choose a new receipt path:

```bash
PYTHONPATH="$PWD" python3 scripts/ops/legal_ir/benchmark_sparse_checkpoint_training.py --pairs 2 --output /tmp/sparse-checkpoint-benchmark-new.json
```

Only actual `lake build <Lib>` is a Lean admit. No Constitution span is marked
`roundtrip_ok`; the Constitution remains unformalized. Model persistence,
optimizer acceptance, full compaction and database rows do not change that.
