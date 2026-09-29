# Train legal autoencoder features

Use the existing legal runner for U.S. Code samples with verified local semantic embeddings. It supports resumable local parallel training and a separate distributed owner/worker runner. UI/UX, security and intent structural features use the [native feature quickstart](native_feature_quickstart.md); their checkpoint and target formats are different.

This guide describes the published APIs at dataset commit `3666ebad19422b8345ebe5432a1c02f26d2eba4c`. Commands below are bounded templates; they were not used to start a campaign while writing this documentation.

## Choose the training purpose

| Purpose | What selects a candidate | What it does not establish |
| --- | --- | --- |
| `feature_pretraining` | Raw decoder reconstruction, complete shared bridge targets, guarded objective improvement and exact sparse replay | Source semantic qualification, family syntax qualification, Lake admission, inference promotion |
| `formalization` | Existing optimizer plus separate candidate qualification on source and disjoint tuning rows | Admission of an entire law, an independently held-out canary, or proof that model embeddings decode into formulas |

`formalization` is the CLI default. Specify `--training-purpose feature_pretraining` explicitly when compiler repairs are deferred. Feature mode does not lower the formalization gates; it produces separately identified unqualified candidates. See [inference and qualification](inference_and_qualification.md) for the gates and their limits.

## Pin the process before importing

Run in a fresh process. Changing `PYTHONPATH` after importing another copy of `ipfs_datasets_py` cannot repair that process.

```bash
cd /home/barberb/lift_coding/external/ipfs_datasets
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONDONTWRITEBYTECODE=1
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE=0
export IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI=0
export CUDA_VISIBLE_DEVICES=''
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1

python3 -B - <<'PY'
from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
require_workspace_logic_tree()
PY
```

The compiler, decompiler and parser must resolve inside this workspace's `external/ipfs_datasets` tree. A bare import otherwise may resolve to the editable HACC checkout. Do not synchronize HACC or `hallucinate_app` to bypass the pin. The [setup guide](README.md) covers dependencies; these commands do not install or download weights.

## Gather the input artifacts

Choose an existing local checkpoint compatible with the embedding model and dimension. A fresh 384-dimensional model is a different experiment from continuing the archived restart12 model. Never overwrite the archived checkpoint.

Set these paths to real existing artifacts; `/absolute/path/...` entries are placeholders:

```bash
export AE_CHECKPOINT='/absolute/path/compatible-full.state.json'
export AE_TRAIN_JSONL='/absolute/path/verified-training.jsonl'
export AE_TUNE_JSONL='/absolute/path/verified-tuning.jsonl'
export AE_FEATURE_MANIFEST='/absolute/path/feature-inputs.json'
export AE_RUN_ROOT="$PWD/workspace/test-logs/federal-corpus-audits/my-legal-feature-run"
export AE_TARGETS_DIR="$AE_RUN_ROOT/targets"
export AE_STATE_DIR="$AE_RUN_ROOT/training"
```

Each JSONL line is a `SampleRecord`, with `title`, `section`, `text`, optional `citation`, `embedding_model`, and supplied `embedding_vector`. These are sample objects, not census envelopes with a nested `sample` field. Feature mode requires non-mock embeddings with matching production evidence; changing `embedding_model` on arbitrary vectors does not create that evidence.

The accepted feature manifest schema is `autoencoder-feature-inputs/v1`. It contains:

- `model`, matching the local embedding production receipt;
- `embedding_production_receipt`, an absolute `{path, sha256, bytes}` reference;
- `source_artifacts`, exact local source references;
- `artifacts.training` and `artifacts.validation`, each with a `rows` reference, `count`, and ordered `input_ids` from the production receipt.

The verifier also supports the historical `parallel-training-verified-embedding-split/v1` diagnostic manifest. That compatibility does not make its split globally eligible or turn the repeated tuning panel into a held-out canary. The current runner allows **1–32 tuning rows**. Both selections must be nonempty and disjoint; verified vectors must retain their exact finite float32 values. Do not expand context, truncate text, synthesize vectors or download a replacement model to satisfy this check. See [artifacts and inputs](artifacts_and_inputs.md) for manifest construction and embedding production.

Verify only the local evidence, without training or compiling:

```bash
python3 -B - <<'PY'
import json
import os
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_feature_inputs import verify_feature_training_inputs

checked = verify_feature_training_inputs(
    os.environ['AE_FEATURE_MANIFEST'],
    os.environ['AE_TRAIN_JSONL'],
    os.environ['AE_TUNE_JSONL'],
)
print(json.dumps({
    'model': checked['model'],
    'training_count': checked['training']['count'],
    'tuning_count': checked['validation']['count'],
}, indent=2))
PY
```

