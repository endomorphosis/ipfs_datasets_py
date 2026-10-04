# Residual projection freeze: controlled 384D development comparison

The additive v4 trainer tests whether a decoder can learn source values while
the inherited residual projection remains unchanged. It keeps every existing
selection and qualification gate. It does not change the historical 8D lineage,
the v1/v2/v3 checkpoint readers, or published inference defaults.

The preceding [source-conditioning experiment](source_conditioned_decoder_v3.md)
found that persistent conditioning did not consistently improve saved model
fidelity. Across its 808 generated evaluations, 736 violated the initial
embedding reconstruction bound and 419 regressed a protected output field;
383 violated both. Some later candidates generated more exact outputs but
correctly failed selection. This motivates a controlled intervention, not a
weaker acceptance criterion or a claim that freezing will work.

## Runtime API and unchanged semantics

[`domain_384_autoencoder_v4.py`](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/domain_384_autoencoder_v4.py)
adds the required `projection_update_policy` setting:

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_384_autoencoder_v4 as trainer

fit = trainer.train(
    "intent_ir", training_rows, tuning_rows,
    parent_projection={"path": parent_path, "sha256": parent_sha256},
    config={
        "decoder_conditioning": "every_step",
        "projection_update_policy": "frozen_parent_residual",
        "epochs": 1000, "max_seconds": 30, "batch_size": 16,
        "learning_rate": 0.003, "reconstruction_weight": 0.1,
        "scalar_value_weight": 8.0, "source_conditioning": "none",
        "max_target_tokens": 64, "eval_interval": 10, "patience": 120,
        "plateau_patience": 3, "plateau_factor": 0.5,
        "min_learning_rate_ratio": 0.05, "embedding_nonregression": True,
        "seed": 3517,
    },
)
runtime = trainer.Runtime(fit["checkpoint"])
# Inference receives original source provenance and its embedding, not targets.
prediction = runtime.infer(inference_rows)
```

`joint` updates all existing model parameters. `frozen_parent_residual` freezes
exactly `projection_down.weight`, `projection_down.bias`,
`projection_up.weight`, and `projection_up.bias`. The conditioning layer, GRU,
token embeddings, and output head remain trainable. No architecture dimensions
change. The inherited projection width of eight is a residual branch inside
the 384D model; this is not the separate historical 8D autoencoder.

The projection remains
`x + projection_up(tanh(projection_down(x)))`. Its complete 384D input survives
the residual addition. Freezing the four tensors should preserve its initial
embedding reconstruction for identical inputs; the normal embedding gate still
runs. A byte-level reference checks the frozen tensors after every optimizer
step. Checkpoints record the policy, trainable and frozen tensor names, and
initial/selected projection digests. The benchmark independently binds both
digests to the actual pinned parent's transferred float32 tensors, including
signed zero, and checks exact serialized tensor preservation.

Source conditioning has the existing two controls: `initial_only` supplies the
initial recurrent state; `every_step` also supplies the same condition at each
token step. Its additional GRU input columns start at zero, preserving the
control's initial behavior. All common parameters are inherited from the same
immutable parent. Seeds vary minibatch order, not independently randomized
initial model weights.

Generated exactness, every scalar path, native candidate validity, and embedding
nonregression still govern checkpoint selection. Training retains positive
loss on every scalar value, key/syntax losses, ordinary and weighted token
cross-entropy reporting, and reconstruction loss. Learning-rate plateau handling
uses continuous candidate progress; rejection alone is not treated as a
plateau. Target truncation, target-assisted inference, and source prediction
repair remain prohibited. Temperature stays zero and the target ceiling stays
64 tokens.

The v4 checkpoint is a separate lineage artifact. This API forks a parent for
a new bounded fit; it does not promise optimizer resume, automatic promotion,
database weight synchronization, or Hub publication. Optimizer state is not
serialized for training resume.

## Registered 16-fit benchmark

[`benchmark_projection_freeze_development.py`](../../scripts/ops/autoencoder/benchmark_projection_freeze_development.py)
runs the full factorial comparison:

| Dimension | Fixed values |
| --- | --- |
| Domain | `intent_ir`, `ui_ux_ir` |
| Minibatch-order seed | 3517, 3518 |
| Conditioning | `initial_only`, `every_step` |
| Projection updates | `joint`, `frozen_parent_residual` |
| Per-domain input | Existing 96 training / 24 tuning rows |
| Fit budget | 1,000 epochs maximum / 30 numerical seconds |
| Execution | One CPU training worker; one Torch thread |

The four arms run in reversed order for seed 3518 within each domain. The full
recipe, input pins, ordering, native indices, family list, and implementation
identity are written before fitting. All 16 checkpoints must be sealed before
post-fit ablations and native checks. Pair checks require identical complete
initial states across projection policies for the same conditioning mode,
identical common inherited parameters across conditioning modes, and identical
initial measured validation behavior. Vocabulary, parent, and all other
numerical settings must match within each comparison.

The inputs are the already exposed authored Intent statements and four-field UI
components from `intent-ui-coverage-20261002/comparison-r1`. The published
archive manifest binds all training/tuning files and embedding receipts. The
runner verifies complete row joins and every local GTE asset; it downloads
nothing and never opens a test split. These fixed-grammar tuning groups overlap
training. This is development evidence, not a fresh holdout or general corpus
qualification. Preparation uses the existing encoder ceiling without raising
its context window.

The parent checkpoint is
`workspace/test-logs/holdout-throughput-release-20261001/current-holdout-r1/1729-original32-head.json`,
SHA-256 `969461ab82a2806e54ad33ba242a1eb62d032fa1b3cfc808b77c66dcc965aa62`.
The encoder is the existing local `thenlper/gte-small` snapshot
`17e1f347d17fe144873b1201da91788898c639cd`. The neural trainer consumes its verified
384D stored vectors; the encoder itself is not trained by this experiment.

Run from the reviewed frozen source tree, through the existing storage and
process reservation guardian. The benchmark CLI is:

```bash
python3 scripts/ops/autoencoder/benchmark_projection_freeze_development.py \
  --development-data /home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/intent-ui-coverage-20261002/comparison-r1 \
  --parent /home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/holdout-throughput-release-20261001/current-holdout-r1/1729-original32-head.json \
  --output /absolute/path/to/new-reserved-results
