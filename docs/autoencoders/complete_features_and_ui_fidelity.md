# Complete structural features and UI decoder fidelity

The complete-vocabulary v6 trainer removes the previous 4,096-atom truncation
from a separate structural-head lineage. The UI changes preserve the complete
native document when decoding its wire representation and add an optional
readout for interface-binding records. These solve different problems: retaining
training targets, preserving supplied schema fields, and interpreting learned
feature scores. None establishes source-language fidelity or a global optimum.

Read [family-aware routing and refinement](family_routing_and_refinement.md)
for the solver capability boundary, existing decoder-block strategy, and the
previous comparison. That comparison's exposed holdouts are development evidence
for this work; they are not a newly sealed test set.

## Entry points and artifact boundaries

| Owner under `ipfs_datasets_py` | Entry point | Purpose |
| --- | --- | --- |
| `optimizers.logic_theorem_optimizer.autoencoder_family_complete_vocab` | `build_complete_space` | Keep every original training atom within explicit capacity limits |
| Same | `estimate_feature_memory`, `guard_inference_memory` | Estimate tensor storage and reject an oversized allocation plan |
| Same | `common_support_metrics` | Compare models against identical complete target support, including unknown atoms |
| `optimizers.logic_theorem_optimizer.autoencoder_family_training_complete_v6` | `train_complete_prepared_projection_corpus` | Train from an issued, replayed live corpus handle |
| Same | `train_complete_family_projection_autoencoder` | Lower-level equivalent accepting live training and tuning observations |
| Same | `infer_complete_family_projection_autoencoder` | Read a v6 checkpoint and score new live-gated observations |
| `logic.ui_ux_ir.decoder` | `decode_ui_ir` | Decode the complete declared UI schema without silently dropping fields |
| `optimizers.logic_theorem_optimizer.ui_feature_training` | `train_ui_feature_batch`, `infer_ui_feature_batch` | Existing registry-backed UI feature route with optional versioned formal readout |
| `optimizers.logic_theorem_optimizer.ui_formal_decoder` | `decode_ui_formal_features`, `evaluate_ui_decoded_fidelity` | Separate score-only decoding from comparison with compiler targets |

V6 artifacts use `validated-complete-native-family-autoencoder/v6`, a fresh
output directory, and their own numerical/native producer pins. They do not
load or migrate an older v5 artifact as a compatible parent. The complete
structural trainer currently trains fresh heads; it does not offer checkpoint
continuation. Its local JSON descriptor is distinct from the UI feature registry
version described below. It does not automatically synchronize DuckDB, Quack,
DuckLake or Hugging Face artifacts.

The historical 8D linguistic autoencoder and the learned 384D source-language
models retain their separate architectures, decoders and checkpoint formats.
A structural head's chosen `latent_width` is not its lineage identity: setting
it to eight does not make it the historical 8D autoencoder.

## Complete means every original training atom

The codec uses the existing original atom definition. It retains object fields,
array positions, string-token positions, concrete values, source hashes and
provenance. It does not pool positions, rename identifiers, select only frequent
atoms, omit difficult projections, or classify unknown fields as disposable
metadata. Training-only vocabulary fitting and original per-projection
log1p/L2 normalization remain explicit.

The old restriction was a feature-vector width, not an LLM context window.
The new default maximum is 65,536 training features, with a 512 MiB estimated
memory budget. Context windows and source-decoder token budgets are unchanged.
The helper additionally bounds serialized atom storage at 64 MiB by default.
The native trainer retains the existing 64 MiB checkpoint artifact bound.

Exceeding a feature or byte budget raises `FeatureCapacityError`, whose
`to_dict()` records the reason, observed amount, maximum, `truncated: false`
and `training_permitted: false`. No partial feature space is returned. Numerical
optimizer preflight can also reject its estimated tensor reservation. Increase
an explicit resource allocation only when the host can accommodate it; a smaller
cap is not permission to drop atoms.

The memory reports estimate dense float64 matrices, parameter copies, gradients,
Adam state, SVD work, minibatches and prediction buffers. Sparse-matrix estimates
identify a possible storage tradeoff; they do not switch this trainer to a sparse
or CUDA backend. These are allocation estimates, not measured RSS or hard
process limits. Python objects, imported libraries, allocators and concurrent
native checkers still need host headroom.