## Prepare shared targets once

Preparation and optimization have separate deadlines. Every sweep candidate over the same selection should consume the same sealed bundle instead of recompiling the targets.

First inspect a plan. `--plan` reads and validates inputs but does not build targets or reserve resources. The output directory must not already exist, including for this planning command.

```bash
python3 -B scripts/ops/legal_ir/prepare_shared_autoencoder_targets.py \
  --input-jsonl "$AE_TRAIN_JSONL" \
  --validation-jsonl "$AE_TUNE_JSONL" \
  --output-directory "$AE_TARGETS_DIR" \
  --target-timeout-seconds 60 \
  --require-complete-targets \
  --max-input-rows 256 \
  --max-output-bytes 268435456 \
  --target-shard-max-bytes 268435456 \
  --storage-bytes 750000000 \
  --memory-mb 8192 \
  --timeout-seconds 600 \
  --plan
```

To perform preparation, run the same command **without `--plan`**, after checking the existing resource ledger can admit it. Do not create a fresh ledger to evade a campaign cap. The shipped default ledger is `workspace/test-logs/federal-corpus-audits/owned-daemon-resource-control/disk-reservations.json`; custom approved roots/ledgers use `--resource-root` and `--resource-ledger`.

This preparation command fixes the five bridge names, in this order:

```text
modal_frame_logic,deontic_norms,fol_tdfol,cec_dcec,external_prover_router
```

It fixes provers off, metric disk cache off, and one bridge worker. `--require-complete-targets` refuses a successful handoff when a target timed out or requested bridge evidence is missing, partial or rejected. A `ready` target alone is not semantic qualification.

On success, retain `receipt.json`, `producer.json`, `targets.bundle`, and `resources.json`. The receipt supplies `runner_arguments`, `runner_environment`, `target_snapshot_id`, `target_completeness`, and preparation timing. Apply its timeout environment on every consumer:

```bash
export AE_TARGET_ID="$(python3 -B -c 'import json,os; print(json.load(open(os.environ["AE_TARGETS_DIR"]+"/receipt.json"))["target_snapshot_id"])')"
export IPFS_DATASETS_LEGAL_IR_TARGET_TIMEOUT_SECONDS=60.0
```

The `60.0` matches this template's preparation argument. When using another receipt, use its exact `runner_environment` value instead. Preserve the receipt's shard bound too. Target bytes, sample content, producer package source, runtime and bridge settings are checked on reuse. A source edit can require a new bundle; copying the old snapshot ID does not make it compatible.

## Run one bounded feature-training cycle

This command executes training; it is not a dry run. Use a new state directory and the prepared artifacts above. It allows up to two concurrent passes, with three epochs per job and a 90-second optimizer budget. Actual admitted parallelism may be smaller.

```bash
python3 -B scripts/ops/legal_ir/run_incremental_autoencoders.py \
  --state-directory "$AE_STATE_DIR" \
  --execution-mode training \
  --training-purpose feature_pretraining \
  --checkpoint "$AE_CHECKPOINT" \
  --input-jsonl "$AE_TRAIN_JSONL" \
  --validation-jsonl "$AE_TUNE_JSONL" \
  --feature-input-manifest "$AE_FEATURE_MANIFEST" \
  --shared-targets "$AE_TARGETS_DIR/targets.bundle" \
  --target-snapshot-id "$AE_TARGET_ID" \
  --target-shard-max-bytes 268435456 \
  --workers 2 \
  --parallel-workers 2 \
  --max-batches 2 \
  --epochs 3 \
  --learning-rate 0.35 \
  --line-search-attempts 2 \
  --projection-optimizer-mode productive_adaptive \
  --projection-momentum 0.25 \
  --projection-candidate-update-order decoded_embedding_structural \
  --max-seconds 90 \
  --cycle-timeout 900 \
  --memory-mb 8192 \
  --storage-bytes 1000000000 \
  --polls 1
```

The implementation remains `python_sparse_batch`, with external provers and sample memory off. The runner records temperature 0 and preserves the existing context limits. The feature runner chooses `raw_decoder` reconstruction; it does not silently substitute safety-projected metrics. `decoded_embedding_structural` is one explicit update-family choice, not coverage of every possible learned head. No optimizer can guarantee a global minimum for this objective.