```

The output path must be new. Existing outputs, weights, source snapshots, and
retained storage claims are preserved. CPU/RAM leases and the existing ledger
remain authoritative; a larger storage cap does not remove physical-space or
process checks. The numerical deadline includes generated checkpoint selection
and state copying, while whole-call preparation and serialization costs are
reported separately. A scheduler lane called `hammer_lean` is resource
accounting, not Lean evidence.

## Evidence and qualification boundaries

Each fit saves its checkpoint, full training history, raw generated training and
tuning outputs, and exact replay of the saved checkpoint's selected metrics.
After all fits are sealed, three tuning ablations run: zero source condition,
zero decoder, and shuffled embeddings. They test path dependence; they do not
establish independent source fidelity.

The first three tuning indices, fixed before fitting, are the native sample for
every fit: 48 attempts in total. The independent source audit may reject an
output but cannot replace it with an expected answer. Only eligible unchanged
candidates proceed to family preparation, with the same complete 40-family
request. Missing or unsupported families remain explicit. Native v7 validation
uses the resumable wrapper and actual pinned Lake 4.30.0, with bounded native
worker admission and retries. Compiler, schema, or family success alone is not
a Lake admit, and these fragments cannot satisfy whole-modality qualification.
If every fixed candidate fails source agreement, the result is zero native jobs
and zero Lake evidence, not a passing native result.

Report both optimizer example presentations per second and whole-fit seconds
per unique training span. Repeating 96 spans for 1,000 epochs represents 96,000
training presentations, not 96,000 new corpus spans. Warm loaded inference uses
one warmup and three timed runs over all 24 tuning inputs. That public API timing
includes native candidate validation but excludes embeddings, source audit,
Lake, and bridge-on evaluation. These small timing samples are descriptive.
Maximum parent RSS excludes native child RSS.

## Results

The completed [comparison evidence](../implementation/reports/evidence/projection-freeze-development-20261002/results.json)
supports freezing the residual projection for this exposed development panel.
It does not establish performance on fresh legal text, UI documents, or unseen
groups. All 16 fits completed 1,000 epochs and 6,000 optimizer steps; none
stopped at a deadline. Every frozen projection matched the actual pinned
parent's float32 tensor bytes, including signed zero. An independent
standard-library analysis replayed the parent and all sealed checkpoint
digests, selected metrics, and gate decisions.

The following table reports exact reconstruction out of 24 tuning rows and
correct critical scalar values out of 96. The critical values are
actor/action/modality/object for Intent and component/role/privacy/presentation
for UI. Constant schema tags remain checked separately and are never dropped
from validation.

| Domain / seed | Conditioning | Exact: joint → frozen | Critical values: joint → frozen |
| --- | --- | ---: | ---: |
| Intent / 3517 | Initial only | 1 → 24 | 29 → 96 |
| Intent / 3517 | Every step | 1 → 24 | 42 → 96 |
| Intent / 3518 | Initial only | 3 → 21 | 60 → 93 |
| Intent / 3518 | Every step | 1 → 24 | 44 → 96 |
| UI / 3517 | Initial only | 2 → 15 | 61 → 83 |
| UI / 3517 | Every step | 1 → 24 | 57 → 96 |
| UI / 3518 | Initial only | 1 → 16 | 47 → 84 |
| UI / 3518 | Every step | 1 → 24 | 49 → 96 |

Every frozen-versus-joint pair improved exact reconstruction without reducing
any scalar path's correct count. Frozen projection plus persistent conditioning
reached 24/24 exact in all four domain/seed fits. The corresponding source
audits also found agreement on every row. These are repeated evaluations of
the same 24 tuning sources per domain, not additional independent spans.

The first selected 24/24 observation occurred at epochs 210 and 180 for Intent
with persistent conditioning, and 390 and 370 for UI. Initial-only conditioning
reached 24/24 for Intent seed 3517 at epoch 370; its other three fits remained
below full exactness. The receipts do not measure wall time to those individual
epochs, so these epoch counts must not be converted into measured
time-to-target claims.

The mechanism is visible in the gate replay. Joint training had 736 embedding
failures and 419 field failures across 808 generated evaluations; 383 failed
both gates, and only 35 evaluations selected a checkpoint. Frozen training had
zero embedding failures, 358 field failures, and 447 selected evaluations
across its 808 evaluations. Gate ordering otherwise masks some embedding
failures behind the first reported field rejection. Per-field rejection remains
useful: freezing alone did not eliminate all semantic errors in the initial-only
models.

Freezing preserves the initialization's embedding MSE, approximately 0.004376
for Intent and 0.005257 for UI. Several joint-selected checkpoints have lower
embedding MSE. The improvement shown here is source reconstruction while
retaining the unchanged initial embedding bound; it is not an improvement in
every objective or proof of a global minimum. Zero-condition and zero-decoder
ablations produced zero exact outputs for all frozen models. Shuffling
embeddings reduced all four perfect persistent-conditioning models to 0/24
exact, supporting source-path dependence within this fixed panel.

Training cost did not improve uniformly. This table sums the two seed fits for
each domain and conditioning mode; each fit ran the same 1,000-epoch budget.

| Domain / conditioning | Whole training-call seconds: joint → frozen |
| --- | ---: |
| Intent / initial only | 49.79 → 47.50 |
| Intent / every step | 46.31 → 46.58 |
| UI / initial only | 44.79 → 39.10 |
| UI / every step | 46.15 → 46.71 |

Across all eight arms per policy, whole training calls totaled 187.04 seconds
for joint training and 179.89 seconds for frozen training. The per-fit ranges
were 0.211–0.290 versus 0.202–0.271 seconds per unique training span. Optimizer
rates were 3,897–5,292 versus 4,018–5,555 repeated example presentations per
second. The mixed per-seed timing changes and small timing sample do not support
a general speedup claim.

Warm public inference took 0.508–0.560 ms/span for joint Intent models versus
0.470–0.534 for frozen Intent models; UI took 0.598–0.607 versus 0.599–0.645.
These timings have the public-API scope described above, including native
candidate validation and excluding source audits, embeddings, bridges and Lake.
The complete experiment took 541.48 seconds and reached 1,005,888 KiB maximum
Python-parent RSS; that RSS excludes native child processes.

The 48 predeclared native attempts produced 29 source-disagreement blocks and
19 eligible unchanged candidates. Actual pinned-tool commands
`lake build IntentIR` passed for 11 candidates and `lake build UIUXIR` passed for
eight. Every receipt remained partial. Intent checked 16 emitted projections
covering 10 requested families (`datalog`, `dcec`, `deontic`, `frame_logic`,
`higher_order`, `horn_chc`, `program`, `tdfol`, `temporal`, `transition_system`),
with 30 families missing. UI checked its two projections (`first_order`,
`frame_logic`), with 38 families missing. All emitted projections in those
builds passed their parser and Lake checks. This checks the supplied native
typed/operator interpretation contracts, not arbitrary source truth or missing
behavioral semantics. All 19 strict whole-modality training gates remained
false. No checkpoint was promoted or uploaded by this comparison.

The evidence archive includes `analyze_results.py` and
`diagnostic-analysis.json`. The analysis pins summary SHA-256
`a4d5dbfb7e18d4b3e0414b24e1d837ab7711fb6b96212ecb6acd0f6f5d63bd87`
and can be rerun against the saved receipts and locally retained parent and
checkpoint JSON files without loading neural models or reading split inputs.
Those weight files are identified by path and hash; they are not included in
the evidence archive or uploaded by this run. The run also retains 316 passing regression tests and
four guardian-cleanup controls. The next fresh grouped evaluation must be
specified and frozen independently; no result here may be relabeled as a new
holdout or whole-modality qualification.
