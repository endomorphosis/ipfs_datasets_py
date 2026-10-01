# Actor composition: controlled formula-decoder evaluation

This experiment tests whether a decoder learns to preserve actors across norm
templates, instead of associating each actor with one training template. It
compares two training datasets with the same initialization, formula vocabulary
and optimizer-step budget. Results measure reconstruction of screened compiler
weak labels. They do not establish independent legal correctness, qualification
of an autoencoder, or fidelity across the full logic-family floor.

The historical 8D teacher and the new 384D decoder remain separate lineages.
See the [historical teacher guide](legacy_teacher_fidelity.md) for preserved
features, historical errors, supervision provenance and performance profiles.
The actor experiment loads **no historical teacher weights** and makes **no
historical teacher predictions**. It reuses the compiler screening policy from
`LegacyLinguisticTeacher` to prepare explicit weak labels; its observer's
numerical model is not encoded, decoded or trained.

## Fixed source panel and comparison

The source-only [manifest](../../tests/fixtures/logic/actor_composition_panel.json)
is validated by [formula_curriculum.py](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/formula_curriculum.py).
It contains the Cartesian product of six actors and six templates: 36 authored
diagnostic sentences. It contains no target formulas or model predictions.

Actors are `registrar`, `board`, `inspector`, `administrator`, `custodian`, and
`clerk`, in that order. Templates, in order, are:

| Template | Source pattern |
| --- | --- |
| `report` | The {actor} shall submit reports. |
| `prohibition` | The {actor} shall not disclose records. |
| `minimum` | The {actor} shall retain the file for at least 20 days. |
| `deadline` | The {actor} shall submit backup report within 10 days unless emergency. |
| `publication` | The {actor} shall publish notices. |
| `review` | The {actor} shall review applications. |

The split is fixed by `(template_index - actor_index) % 6`: offsets 0–3 give
24 training rows, offset 4 gives six tuning rows, and offset 5 gives six
evaluation rows. IDs, row order, text, split assignments and manifest hashes
are checked before fitting. Previously exposed sources and declared evaluation
actor/action pairs are excluded by the manifest loader.

The `balanced` arm uses all 24 training rows, giving each actor and each
template four appearances. The `confounded_diagonal` control uses the six
offset-zero training rows, pairing each actor with exactly one template. Both
arms contain every actor, every template and the same surface vocabulary; the
runner also checks that their actual formula codecs and initial model weights
are identical. Balanced marginals do not imply statistical independence: the
withheld pairs leave deliberate gaps in the training product.

The evaluation unit is an **actor × template pair**, not necessarily an unseen
actor × action pair. Two of the six evaluation actor/action combinations were
seen in balanced training under the other `submit` template. Report that
limitation when interpreting a score. Equal optimizer steps also do not imply
equal numbers of distinct training examples: the control repeatedly sees six
rows while the balanced arm sees 24.

## Model and fixed training settings

[evaluate_actor_composition_curriculum.py](../../scripts/ops/legal_ir/evaluate_actor_composition_curriculum.py)
opens a fresh `legal_ir/current_v2` runtime for each arm. Inputs use verified
local native 384-dimensional semantic embeddings. The sparse numerical core is
frozen; only the residual embedding projection and formula-token decoder train.
Serialized legal samples also contain parser-derived features. Consequently,
this is not an independent source-text-only formalizer.

| Setting | Both arms |
| --- | --- |
| Optimizer | Adam, CPU float32, one PyTorch thread |
| Learning rate | `0.02` |
| Batch size | `6` |
| Optimizer steps | `1000` by default, sealed in the plan |
| Training deadline | `120` seconds per arm; an incomplete step budget fails the experiment |
| Hidden size | `32` |
| Token embedding dimension | `16` |
| Residual projection width | `8` |
| Seed | `1729` |
| Objective | Formula-token cross-entropy plus projected-embedding MSE, each weighted `1.0` |
| Gradient norm clipping | `5.0` |
| Inference temperature | `0` |
| Formula token limit | Existing `64`-token limit |

The runner supplies an epoch ceiling of 1000, but equal **optimizer steps** are
the comparison budget. At batch size six, the control completes one epoch per
step and the balanced arm completes one epoch every four steps. No learning-rate
search, checkpoint selection or tuning-based promotion is performed. Tuning
losses are observations. The formula vocabulary is fitted from each arm's
training labels, and tuning labels must be encodable without extending it.

The training phase requires finite, nonzero parameter updates in both the
projection and decoder, unchanged sparse-core state, exact prediction equality
after save/reload, and identical checkpoints after a one-step resume. The
resume check occurs after the scored head is saved; that extra step is excluded
from the frozen artifact used for evaluation.