As a development-only inventory of the previous exposed training panel, complete
spaces contained 2,227 Legal, 27,009 Intent, 3,777 Security and 7,337 UI atoms. The
Intent and UI tensor-plus-serialized-vocabulary estimates were approximately
29.7 MB and 8.1 MB respectively for six training rows, two tuning rows and latent
width four. This inventory performed no training, native validation or new
heldout evaluation. It explains why retaining the omitted Intent/UI features is
feasible for that bounded panel; it is not a corpus-scale memory guarantee.

## Train and infer through the existing live gates

Build the corpus through the existing
[`training_readiness` workflow](training_readiness_parallel.md). Each row must
join original typed source inputs to the exact live native observations and
isolated train/tuning identities. A serialized manifest or stored receipt cannot
reopen that gate.

```python
from ipfs_datasets_py.logic.formalization.autoencoder.training_readiness import (
    prepare_validated_projection_corpus,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_family_training_complete_v6 import (
    train_complete_prepared_projection_corpus,
    infer_complete_family_projection_autoencoder,
)

# rows contain original source_inputs and issued live observations.
corpus = prepare_validated_projection_corpus("intent_ir", rows)
fitted = train_complete_prepared_projection_corpus(
    corpus,
    output_dir=fresh_checkpoint_directory,
    epochs=24, patience=24, latent_width=4, minibatch_size=2,
    learning_rate=0.001, denoising=0.05, ridge=0.001,
    max_seconds=120, max_features=65536,
    memory_budget_bytes=512 * 1024 * 1024,
    adaptive_learning_rate=False,
)

# Independent test observations are prepared only after compared fits are sealed.
inferred = infer_complete_family_projection_autoencoder(
    fitted["descriptor"], live_evaluation_observations,
)
```

Every emitted native projection still needs its original parser/operator
lowering and actual modality Lake evidence. Capability floors, explicit
applicability reviews, source replay, producer guards, source isolation and
family nonregression selection remain in force. An absent optional projection
is masked; it is never converted into a zero target. A present unsupported
projection remains a blocker.

The shared solver scheduler and checked family-aware portfolio remain available
through the native preparation workflow. A solver's input syntax alone does not
establish support for temporal, deontic or cognitive semantics. Supplemental
solver results do not replace Lake. Only actual `lake build <Lib>` gives Lean
build evidence, and an input-projection build does not qualify a reconstructed
feature vector or prove the source's meaning. The Constitution remains
unformalized.

`max_seconds` bounds numerical initialization, calibration and refinement.
Source/evidence validation and feature preparation have separately reported
costs; this is not a whole-call deadline. A partial or late epoch cannot replace
the selected state. V6 adds no provider call, model download or higher sampling
temperature.

## Read the right loss and coverage fields

The training loss remains masked macro-family structural reconstruction on the
fitted vocabulary. Training atoms are now complete, but a new target may still
contain unseen atoms. The usual retained-coordinate `objective` must not be
interpreted as reconstruction of those unknown values.

`complete_support_metrics` reports an additional objective for inference. For a
fair old-versus-new comparison, pass the **same complete training reference** to
`common_support_metrics` for both models. Its scoring coordinates are the union
of that reference and all evaluation-only target atoms in the supplied batch:

- Actual predicted coordinates are unchanged. Missing coordinates predict zero.
- The target is normalized using all its original atoms, including unseen ones.
- Predictions are never rescaled with target mass or a known/full-target ratio.
- False-positive trained coordinates remain in the error denominator.
- Missing projections are masked, and every emitted projection receives loss.

The common-support metric is deliberately different from the old retained-only
training objective. Its equal support and denominator let a small vocabulary
retain its full penalty instead of appearing accurate by omitting target values.
Evaluation atoms never enter a fitted feature space or update a checkpoint.

Inspect `feature_selection.available_atoms`, `retained_atoms`, `discarded_atoms`
and the memory estimates alongside `coverage`. Common-support coverage reports
known/missing atom occurrences, unseen training atoms, missing target squared
mass, absent projection masks and the exact reference/support hashes. Encoding
or scoring every atom does not prove learned semantic fidelity.

## Fixed schedule first; adaptive schedule is experimental

