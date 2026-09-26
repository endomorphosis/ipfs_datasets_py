# Autoencoder control plane: durable owner and independent workers

Implementation milestone, 2026-09-25. This implements the first storage and
parallel-worker slice of the [DuckDB/Quack + DuckLake plan](../plans/AUTOENCODER_DUCKDB_DUCKLAKE_TRAINING_PLAN.md).
It does not activate the production DuckLake service or claim the full plan is
implemented. No checkpoint download, Hub upload, external checkout edits or
Lean admission occurred.

## Implemented boundaries

| Component | Concrete behavior |
|---|---|
| `duckdb_control/autoencoder_registry.py` | Reuses the existing `ConnectionManager` and canonical identity contracts; persists variants, immutable versions, heads, jobs, leases, operation receipts and destination-specific outbox records in an explicit dedicated DuckDB file |
| `duckdb_control/autoencoder_quack.py` | Opt-in native Quack prototype, with one loopback gateway/token per owner-assigned worker; closed ClaimRun/RenewLease/ReadRun/ReadVersion/CompleteRun commands; the served database never attaches the private owner database |
| `optimizers/logic_theorem_optimizer/autoencoder_training_worker.py` | Loads verified immutable checkpoint bytes into private state, enforces the workspace tree pin, runs existing bounded projection, and writes exclusive candidate/evidence files |
| `optimizers/logic_theorem_optimizer/autoencoder_training_coordinator.py` | Keeps DuckDB in the owner process, validates staged job specifications and variants, dispatches spawned workers, renews leases and verifies/stages returned artifacts before recording completion |
| `huggingface/autoencoder_release.py` | Builds a deterministic private exact-resume package and an actual existing `PublicationPlan`; preserves original bytes and verifies the complete local file closure; no network or upload |
| `scripts/ops/legal_ir/probe_autoencoder_storage.py` | Exercises actual installed pinned DuckDB, Quack and DuckLake in disposable processes/files without installing extensions |
| `scripts/ops/legal_ir/benchmark_autoencoder_control.py` | Compares the same two three-sentence jobs sequentially and concurrently, checks exact candidate and metric parity, reopens the owner and verifies that branch heads did not move |

The registry copies source artifacts into a content-addressed store, fsyncs
them, and publishes them without overwriting an existing destination. It never
hardlinks the source checkpoint. Artifacts are verified outside control
transactions. Rejected/incomplete attempts remain separate from selected
versions. The schema and artifact-root binding are checked on reopen; a damaged
existing database cannot silently bootstrap a new generation.

One owner holds the database for its lifetime. Owner restart changes its
generation, fencing old leases. Commands persist an operation digest and exact
receipt with their effects. Retry lookup distinguishes an identical replay
from reusing an operation ID for different content. DuckLake and Hugging Face
outbox records have separate consumers, leases and acknowledgements. Normal
training generates DuckLake intents; a Hub intent must be requested explicitly.
Neither intent is a completed external write.

The combined storage/transport/worker and existing semantic regression selection
passed **132 tests** in 15.22 seconds, with native storage probes enabled. This
includes the three semantic gates, empty-vocabulary behavior, decompiler
regressions and bridge-evaluation reuse. It is not a claim that the repository's
entire broader baseline test suite passes.

Root versions can initialize an empty branch. Candidate promotion otherwise
fails unless a trusted owner-side evaluation policy is supplied, and still
requires a head/version generation compare-and-swap. Workers cannot configure
that callback through Quack. Optimizer acceptance, durable candidate creation,
head promotion and Lean admission remain separate.

## Runtime qualification

The [storage receipt](evidence/autoencoder_control_plane_plan/storage-capabilities-20260925.json)
records real close/reopen and SIGKILL recovery, native Quack token/query denial,
and DuckLake catalog 1.0 writing and reopening Parquet. The installed extension
bytes match the existing workspace lock. The
[native command test receipt](evidence/autoencoder_control_plane_plan/native-training-transport-tests-20260925.json)
adds actual remote command mutations, independent-process use, reply isolation,
idempotent replay across restart and stale-lease rejection.

These establish isolated capabilities. They do not bypass DQK-088/094/102 or
activate a production catalog. A real incompatibility remains: this DuckLake
build lacks the global `ducklake_auto_migration` setting named by an existing
contract. The isolated probe uses its supported per-ATTACH
`AUTOMATIC_MIGRATION false`, and explicitly records the difference.

## Initial measured comparison

The [final training receipt](evidence/autoencoder_control_plane_plan/parallel-training-20260925-r2.json)
records two English variants sharing the pinned restart12 base. Every job has
three training sentences and the same three validation sentences, so this is
**in-sample**, not a held-out or multilingual canary. Each serial job uses a
fresh process; the parallel pair uses two fresh processes. OS file-cache warmth
is uncontrolled.

| Fixed workload | Wall time, including worker setup and persistence | Wall time / training span |
|---|---:|---:|
| Two sequential jobs, six total training spans | 30.366 s | 5.061 s |
| Two concurrent jobs, six total training spans | 15.449 s | 2.575 s |

Observed throughput ratio: 1.966. Both modes produced byte-identical candidate
checkpoints, identical before/after numeric evaluation metrics and one accepted
epoch per job. All four runs survived owner reopen; both branch heads retained
their original versions. The original 25,895,338-byte checkpoint still had SHA-256
`1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd`.