The local feature command neither uploads candidates nor polls unverified census rows. `--publish-repository` and `--repository-id` are not feature-mode shortcuts. For feature publication and multiple machines, use the dedicated owner/worker recipe in [control plane and synchronization](control_plane_and_sync.md).

## Resume, change capacity, or start a sweep

Re-run the same command against the same state to reconcile completed batches and continue pending work. Keep the checkpoint/input binding, target snapshot, purpose, source version, tuning selection and optimizer policy unchanged. Resume is at **completed-batch granularity**, not arbitrary mid-epoch optimizer continuation. Adaptive rate/history and momentum are job-local in this legacy projection optimizer.

`--workers` sets the stable lane count. Keep it fixed when resuming. `--parallel-workers` limits the currently admitted concurrent passes without changing lane identity; `0` follows hardware admission. Capacity depends on the existing CPU, memory, child-process and storage reservation, not simply on core count. A zero-worker capacity report is deferred work, not successful training.

For a hyperparameter sweep, use a separate fresh state directory per configuration and the same immutable targets and tuning set. Compare equal sample counts and equal bridge settings. Do not reuse a partially completed stream with edited optimizer arguments and call it a continuation.

Useful bounded settings from the current CLI:

| Option | Meaning and limits |
| --- | --- |
| `--epochs` | 1–32 per job |
| `--line-search-attempts` | 1–10; explicitly bounds proposals |
| `--projection-optimizer-mode` | `fixed`, `guarded_adaptive`, or `productive_adaptive`; adaptive modes require disjoint tuning |
| `--projection-momentum` | 0–0.9; nonzero requires adaptive mode and at least two attempts |
| `--learning-rate` | Finite initial rate in `(0, 1]` |
| `--max-seconds` | Positive optimizer budget, at most 300 seconds; excludes separate target preparation |
| `--cycle-timeout` | Supervisor process deadline, including work outside the optimizer |
| `--max-batches` | 1–128 optimizer attempts per cycle |
| `--polls`, `--sync-interval` | Bounded cycles and delay; `--polls 0` is unbounded until interrupted |
| `--fresh-training-workers` | Default; new native processes each wave |
| `--reuse-training-workers` | Explicit bounded reuse, still subject to provenance checks |
| `--arrow-feature-weights` | Optional verified Arrow IPC baseline bound to the checkpoint; not a DuckDB file or a complete alternate checkpoint |

## Read the result before scaling up

The final printed record points to the durable cycle receipt. Inspect `training.completed`, the worker receipt artifacts, and resource finalization. Relevant fields include:

- `optimizer_accepted_epochs` and `feature_status` (`updated` or `consumed_without_update`);
- `raw_tuning_metrics.before/after`, covering cosine, reconstruction and target count;
- worker `training_report.before/after`, including cross-entropy and nonempty `legal_ir_losses`;
- `epoch_reports[*].committed_objective_delta`, `pareto_regressions`, rejection reasons, and `stopped_reason`;
- `projection_profile`, `elapsed_seconds`, target preparation/hydration costs, pending counts and capacity reports;
- `semantic_qualification_status`, which is `deferred_not_evaluated` in feature mode, and the false qualification/admission/promotion flags.

An accepted feature epoch must improve its raw weighted objective and pass the existing regression guards. A completed batch can contain **zero accepted epochs**. Inspect the reason instead of counting completed rows as progress. Repeated tuning is not an independent canary.

For speed reports include wall time per prepared span and per bridge-on evaluate, sample count, all bridge names, prover flag, cache flag, worker count, and whether targets were newly prepared or reused. `legal_ir_target_count == 0` is not a faster legal-IR evaluation. Resource claims must finalize cleanly; a receipt written before a worker exits is not sufficient end-to-end evidence.

## Source entry points

- [Incremental CLI](../../scripts/ops/legal_ir/run_incremental_autoencoders.py): argument parsing, execution-purpose gates, supervision and cycle receipts.
- [Shared target preparation CLI](../../scripts/ops/legal_ir/prepare_shared_autoencoder_targets.py): plan, build, completeness and reusable handoff.
- [Feature input verifier](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_feature_inputs.py): source/embedding/split evidence.
- [Feature training](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_feature_training.py): raw objective guards, local parallel dispatch and batch resume.
- [Training worker](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_training_worker.py): immutable job schema and numerical limits.
- [Distributed feature verifier](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_distributed_features.py): independent owner reevaluation and generation selection.

For source edits, failed reservations and deadline failures, use [operations and troubleshooting](operations_and_troubleshooting.md). For the separate structural IR backend, use [modalities](modalities.md).