V6 uses decoder-family blocks with a frozen encoder. Clean training and tuning
latents are cached, while denoising corruptions are encoded anew. The fixed
warmup/cosine schedule remains the default: `adaptive_learning_rate=False`.

The opt-in controller uses per-family tuning-selection plateaus:

```python
adaptive_learning_rate=True,
plateau_patience=3,
plateau_factor=0.5,
min_learning_rate_ratio=0.05,
```

A rate reduction preserves Adam's ongoing candidate trajectory and momentum.
Training gradients use training rows; the optional rate schedule and checkpoint
selection use tuning rows. Tuning is therefore not an independent holdout.
Family selection still requires the unchanged nonregression tolerance.

The reports retain candidate and selected tuning-family losses, clean training
losses, selected epochs per family, learning rates/scales, plateau counters,
per-family gradient/update norms, rejected regressions, deadline disposition and
memory reservations. These distinguish useful selected work from merely running
more epochs. A development comparison on the already exposed old feature basis
found the proposed adaptive setting worse than the fixed control in seven of
eight fits and tied in one. It remains an experiment, not an asserted improvement.

## Preserve the complete UI document before measuring a model

`decode_ui_ir(payload)` now decodes all **44 declared top-level UIIRDocument
fields** and their nested dataclasses. Rich documents retain states, events,
guards, effects, program and invocation bindings, producer/configuration/review
records, accessibility, localization and other declared facets. Semantically
ordered fields such as effect IDs, child IDs and locale fallbacks retain order;
the schema's canonical serializer still owns canonical ordering of records.

The wire decoder rejects unknown fields, duplicate JSON keys, wrong scalar or
container types, missing required nested fields, unknown enum values, nonfinite
numbers and unsupported versions. It does not turn `true` into an integer,
stringify identifiers or replace present null/false values with defaults. It
accepts only schema-defined defaults for omitted optional fields and still runs
the full schema/reference-closure validator. Resource bounds are 16 MiB, 200,000
JSON nodes and depth 64. Legacy schema migration remains explicit.

The learned 384D UI target validator uses this native decoder. Rich targets can
therefore reach the existing validation boundary without losing supplied fields.
This repairs the wire/target-validation path; it does not train the 384D neural
decoder, enlarge its token budget, establish natural-language correspondence or
prove all rich UI facets are projected. Unprojected facets remain explicit.

## Optional UI interface-binding readout in the registry workflow

The existing UI feature route can save and use a separate versioned readout:

```python
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.ui_feature_training import (
    train_ui_feature_batch, infer_ui_feature_batch,
)

with AutoencoderRegistry(weights_db, artifact_directory) as registry:
    result = train_ui_feature_batch(
        registry, training_rows, tuning_rows, fresh_attempt_directory,
        epochs=8, formal_decoder_version="ui_native_bindings_v2",
    )
    version_id = result["registration"]["version_id"]
    inference = infer_ui_feature_batch(
        registry, version_id, inference_rows, fresh_inference_directory,
    )
```

`formal_decoder_version=None` preserves the prior behavior. The optional head
fits fixed shapes and leaf choices from training targets only. Decoding reads
learned reconstructed feature scores without receiving expected target values.
The versioned result reports `decoded_native_record_count` separately from
`decoded_backend_formula_count`; all five current routes produce native records,
so `decoded_formulas_generated` remains false even when every record decodes.
It extends the missing validator for `ui_ux_ir:interface_bindings`, checking
binding/action/component joins, method names, risk/confirmation/idempotency
enums, inline schemas and interface-CID string consistency. Low/invalid scores,
unsupported shapes and invalid binding records retain abstentions.

The route's default projection set is F-logic, event calculus, TDFOL, DCEC and
interface bindings. This existing five-view feature workflow is separate from
the strict v6 full-native training boundary. It does not run or replace the
modality Lake checks, expand the full family inventory, or grant qualification.
Its complete binding record is JSON notation, not an independently proved
backend formula. Verifying a CID string does not verify the missing full
interface preimage, a DOM affordance or an observed runtime effect.

With the option enabled, training saves `formal-decoder.json` and
`decoder-tuning-fidelity.json` and returns `decoder_tuning_fidelity`. Registry
reopen/inference restores the saved decoder and returns `formal_decoding` plus
`decoder_fidelity`. Resume must name the same decoder version and retain the
existing source-group, tuning, producer and feature-basis checks. Parent
artifacts remain immutable; inference does not register or train a candidate.
The caller still owns the single database writer and resource admission.

