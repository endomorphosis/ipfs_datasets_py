# Inference and qualification are separate operations

An autoencoder inference call returns learned representations or reconstruction metrics. It does not establish that a legal sentence compiled correctly, that a modality's projections preserve meaning, or that a theorem was admitted. Use the operation below that matches the evidence you need.

| Operation | Public entry point | Executes training? | Executes Lake? |
| --- | --- | --- | --- |
| Legal model metrics | `autoencoder_paths.run_inference` | No | No |
| Legal feature metrics with raw decoder | `autoencoder_paths.gated_evaluate(..., reconstruction_objective="raw_decoder")` | No | No |
| Legal source/model qualification | `run_incremental_autoencoders.py --execution-mode inference` | No | When the source is eligible and renderable |
| UI/UX, security or intent feature inference | `autoencoder_projection_features.infer_projection_features` | No | No |

The structural modality API needs its own contract, feature space and numerical state. It does not accept legal modal checkpoints, Arrow weight overlays or a legal shared-target bundle. See the [native feature quickstart](native_feature_quickstart.md) for its complete training/inference example.

## Reuse the optimized Legal runtime

The published Legal 384D loaders enable inference optimizations by default:

```python
from ipfs_datasets_py.logic.legal_ir import open_autoencoder

runtime = open_autoencoder(local_files_only=True)
result = runtime.infer_texts(["The agency shall retain records."])
# Reuse runtime for subsequent calls; the private decoder and encoder are cached.
original = open_autoencoder(local_files_only=True, optimized=False)
```

Both `checkpoint_hub.open_autoencoder("legal_ir", ...)` and
`checkpoint_hub.open_local_autoencoder("legal_ir", ...)` accept the same
`optimized=False` opt-out. The versioned `autoencoder_runtime_registry.open_runtime`
also defaults to optimized learned-formula inference for `legacy_v1`,
`legacy_v1_optimized` (8D), and `current_v2` (384D), when a formula head is attached.
Pass `optimized=False` when opening that runtime to retain the original decoder.
Metrics and compiler modes keep their existing evaluation behavior.

Checkpoint bytes, source bindings, full core checks, and decoder tensor checks
remain verified. Optimized results identify their inference implementation;
batched float32 calculations can differ slightly in confidence margins. GTE-small
uses CUDA when available and CPU otherwise. Timings with supplied embeddings
exclude the cost of this encoder.

## A runnable, offline legal inference example

This example uses a fresh small model and the deterministic **test** embedding supplied by `build_us_code_sample`. It demonstrates the inference gate without downloading a model, loading an archived checkpoint, generating bridge targets or running a prover. Its metrics are not semantic-embedding quality measurements and are not production training inputs.

```bash
cd /home/barberb/lift_coding/external/ipfs_datasets
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONDONTWRITEBYTECODE=1
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE=0
export IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI=0
export CUDA_VISIBLE_DEVICES=''

python3 -B - <<'PY'
import json
from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
require_workspace_logic_tree()

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import AdaptiveModalAutoencoder
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_paths import run_inference

sample = build_us_code_sample(
    title='fixture',
    section='1',
    text='The agency shall not disclose records.',
)
model = AdaptiveModalAutoencoder(compute_device='python')
report = run_inference(model, [sample], legal_ir_bridge_names=())
print(json.dumps({key: report[key] for key in (
    'execution_path', 'training_executed', 'state_changed', 'sample_count',
    'legal_ir_target_count', 'cosine_similarity', 'reconstruction_loss',
    'qualified', 'admitted',
)}, indent=2))
assert report['training_executed'] is False
assert report['state_changed'] is False
assert report['legal_ir_target_count'] == 0
assert report['qualified'] is False and report['admitted'] is False
PY
```

`run_inference` uses `gated_evaluate`, checks the model's state revision and identity before/after evaluation, disables sample memory and external provers, and returns the native metrics. Its default reconstruction objective is `safety_projected`. The result deliberately records zero legal-IR targets because the bridge list is empty. That is not a bridge-on speed measurement.

For raw decoder metrics on the same model, replace the call with:

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_paths import gated_evaluate