## Preparation, fitting and evaluation boundaries

The CLI uses separate processes for preparation, fitting and evaluation. Its
receipts enforce the following sequence:

1. `prepare` creates a new output directory and seals `plan.json` with source
   hashes, manifest identity, split policy, arm settings and step budget. A
   separate embedding process produces offline native embedding receipts.
   Screened compiler targets are prepared once and saved in separate training,
   tuning and evaluation files, alongside full compiler observations and typed
   student samples.
2. `train` verifies those artifacts and reconstructs the exact student samples
   from the verified embedding receipt. It reads only training and tuning target
   files. Each arm's initial binding, configuration, codec and model-state hashes
   must match. It saves both fixed-budget heads and their fit receipts before
   writing `frozen.json`, which records `evaluation_targets_opened=False`.
3. `evaluate` verifies both frozen head files, fit receipts, optimizer budgets
   and initialization identities before opening evaluation labels. It performs
   inference and generated-schema checks without fitting or selecting a model.
   Final source hashes must still equal the sealed plan.

Artifact references bind absolute paths, byte lengths and SHA-256 digests.
Embedding checks bind the exact source text, source artifact, document/section
ID, citation, producer code, model identity/revision, input/result ordering and
successful embedding status. Rebuilt full sample dictionaries must equal the
prepared samples. Prediction rows are checked against the frozen head identity
and their expected source hashes.

These are reproducibility and process-order checks. The preparation phase must
produce evaluation labels, and the source manifest is visible before fitting;
the experiment does not claim that evaluation texts were secret or inaccessible
to every caller. After evaluation, the actor panel is exposed. Future tuning
against it makes it a diagnostic regression panel, not a permanently blind
held-out benchmark. A later generalization claim needs a newly declared panel
and a fresh selection boundary.

## Free-running fidelity API

Use [formula_generation_metrics.py](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/formula_generation_metrics.py)
to compare the complete inference report with an explicit closed target set:

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.formula_generation_metrics import (
    compare_free_running_formulas,
)

metrics = compare_free_running_formulas(
    inference_report,
    targets,  # Each row has exactly id, source_text, canonical_ir.
    partition="sealed_evaluation",
)
```

Each `canonical_ir` has exactly `rules`; each rule has exactly seven facets:
`modality`, `actor`, `action`, `object`, `conditions`, `exceptions`, and
`temporal`. Rules and qualifier lists are compared exactly without silently
normalizing, discarding or completing fields. Qualifiers must already be sorted
and unique. If `formal_outputs` is present, its rule payloads must agree with
`canonical_ir`.

Every prediction row must explicitly declare `teacher_forcing=False` and
`target_access=False`, and its source hash must match the target's source text.
Top-level declarations may be absent; contradictory declarations invalidate the
evaluation. These declarations are checked, not independently proven. The
metric itself reads target labels after generation, as recorded by
`metric_target_access=True`.

This is a canonical-JSON comparison API. Its operational status does not
validate a projection identifier or require a `formal_outputs` envelope; when
that envelope exists, its payload must match. The runner supplies actual latent
decoder outputs and checks their generated schemas separately. Callers needing
projection-specific evidence must retain those producer and schema checks.

| Result field | Interpretation |
| --- | --- |
| `coverage` | Exact requested ID coverage, including missing, duplicate, unexpected and invalid IDs. Duplicate rows never receive credit by choosing a favorable occurrence. |
| `valid_evaluation` | Coverage and free-running/source evidence are consistent. It does not imply correct formulas. |
| `operational_complete` | A valid evaluation with no malformed output records. Honest abstentions can satisfy this while scoring zero. |
| `exact_reconstruction` | Matched/total/fraction for complete IR equality; `complete` also requires a valid evaluation. |
| `facets` | Matched/total/fraction for each of the seven facets across the entire ordered rule list. |
| `rule_count_exact` | Exact rule-count matching on valid decoded records. |
| `counts` | Separate decoded, abstained, malformed, unverifiable-generation, missing and duplicate counts. |
| `actor_confusions` | Expected and generated actor sequences with counts. |
| `diagnostics` | Formula/actor collapse, cross-target matches and source-copying display anomalies; none proves target copying. |

Every target remains in every accuracy denominator. Missing rows, abstentions,
malformed formulas and unverifiable generation receive no reconstruction
credit. A syntax-valid formula with the wrong actor is a reconstruction failure.
Low teacher-forced token loss, low embedding reconstruction loss, and reported
syntax success never contribute to exact matches. All admission, qualification,
independent-validation and held-out-fidelity authority flags remain false, even
when all explicit weak labels match.

## Schema checks and semantic limits

The supported learned output projection is `typed_deontic_rule_v1`. Its seven
facets include temporal strings, but the head does not encode typed temporal
sidecars such as the separate temporal-kind representation. Matching its target
JSON therefore does not establish preservation of every temporal semantic
feature. This experiment also does not test the full propositional, first-order,
deontic, temporal, cognitive-event-calculus or frame-logic projection floor.

Evaluation runs the existing generated-output schema path, which invokes an
actual `lake build <Lib>` for the emitted Lean schema artifacts. Record those
build receipts separately. A successful build establishes only that the
generated artifact passed that Lake check; it does not make compiler weak labels
independent gold or establish semantic equivalence to a law. The metrics module
does not run Lake and cannot issue an admit. No Constitution span is qualified.

The runner records compiler-label wall time per span and generation wall time
per span. It uses no metric bridges (`bridge_names=[]`, `legal_ir_target_count=0`),
no external prover evaluation, disk metric cache disabled, one metric worker and
no sample memory. These are not bridge-on evaluation timings. Temperature and
existing context limits stay unchanged; model weights are not downloaded.

## Run and inspect artifacts

Run all phases from the canonical checkout in a fresh process. A bare installed
`ipfs_datasets_py` import can otherwise resolve to the unrelated HACC editable
install. The script prepends its own repository root and the compiler path uses
the workspace-tree guard. If using an isolated source export, derive and verify
it from this canonical tree, retain its provenance, and run every phase against
that same pinned export. Do not mix source trees or update producer files after
sealing a plan.

```bash
cd /home/barberb/lift_coding/external/ipfs_datasets
PYTHONPATH="$PWD" python3 scripts/ops/legal_ir/evaluate_actor_composition_curriculum.py \
  --phase all \
  --optimizer-steps 1000 \
  --output-directory workspace/test-logs/actor-composition-new-run