The fidelity measurement compares every selected compiler-target field, scalar
type and ordered collection, including missing or extra values. It runs decoding
before inspecting the separate expected targets. Exact-projection fraction and
abstention counts remain separate. This is typed compiler-target equality, not
source-text entailment. The differentiable feature objective is unchanged;
these exact-match reports are additional diagnostics, not a new backpropagated
semantic loss or a newly trained neural formula decoder.

## Reproduce the complete-feature comparison

Use a frozen selected source tree and existing installed native tools:

```bash
PYTHONPATH="$PWD" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
CUDA_VISIBLE_DEVICES='' OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python scripts/ops/autoencoder/benchmark_complete_feature_convergence.py \
  --output /absolute/path/to/fresh-comparison \
  --lake /path/to/installed/lake \
  --java-executable /path/to/installed/java \
  --tla2tools-jar /path/to/installed/tla2tools.jar \
  --workers 4
```

The new `complete_feature_convergence_v2` panel contains authored Intent/UI
compositions: six training, two tuning and two test groups per domain. Two fixed
seeds compare the 4,096-feature decoder-block control, complete fixed schedule,
and complete adaptive schedule. Native validation uses the shared scheduler;
numerical fits are sequential and single-threaded. Each output directory is
fresh. All twelve compared fits and settings are sealed before the four test
source/target rows are prepared. Those exposed test results must not become a
fresh holdout again during subsequent tuning.

Retain `plan.json`, development native receipts, every training report,
`freeze.json`, `heldout-exposure.json`, all per-seed common-support reports and
`summary.json`. Compare per-seed family regressions, not only seed means. Report
native validation, target preparation, full fitting, numerical optimization and
inference timings separately. The public v6 inference call includes its internal
`common_support_metrics` calculation; the budgeted inference API does not. The
benchmark additionally computes shared-reference metrics outside those timed
calls for every strategy. Thus `inference_seconds` compares different public-API
workloads, not decoder-only speed. Two alternating seeds without a separate
warm-up phase provide descriptive timings, not a controlled throughput claim.
These are authored workflow measurements, not legal-IR bridge-on evaluate
timings or a production-corpus benchmark.

## Recorded validation: 2026-10-01

The frozen export of `f2da9045096ab8849d048c6b5f78a9db2597128d` plus
this change passed **258 focused tests**. The comparison completed in 623.59
seconds: 20 actual Lake builds (ten IntentIR, ten UIUXIR), 390 emitted projection
checks, 20 SANY syntax checks and four Z3/CVC5 propositional SAT diagnostics.
All twelve fits completed 24 epochs and 72 minibatch updates, selected later
than epoch zero, and were sealed before any heldout targets were prepared.
No model was promoted or granted admission.

Mean heldout objectives use the same complete support for all three strategies:

| Domain | 4,096-feature control | Complete fixed | Complete adaptive | Fixed reduction vs control |
| --- | ---: | ---: | ---: | ---: |
| Intent | 0.0269850934 | 0.0019580247 | 0.0019551900 | 92.744% |
| UI/UX | 0.0080373492 | 0.0025749414 | 0.0025761002 | 67.963% |

The large gains are mainly **coverage restoration**, not evidence that adaptive
rates found a better optimum. On this authored panel the complete fixed path
retained 26,986 Intent and 7,329 UI training atoms. Known heldout atom occurrences
rose from 15.108% to 99.651% for Intent and from 56.543% to 97.876% for UI.
Every unknown occurrence remains in the metric. The residual unknown atoms and
nonzero loss do not count as reconstructed source meaning.

Individual family regressions remain. Both seeds and both complete strategies
regressed Intent event calculus, first-order, propositional and TDFOL losses
against the paired control. For UI, both seeds regressed DCEC, event calculus,
first-order and frame logic; seed 1730 also regressed deontic loss. These small
regressions must not be hidden by the large aggregate reduction. Adaptive rates
were marginally better on mean Intent loss and marginally worse on UI; the
fixed schedule remains the default, with no post-test tuning or promotion.