evaluation = gated_evaluate(
    model, [sample], execution_mode='inference',
    legal_ir_bridge_names=(),
    reconstruction_objective='raw_decoder',
)
metrics = evaluation.to_dict()
```

Raw decoder evaluation measures learned residual features relative to the supplied embedding. It is not an independent text decoder. Do not compare it to safety-projected metrics as if they were the same objective.

## Evaluate an existing local legal checkpoint

Replace the fresh model construction with the following after independently verifying the checkpoint's artifact hash and selecting its matching embedding representation:

```python
from pathlib import Path
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    AdaptiveModalAutoencoder,
    ModalAutoencoderTrainingState,
)

checkpoint = Path('/absolute/path/verified-complete.state.json')  # Replace this path.
state = ModalAutoencoderTrainingState.load_json(checkpoint)
model = AdaptiveModalAutoencoder(state=state, compute_device='python')
```

This snippet expects a **complete legal modal state**, not a sparse update manifest, DuckDB database, Arrow IPC overlay, tensor checkpoint or structural modality state. Resolve a sparse chain through its existing owner-verified materialization path first; see [artifacts and inputs](artifacts_and_inputs.md). Supply `build_us_code_sample` with the checkpoint-compatible `embedding_model` and `embedding_vector` from verified local input evidence. The test vectors above cannot validate a semantic checkpoint.

The model's `encode`/`decode` methods reconstruct embedding vectors. They do not return verified legal text or a theorem. Candidate qualification independently runs the deterministic compiler/decompiler on the original source.

For bridge-on evaluation, pass the full requested list explicitly:

```python
BRIDGES = (
    'modal_frame_logic', 'deontic_norms', 'fol_tdfol',
    'cec_dcec', 'external_prover_router',
)
report = run_inference(model, samples, legal_ir_bridge_names=BRIDGES)
```

Here `samples` must be your already constructed legal samples. This call performs potentially expensive bridge work; it is not part of the minimal smoke above. Record `seconds`, `sample_count`, `legal_ir_target_count`, `legal_ir_losses`, bridge names, worker count and cache/prover settings. Positive target count is necessary to call this a legal-IR measurement. Reuse a verified target mapping only after the shared-target loader has checked source, sample and configuration identities; do not pass arbitrary cached dictionaries as evidence.

## Run the full legal qualification path without training

The incremental CLI's inference mode runs separate qualification passes against an immutable local checkpoint. It writes receipts and may execute source-locked Lake builds, but opens no training registry, creates no optimizer candidates, and publishes no weights.

The following is an execution template, not a dry run. Fill the placeholders with an existing compatible **complete checkpoint**, local input JSONL and **1–32 disjoint tuning rows**. Use a new state directory, separate from every training state directory.

```bash
python3 -B scripts/ops/legal_ir/run_incremental_autoencoders.py \
  --execution-mode inference \
  --state-directory /absolute/path/new-qualification-state \
  --checkpoint /absolute/path/verified-complete.state.json \
  --input-jsonl /absolute/path/input.jsonl \
  --validation-jsonl /absolute/path/disjoint-tuning.jsonl \
  --workers 1 \
  --parallel-workers 1 \
  --max-batches 1 \
  --lake-timeout-seconds 120 \
  --cycle-timeout 900 \
  --memory-mb 8192 \
  --storage-bytes 1000000000 \
  --polls 1