```

For separate processes under explicit control, use a new output directory and
run these phases in order:

```bash
PYTHONPATH="$PWD" python3 scripts/ops/legal_ir/evaluate_actor_composition_curriculum.py \
  --phase prepare --optimizer-steps 1000 \
  --output-directory workspace/test-logs/actor-composition-new-run
PYTHONPATH="$PWD" python3 scripts/ops/legal_ir/evaluate_actor_composition_curriculum.py \
  --phase train --output-directory workspace/test-logs/actor-composition-new-run
PYTHONPATH="$PWD" python3 scripts/ops/legal_ir/evaluate_actor_composition_curriculum.py \
  --phase evaluate --output-directory workspace/test-logs/actor-composition-new-run
```

`prepare` owns the step budget stored in the plan. The supported budget range is
1–1000; a smaller budget is a different experiment. The internal `embeddings`
phase is invoked by preparation. Files use exclusive creation, so a completed or
partially written run directory is not an overwrite/resume target. Preserve it
for diagnosis and use a fresh directory for a new attempt.

Inspect `plan.json`, `prepared.json`, both `*-training.json` reports, the saved
heads, `frozen.json`, and `report.json`. The final report retains the complete
generation rows, facet metrics, source/sample provenance and generated-schema
receipts. `operational_ok` requires complete operations and successful schema
builds; inspect `exact_reconstruction` and actor metrics separately to assess
fidelity. Preserve the completed, source-bound run receipt with each result.

## Measured data ablation: 2026-10-01

The [retained evidence](../implementation/reports/evidence/actor-composition-20261001/)
records the first fixed-budget experiment. It ran from committed package
`a2f0081fc75addc906af8b2c179d1be6c1577410` plus the explicitly enumerated
curriculum, metrics and runner changes in an isolated export. Other active edits
in the shared checkout were excluded. Both arms used the settings above and
completed exactly 1,000 optimizer steps.

| Measurement | Six-row diagonal control | 24-row balanced curriculum |
| --- | ---: | ---: |
| Free-running training formula matches | 6/6 | 10/24 |
| Free-running tuning formula matches | 0/6 | 0/6 |
| Evaluation formula matches | 0/6 | 0/6 |
| Evaluation actor matches | 0/6 | 1/6 |
| Final training token cross-entropy | 0.000141 | 0.089336 |
| Tuning token cross-entropy | 1.096552 | 0.367939 |
| Reported training wall seconds | 15.785 | 15.690 |
| Generation wall seconds per span (six rows, one measurement) | 0.0670 | 0.0520 |
| Generated `lake build DecoderSchema` checks | 6/6 passed | 6/6 passed |

The balanced curriculum reduced tuning token loss but did not improve exact
formula reconstruction. It also failed to reconstruct 14 of its own 24 training
formulas. The experiment therefore does not establish either optimization
convergence or compositional generalization. Passing all 12 schema builds
coexisted with zero exact evaluation matches; the build receipts are evidence
about the emitted schemas only. This panel is now exposed and must not be
reused as an independent selection test.

Preparing the 36 compiler weak labels took 1.421 seconds, or 0.0395 seconds per
span, with metric disk cache disabled. This is compiler-label preparation time,
excluding native embedding production and sample construction. These runs used
`bridge_names=[]`, `legal_ir_target_count=0`, provers disabled, one metric worker
and sample memory disabled; they provide no bridge-on speed measurement.
Generation timings exclude embedding/sample preparation and Lake builds. These
single measurements are observations, not evidence of a stable speedup.

The earlier four-row failure was reproduced before this experiment. Raw native
embeddings and the frozen sparse-core transform retained actor differences;
the learned residual projection and decoder made those representations much
more similar. That observation and the controlled data ablation motivate
training/tuning-only optimizer experiments. They do not prove that a particular
layer, learning rate or data change alone explains the errors. The historical
8D teacher was not loaded, trained or changed in either experiment.

## Development-only learning-rate comparison

The follow-up
[compare_actor_optimizer_rates.py](../../scripts/ops/legal_ir/compare_actor_optimizer_rates.py)
compares learning rates `0.005` and `0.002` with the retained `0.02` balanced
reference. Every candidate starts from identical model weights, sparse-core
binding and formula vocabulary, and receives 1,000 updates on the same 24
training rows. It verifies that learning rate is the only configuration
difference, seals a plan before fitting, and never opens the evaluation targets
or evaluation report. The original ablation artifacts remain unchanged.

| Learning rate | Training exact | Tuning exact | Tuning actor | Tuning facet matches | Tuning token CE | Tuning embedding MSE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `0.02` reference | 10/24 | 0/6 | 1/6 | 32/42 | 0.367939 | 0.016727 |
| `0.005` | 14/24 | 0/6 | 1/6 | 25/42 | 0.334016 | 0.002645 |
| `0.002` | 3/24 | 0/6 | 2/6 | 26/42 | 0.284734 | 0.001105 |

All three settings still fail every complete tuning formula. Lower loss did not
produce better overall formula fidelity. The predeclared selection ranks
tuning exact matches, actor matches, total seven-facet matches, then negative
token cross-entropy, in that order. It consequently names `0.002` as the
development candidate because of one additional actor match, despite worse
total facet accuracy than the reference. This is an explicit tradeoff, not a
recommended replacement or automatic promotion. All candidate heads, raw
predictions and loss traces are retained, including unsuccessful results.

The new runs took 16.354 and 16.925 reported training seconds respectively;
the complete development comparison took 44.122 seconds. It used one CPU
thread, the same native inputs, and the same disabled bridge/prover/cache/memory
settings as the ablation. It executed no Lake builds and made no bridge-on speed
measurement. These are single-seed development observations, not a stable
performance benchmark or a global-minimum claim. Saved heads reproduce their
tuning predictions exactly after reload.

```bash
PYTHONPATH="$PWD" python3 scripts/ops/legal_ir/compare_actor_optimizer_rates.py \
  --input-directory workspace/test-logs/actor-composition-new-run \
  --output-directory workspace/test-logs/actor-optimizer-new-run
```

Use the same source export that created the completed 1,000-step ablation.
The output directory must be new. Selection is recorded at the comparison
layer; the nested, unchanged trainer receipts describe loss observation without
selection inside the trainer itself. A future independent generalization claim
requires new evaluation examples declared after development selection.

The next useful controlled experiments concern how actor and other source
features reach the decoder, and how embedding reconstruction competes with
formula generation. Test source-conditioned versus projected conditioning and
objective weights separately, with fixed budgets and explicit free-running
training/tuning scores. Preserve the 8D lineage, original failed runs, and all
qualification gates. More throughput or a longer campaign alone does not
resolve the observed errors.

The retained release receipts contain **216 passing tests** across curriculum
validation, formula metrics, training/evaluation phase boundaries, checkpoint
integrity and development-only selection. The 12 actual Lake schema builds
belong to the data ablation, not the learning-rate comparison. No model was
promoted, no legal span was admitted, and the Constitution remains
unformalized.