| Domain | Control median full fit | Complete fixed median full fit | Control numerical refinement | Complete fixed numerical refinement |
| --- | ---: | ---: | ---: | ---: |
| Intent | 29.31 s | 31.47 s | 0.749 s | 0.869 s |
| UI/UX | 22.04 s | 22.36 s | 0.331 s | 0.475 s |

Each fit processes six training rows plus two tuning rows, with all native
revalidation intact. Complete fixed cost amortized over the six training rows
was 5.25 seconds per Intent row and 3.73 seconds per UI row. This includes
validation and preparation; it is not inference throughput. Across all twelve
fits, numerical refinement consumed 7.55 of 315.04 seconds of full fitting.
Complete coverage is not a measured throughput improvement. Native checks used
four requested workers; numerical fits were CPU-only, sequential and
single-threaded. There was no legal-IR bridge evaluate in this experiment, so
there is no bridge-on timing or target count to infer. The sampled process peak
was approximately 1.00 GiB RSS, excluding native children; it is not the per-head
tensor estimate or a hard resource ceiling.

The complete fixed Intent checkpoint was 7.15 MB versus 1.51 MB for the control;
UI was 2.46 MB versus 1.26 MB (seed 1729). Their conservative numerical tensor
reservations were 38.65 MB and 10.50 MB respectively, separate from Python,
serialized vocabulary, imports, allocator overhead and native workers. Keep
these costs when deciding how many simultaneous trainers a host can support.

The UI wire regression is separate: the old decoder rejected a rich document
because it dropped referenced feedback, and silently altered configuration,
producer and review fields in a simpler document. The new decoder preserves all
44 declared document fields, including through the real 384D target validator.
The optional five-projection readout passes registry training, reopen,
target-free score decoding and resume tests. It still reports native structural
records, not backend formulas or source-semantic qualification.

## Learned 384D source-decoder regression

A separate experiment used verified cached GTE-small 384D embeddings and the
existing trained local parent (SHA256
`969461ab82a2806e54ad33ba242a1eb62d032fa1b3cfc808b77c66dcc965aa62`).
All nine local encoder assets and cached vector/source hashes were checked;
no weights or embeddings were downloaded. Each modality used four training and
two **already exposed tuning** fragments. The unchanged 64-token target limit,
CPU execution and target-free inference were retained. This is not a fresh
holdout, a full-document test, or a source-semantics proof.

The first harness attempt failed after training because it wrapped an already
loaded `Runtime` again. The failed evidence is retained. After that one harness
fix, both 20-step runs reduced teacher-forced loss but produced zero native-valid
outputs. A disclosed follow-up allowed up to 1,000 epochs with patience 120,
still under the same 30-second numerical bound and otherwise unchanged settings.

| Domain | Initial tuning objective | Selected tuning objective | Steps / selected epoch | Full training call | Native-valid tuning IR | Exact tuning IR |
| --- | ---: | ---: | --- | ---: | ---: | ---: |
| Intent | 3.189560 | 0.117981 | 459 / 339 | 2.03 s | 2/2 | 0/2 |
| UI/UX | 3.167338 | 0.072384 | 750 / 630 | 2.85 s | 2/2 | 0/2 |

All four training outputs in each domain became native-valid, but exact training
reconstruction was only 1/4 Intent and 2/4 UI. Intent confused action, actor and
modality values, including permission/prohibition versus requirement. UI confused
role and privacy-sensitivity values. Tuning outputs retained an incorrect action
or role; one Intent output also had the wrong modality. These are meaningful
semantic errors, despite the lower token loss and valid syntax. No Lake run or
qualification was attributed to these learned outputs.

The next source-decoder acceptance work must measure those critical slots and
generated-output fidelity explicitly, jointly with embedding reconstruction.
More optimization steps alone did not solve them. The preserved 8D teacher was
not modified or evaluated by this experiment.

[Results and evidence manifest](../implementation/reports/evidence/complete-features-fidelity-20261001/results.json)
retain the full per-seed losses, learning curves, exact source/asset/data hashes,
failed harness attempt, native commands and logs. The adjacent `manifest.json`
indexes `evidence.tar.gz`, including the exact executed sources and generated
Lean/SANY inputs. Candidate weights remain local with recorded hashes; no Hub
upload or checkpoint promotion was performed by this release.