The initial bridge-on evaluation inside each job took 10.559–10.821 s, or
3.520–3.607 s per evaluated span. The profiler calls this phase
`before_holdout_evaluation`, but the actual membership here is in-sample.
This is a throughput improvement from concurrency; individual bridge evaluation
latency did not fall by the throughput ratio.

The [earlier observation](evidence/autoencoder_control_plane_plan/parallel-training-20260925.json)
also passed at 30.392 s versus 15.462 s. The final run followed a recovery fix:
the coordinator now resolves a persisted operation receipt after response loss
and retries the exact operation, rather than reporting a committed completion
as failure. It also verifies a six-module source manifest before and after each
job, including the worker itself. Both receipts retain their own source hashes.

Every measurement ran `modal_frame_logic`, `deontic_norms`, `fol_tdfol`,
`cec_dcec`, and `external_prover_router`; provers false, one bridge worker per
training process, disk metric cache 0, initially empty process target cache,
sample memory false, and `python_sparse_batch`. Projection limits were one
epoch, one line-search attempt, one update family and 180 seconds. CUDA was
disabled; BLAS/OpenMP thread limits were one. Targets were 3/3 before and after
each job. The receipt's admission flag is false.

## Reproducing the isolated checks

Run from the `external/ipfs_datasets` source tree in a fresh process. These
scripts pin their own tree, create disposable databases/artifacts and refuse to
overwrite a receipt. Choose a new output path for every invocation.

```bash
python3 scripts/ops/legal_ir/probe_autoencoder_storage.py --native --output /tmp/storage-probe-new.json
python3 scripts/ops/legal_ir/benchmark_autoencoder_control.py --output /tmp/training-control-new.json
```

For embedding the APIs, create the dedicated owner with
`AutoencoderRegistry(database_path, artifact_root)`, register a variant and
verified base artifact, stage a `TrainingJobSpec` JSON artifact, then create its
run with `job_spec_sha256` and `job_spec_artifact` references. Invoke
`run_training_jobs(owner, specs, max_workers=2)` from a spawn-safe entry point.
The four variant fields are `source_language`, `target_formal_language`,
`jurisdiction`, and `model_variant`. The current worker supports only the
existing `en` / `typed_deontic_ir` / `us` frontend; storing another language
variant in the registry does not qualify a parser for it.

Supply `expected_source_sha256` for compiler, decompiler, parser, autoencoder,
samples and worker to bind the qualified module files. A resident worker refuses
to continue after those files change. The job's `code_identity`,
`dataset_snapshot_id` and `split_snapshot_id` remain caller labels unless an
external manifest authority qualifies them; receipts say so. The entire actual
sample/configuration payload is independently bound by the staged job digest.

The coordinator uses local typed owner calls. Native Quack command transport
is tested separately and requires `enable_prototype=True`; no daemon silently
switches its database or backend. Gateway credentials belong only to the
assigned worker and are not model provenance.

## Offline Hugging Face release preparation

`build_private_resume_release(version_record, artifact_path, destination,
repo_id=..., variant_manifest=...)` prepares a new local package using the
existing model-repository publication profile and publisher contracts. It
returns a `PrivateResumeRelease` with the actual `PublicationPlan`, package
manifest digest and paths. `verify_release_package` verifies exact local
closure. The [release tests](evidence/autoencoder_control_plane_plan/private-release-tests-20260925.json)
passed ten cases covering determinism, unchanged source bytes/inodes, malformed
evidence, path safety, language declarations and absence of network/approval
actions. Together with the combined selection above, 142 focused tests passed.

The supported profile is currently `exact_resume_private`. It preserves all
original checkpoint bytes, including source-like feature keys and sample
memory. Public and inference exports fail until separately qualified. The
package includes config, provenance, frozen supplied evaluation receipts,
manifests and a model card. Missing evaluation or licensing evidence remains
explicitly missing; packaging does not establish model quality or a license.

No Hub repository was contacted, no credentials were read, and no pinned
checkpoint was packaged during these synthetic packaging tests. The caller
must supply the intended repository and new destination. Live private-repository
verification, remote parent/inventory checks and the existing publisher's
exact-plan approval are still prerequisites for an actual upload. Profile
metadata alone does not enforce remote privacy in the generic publisher.
The local root README is a proposal; the immutable plan contains its release
copy. Publishing a Hub-root model card still needs a separately implemented,
reviewed bootstrap/CAS operation; this packager preserves the release-prefix
restriction.

## Remaining implementation work

This slice retains full private JSON candidate checkpoints. It does **not**
claim changed-row I/O or Arrow zero-copy weights. The next performance work is
shared bridge targets, a qualified sparse row-patch codec, and batched DuckLake
outbox materialization. Existing component-level deltas still cannot be called
row-level persistence. Arrow weight migration remains gated by restart12's
source-like feature-key failure; no validator or model key was changed.

Resource limits are also incomplete: `max_seconds` is the existing cooperative
training budget, not a hard process-kill deadline. A hung native dependency
needs later supervisor integration. Artifact copy/fsync currently shares the
owner's scheduling thread, so short leases can expire during staging and
quarantine useful work. The measured jobs use 300-second leases with a
180-second training budget; large states/short leases need separate staging and
heartbeat qualification. End-to-end disk quotas, retention/compaction,
production recovery drills and daemon routing remain future work.

There is no new held-out claim, multilingual frontend qualification, Constitution
formalization or Lean admit. Lake (`lake build <Lib>`) remains the only Lean
admission path.