```

The state directory must be inside an approved resource-ledger root; use the [operations guide](operations_and_troubleshooting.md) to inspect admission first. The same execution-mode binding is checked on resume. Completed passes have sealed receipts; changing checkpoint, producer sources or validation policy requires a new state. An incomplete retained pass needs explicit recovery rather than overwriting its evidence.

Inference mode rejects optimizer settings, feature-training purpose, shared training targets, Arrow training overlays and network feed/publication arguments. Do not add `--training-purpose feature_pretraining` to this qualification command. The phrase `--execution-mode inference` here means “do not train”; it does not mean “skip source qualification.”

## What the legal qualification receipt checks

The thresholds below come from [candidate qualification](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_candidate_qualification.py). They are existing gates, not suggested tunable success criteria.

| Gate | Requirement | Evidence limit |
| --- | --- | --- |
| `metric_gate` | Per-sample embedding cosine at least **0.72** and reconstruction loss at most **0.20**, finite values, correctly sized decoded vector | Embedding reconstruction, not textual roundtrip equivalence |
| `semantic_gate` | Every source clause completes deterministic compiler/decompiler roundtrip, with complete fields and nonempty decoded text | Source pipeline evidence; no model-generated text claim |
| `family_syntax_gate` | Actual source-bound exports pass each required syntax consumer | Syntax, not entailment, equivalence or proof |
| `lake_gate` | Eligible source semantics, a renderable source-locked numeric pattern, and a successful `lake build Legal` | Only that generated locked numeric theorem |
| `heldout_gate` | Nonempty tuning samples disjoint by identity and normalized text | Repeated selection tuning; receipt still says `heldout_canary: false` |

Required legal syntax exports are `fol`, `deontic_fol`, `temporal_fol`, `deontic_temporal_fol`, `deontic_cognitive_event_calculus`, and `frame_logic`. These are the legal gate's export labels. Other modalities use their own native routes and canonical family/profile/property/view identities; copying this list into a UI or security adapter would be incorrect. See [modalities](modalities.md).

Every qualification row and the aggregate must pass the applicable gates. The qualification code may permit **stricter** cosine/loss thresholds, but cannot weaken the existing floor/ceiling. Feature optimizer loss improvement is a separate observation.

The numeric theorem path uses an already installed `leanprover/lean4:v4.26.0` toolchain and invokes `lake build Legal`; it does not request a toolchain download or import Mathlib. `Legal` is the generated library name, and its capitalization matters. `lean lake legal` is not the command used by the gate.

The renderable temporal subset includes an integer `minimum_duration` threshold. `within_duration` deadlines remain non-renderable, including rules that also contain a minimum duration. A passing syntax parser, bridge report, compile/decompile cycle, NCA output, autoencoder score, or DuckDB row is not a Lean admit. An external prover/router status or an ErgoAI resolution log is not a substitute for the Lake receipt.

The U.S. Constitution is not formalized. Its detected spans return `constitution_not_formalized`; do not relabel them `roundtrip_ok` or bypass the exclusion. Existing qualification receipts retain aggregate `admitted: false` and `formalized: false` even when their scoped Lake subreceipts succeed. A narrowly admitted numeric theorem does not formalize the whole law.

## Read failures without conflating them

- A low `metric_gate` score calls for compatible model/input inspection and possibly training.
- Failed `semantic_gate`, `family_syntax_gate` or `lake_gate` produces source-repair evidence; more feature epochs do not prove the deterministic compiler fixed itself.
- `source_rule_not_renderable` or `within_duration_not_renderable` records an unsupported Lean rendering scope. Do not replace the source with an easier theorem.
- `installed_lake_toolchain_missing` means the required local gate could not run.
- `heldout_samples_missing` or overlap means the selection panel is invalid; in-sample success is recorded separately.
- A producer-source mismatch means the evidence no longer matches the runtime. Preserve it and use a verified source snapshot/new state.

Qualification's model-metric pass intentionally uses an empty bridge list. Its `metric_evaluation.legal_ir_target_count` is zero and is labeled `embedding_metrics_only_not_a_legal_ir_evaluate`. The separate compiler/family/Lake observations do not turn that measurement into a bridge-on evaluation.

## API and implementation links

- [Execution gates and simple inference wrapper](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_paths.py)
- [Resumable qualification-only inference](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_inference.py)
- [Candidate qualification and fixed metric thresholds](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_candidate_qualification.py)
- [Legal family syntax gate](../../ipfs_datasets_py/logic/autoformal/family_qualification.py)
- [Legal sample builder](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_samples.py)
- [Adaptive modal autoencoder](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py)
- [Structural modality feature inference](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_projection_features.py)
- [Training guide](legal_training.md), [API map](api_map.md), and [control plane and synchronization](control_plane_and_sync.md)

Documentation was checked against published dataset commit `3666ebad19422b8345ebe5432a1c02f26d2eba4c`. The minimal offline example was executed on the pinned canonical workspace without training, bridge target generation, Lake execution or downloads. Its shape/assertions were checked; its numerical values are intentionally not a quality baseline.
