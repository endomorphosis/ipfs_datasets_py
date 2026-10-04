# Source readout diagnostics and optional head learning rates

The source head can learn slowly even when its clause vectors are distinct. The
training-only 8D probes below improved object readout accuracy by increasing the
learning rate of the existing head. The matched full-decoder comparison also improves larger-width development
reconstruction, with remaining errors and selection failures documented below.
Neither result establishes a global optimum, fresh holdout improvement, or
successful autoformalization.

The historical 8D linguistic teacher remains unchanged. These experiments use a
separate learned formula sidecar whose 8D inputs are cached, nonsemantic
linguistic-feature hashes. The 384D and 768D comparison lanes use their own
authenticated cached semantic inputs. Width alone does not identify a lineage,
input representation, codec, or decoder.

## Where to start

| Purpose | Entry point |
| --- | --- |
| Fit only an authenticated existing source head | [source_field_readout_probe.py](../../ipfs_datasets_py/logic/formalization/autoencoder/source_field_readout_probe.py) |
| Run the fixed eight-probe comparison | [benchmark_source_field_readout_probe.py](../../scripts/ops/autoencoder/benchmark_source_field_readout_probe.py) |
| Train a full source-conditioned decoder with optional head rates | [long_span_source_value_training.py](../../ipfs_datasets_py/logic/formalization/autoencoder/long_span_source_value_training.py) |
| Run the matched 8D/384D/768D decoder comparison | [benchmark_source_head_learning_rate.py](../../scripts/ops/autoencoder/benchmark_source_head_learning_rate.py) |
| Understand source fidelity, length limits, and retained unselected states | [decoder_length_distillation.md](decoder_length_distillation.md) |
| Use the unchanged historical teacher | [legacy_linguistic_training.md](legacy_linguistic_training.md) |

Use the workspace source tree or the exact frozen sources named in the run
manifest. In this workspace, a bare `import ipfs_datasets_py` can resolve to the
HACC editable checkout. Do not substitute that parser/runtime to make a test run.
The standalone readout probe intentionally imports no project package, parser,
encoder, compiler, or formula decoder; the decoder benchmark validates its pinned
dependency and extension trees.

## The training-only diagnosis

The diagnostic cohort has **180 clause occurrences from 113 distinct clauses in
48 authored Legal development paragraphs**. These are development fixtures, not
a completed US Code or Constitution corpus. Only the training partition supplies
probe inputs and labels. Object labels have 90 occurrences each, so the majority
baseline is 90/180. Repeated occurrences retain their original weighting.

The [geometry receipt](../../workspace/test-logs/decoder-object-readout-20261003/training-object-geometry.json)
found 113 distinct vectors after float32 input transformation and clause
normalization, with no contradictory-label collision groups. Nevertheless,
literal object substitutions can produce nearby vectors: the 34 inspected
literal object pairs have a mean normalized distance of 0.025529. Distinct
vectors do not prove that a particular finite head can separate all labels or
that optimization will find suitable weights.

The existing factorized head has an independent action branch and a shared
actor/modality/object branch. Each branch uses a learned affine projection into
64 tanh features. The shared branch has three separate full-vocabulary readouts.
Its zero-initialized readout causes the source projection's first task gradient
to be zero; subsequent gradients can be nonzero. AdamW weight decay can still
move projection weights on that first update. There is no object-specific
projection in this architecture. The full decoder also receives paragraph and
causal prefix information, so a raw source-head score is not its formula score.

The probe tests two private copies of the original fresh head for each seed:

| Mode | Trainable parameters | Objective |
| --- | --- | --- |
| `shared_non_action` | Original source projection and actor/modality/object readouts | `0.0625 * (CE_actor + CE_modality + CE_object)` |
| `isolated_object` | Exact copy of that projection and only its object readout rows | `0.0625 * CE_object` |

Each CE is a mean over all 180 occurrences and all **32 vocabulary logits**.
The object coefficient stays `0.25 / 4 = 0.0625`, matching its contribution to
the full trainer's four-field auxiliary loss. No logits are masked to the two
observed object labels. Isolation is a diagnostic parameter slice; it does not
install a new production decoder architecture.

Both modes use AdamW with betas `(0.9, 0.999)`, epsilon `1e-8`, weight decay
`0.01`, `foreach=False`, and a gradient-norm limit of `1`. Each fresh fit uses
one fixed learning rate, `0.001` or `0.01`, for 1,000 full-batch updates. There is
no scheduler, validation access, checkpoint selection, or formula generation.
Checkpoints at updates `0, 1, 10, 25, 100, 340, 1000` retain head parameters,
full logits, full-vocabulary CE, accuracy, target margins, separate field
gradient norms, projection-gradient cosines, and parameter movement. The final
Adam state is evidence, not an optimizer-resume interface.

## Measured eight-probe results, 2026-10-03

All accuracies below are **correct training occurrences out of 180**. CE is the
unweighted full-vocabulary object CE reconstructed from saved logits. Each row
is a separate fresh fit; it does not add 180 new independent examples.

| Seed | Mode | LR | Correct at 340 | Correct at 1,000 | CE at 340 | CE at 1,000 | Call seconds |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1729 | shared_non_action | 0.001 | 103/180 | 110/180 | 0.705581 | 0.659345 | 1.352 |
| 1729 | shared_non_action | 0.01 | 135/180 | 162/180 | 0.501926 | 0.268268 | 0.736 |
| 1729 | isolated_object | 0.001 | 102/180 | 107/180 | 0.701380 | 0.675376 | 0.577 |
| 1729 | isolated_object | 0.01 | 140/180 | 176/180 | 0.454198 | 0.189325 | 0.570 |
| 2718 | shared_non_action | 0.001 | 101/180 | 108/180 | 0.704102 | 0.669677 | 0.714 |
| 2718 | shared_non_action | 0.01 | 134/180 | 163/180 | 0.502602 | 0.275790 | 0.713 |
| 2718 | isolated_object | 0.001 | 103/180 | 101/180 | 0.701400 | 0.679280 | 0.576 |
| 2718 | isolated_object | 0.01 | 139/180 | 172/180 | 0.462404 | 0.207880 | 0.581 |

At 340 updates, the shared head's higher rate also changes actor correctness
from 167/180 to 180/180 for both seeds. Modality correctness changes from
154/180 to 180/180 for seed 1729 and from 151/180 to 179/180 for seed 2718.
Object isolation alone at rate 0.001 has mixed effects. The measurements support
testing the existing head's learning rate before adding a new architecture;
they do not establish the cause of the full decoder's reconstruction errors.

Each probe has seen 61,200 clause occurrences at update 340 and 180,000 at
update 1,000. Shared mode has three scalar targets per occurrence; isolated mode
has one. These full-batch exposures differ from the full decoder's paragraph
curriculum and combined loss. No probe update was clipped. That observation does
not rule out clipping effects in the full decoder, which also trains recurrent,
count, boundary, and action-contrastive paths.

The numerical runner took **7.149 seconds**; the eight helper calls sum to
**5.819 seconds**. Per-call times above include private head setup, optimization,
and checkpoint diagnostics, and exclude the runner's report serialization and
resource admission. There is no repeated timing distribution or demonstrated
rate-dependent speedup. The guardian wrapper took 65.930 seconds including
admission, monitoring, and finalization; it is a different timing scope.

This measurement used one CPU worker, cached source inputs, bridge names `[]`,
prover evaluation `false`, and metric disk cache disabled. No legal-IR target
count, bridge-on evaluate time, cold parser time, or legal-span inference time
was measured. Repeated clause presentations per second are not spans formalized
per second.

**Peak RSS was not measured.** The resource audit has one live RSS sample and a
final sample, with no periodic observation file. The largest recorded sample is
115,986,432 bytes; the 2,048 MiB reservation is not evidence of a measured peak
or continuous memory enforcement. Final retained attempt data is 40,518,693
bytes under the 200,000,000-byte reservation, which was released successfully.

The [outcomes receipt](../../workspace/test-logs/decoder-object-readout-20261003/outcomes.json)
and [independent audit](../../workspace/test-logs/decoder-object-readout-20261003/independent-audit.json)
retain the eight fits and 56 checkpoints. The audit passed 47,070 checks with no
findings. It reconstructs saved affine/tanh/readout, CE, and gradient arithmetic
under its stated numerical error bounds; it does not independently replay all
Adam updates. The first audit attempt and its correction remain retained: the
correction handled an absent periodic RSS log without changing numerical
acceptance tolerances.

## Supplying authenticated probe inputs

`run_source_field_readout_probe` takes `torch`, a plain training object, and a
plain initial-head object. Its keyword arguments are:

```python
result = run_source_field_readout_probe(
    torch, training, initial_head,
    expected_training_sha256=authenticated_training_contents_sha256,
    expected_initial_head_sha256=authenticated_head_contents_sha256,
    mode="shared_non_action", learning_rate=0.01,
    max_updates=1000, checkpoints=(0, 1, 10, 25, 100, 340, 1000),
    deadline=absolute_monotonic_deadline,
)
```

The training schema is `source-field-readout-probe-training/v1`, with exactly
`schema`, `split="train"`, `dimension=8`, `vocabulary_size=32`, ordered
`fields=["actor", "modality", "object"]`, and `rows`. Every row has exactly
`id`, literal `source_sha256`, an eight-value `input`, and those three integer
`labels`. Inputs must already contain the authenticated frozen input projection
and clause normalization. Repeated literal sources must have identical inputs
and labels. The helper accepts at most 180 occurrences.

The initial-head schema is `source-field-readout-probe-initial-head/v1`, with
exactly `schema`, `dimension=8`, `vocabulary_size=32`, `hidden_width=64`, those
ordered `fields`, and `parameters`. Parameter names and shapes are:

| Parameter | Shape |
| --- | --- |
| `source_projection.weight` | `64 × 8` |
| `source_projection.bias` | `64` |
| `field_readout.weight` | `96 × 64`, actor/modality/object blocks |
| `field_readout.bias` | `96` |

Fresh readout values must be zero. The helper privately selects rows `64:96`
for isolated object mode. It rejects extra fields, nonfinite values, booleans
used as numbers, contradictory literals, and unbound hashes before fitting.
The external expected hashes must come from authenticated receipts; hashing an
untrusted object and immediately trusting that hash is not source provenance.

The [adapter receipt](../../workspace/test-logs/decoder-object-readout-20261003/probe-adapter-receipt.json)
binds the input export to predecessor commit
`64bc5734dc82db72e955f2e809b770127e9b6cfc`, its published manifest, both original
fresh full states, and the literal training inventory. The tensor cross-check
confirmed all 180 exported float32 feature vectors against the actual frozen
preprocessing arithmetic. Caller objects and CPU RNG are preserved. A deadline
crossing during a private update rolls back both parameters and Adam state;
partial receipts cannot pass the fixed runner's 1,000-update requirement.

## Enabling the full-decoder head learning rate

Add this keyword to an already authenticated `long_span_source_value_training.train`
call, keeping the existing training/evaluation inputs and loss settings:

```python
result = train(
    student, training_rows, validation_rows,
    non_action_learning_rate_multiplier=10.0,
    **existing_authenticated_training_options,
)
```

The default is `1.0`. It preserves the original single-group AdamW construction,
scheduler settings, tensor update path, and report schema. The opt-in multiplier
must be a finite, non-boolean number from 1 through 10. Base rate times multiplier
must not exceed `0.1`; an enabled scheduler floor must remain representable and
positive. An unsupported model is rejected rather than assigned guessed groups.

An enabled multiplier accepts only the checked
`action-factorized-clause-source-decoder-development/v1` and
`ordered-clause-recurrent-source-decoder-development/v1` classes. It applies to
exactly these four trainable tensors:

```text
non_action_head.source_projection.weight
non_action_head.source_projection.bias
non_action_head.field_readout.weight
non_action_head.field_readout.bias
```

One AdamW optimizer owns two disjoint, exhaustive groups: `base` contains all
other trainable parameters; `non_action_head` contains those four tensors.
Global gradient clipping still sees the entire original trainable parameter
order once. The action branch, recurrent decoder, count head, and other base
parameters keep the base rate. Raising the non-action projection rate can also
affect its learned recurrent features; this is not an object-only intervention.

The existing `ReduceLROnPlateau` metric and cadence remain unchanged. The enabled
path gives each group a proportional minimum rate and sets scheduler `eps=0` so
tiny reductions cannot be independently skipped and break the ratio. This
explicit scheduler epsilon differs from Adam's unchanged `eps=1e-8`. The
disabled path retains the original scheduler epsilon and scalar minimum.

Both groups retain the same AdamW weight-decay coefficient. Because decoupled
per-step shrinkage depends on `learning_rate * weight_decay`, a 10× learning
rate also increases that shrinkage 10× at the same coefficient. The experiment
does not silently compensate by changing decay.

Enabled reports add `optimizer_parameter_groups` with exact names, parameter
counts, initial/minimum/final rates, multipliers, and decay. They also add
`optimizer_group_learning_rates` on each committed update and epoch, plus start
and end rate maps on each curriculum stage. Commit rates precede that epoch's
scheduler step; epoch rates follow it. The old `learning_rate` field remains the
base group's rate. Adam state continues across stages, with one optimizer.

Loss weights, target access, full-vocabulary outputs, deadline handling, frozen
projections, and per-length fidelity/reconstruction selection gates are
unchanged. Raw source-head accuracy remains diagnostic and cannot select a
candidate on its own. Keep initial, selected, and last-complete-attempt states
distinct; a better unselected endpoint is not a promoted checkpoint.

The standalone probe freeze passed **72 tests**. The optional-rate change then
passed **166 focused regression tests** on CPU, including exact default reports,
one-step unchanged base-group tensors, both supported head classes, all three
widths' parameter inventories, scheduler floors/ratios, deadline cleanup, and
unchanged fidelity rejection. An earlier expanded test attempt had 12 failures
and 154 passes because PyTorch's accelerator health check attempted CUDA and
ran out of GPU memory; that log is retained. The same source passed with
`CUDA_VISIBLE_DEVICES=''`. The subsequent full frozen scope passed **2,708
tests in 54.66 seconds**. These are distinct test scopes, not additive counts or
evidence of corpus qualification.

## Reproducing a sealed comparison

The command entry points use `--phase training`, `--dependency-root`,
`--extension-root`, `--manifest`, `--plan`, and a fresh `--output`. Run the exact
frozen runner identified by the manifest. A plan fixes the cohort, seeds,
recipes, budgets, vocabulary, and authority flags; the manifest pins inputs and
producer bytes. Neither runner is an unconstrained hyperparameter CLI.

The retained local campaigns are:

```text
workspace/test-logs/decoder-object-readout-20261003
workspace/test-logs/decoder-source-head-lr-20261003
```

From `/home/barberb/lift_coding/external/ipfs_datasets`, the guarded launch form
is below. Each command starts a new bounded comparison, so use it only when
intentionally allocating a new attempt; never overwrite a completed attempt or
launch a duplicate of an active comparison.

```bash
D=workspace/test-logs/decoder-object-readout-20261003
python3 "$D/run_diagnostic_reserved.py" --phase training --attempt probe-replay-01

R=workspace/test-logs/decoder-source-head-lr-20261003
python3 "$R/run_training_reserved.py" --phase training --attempt training-replay-01
```

These wrappers enforce manifest hashes and use the existing resource owner and
shared scheduler. Retain a passed readiness audit and verify every artifact hash
in it before launch. The one-shot `run_guardian.py` files record the original
attempt's wrapper exit and refuse to overwrite it. They are not resumable
training entry points. New attempts start from the bound fresh state; neither
trainer exports an optimizer-resume contract.

For reference, the underlying standalone probe command is:

```bash
P=/home/barberb/lift_coding/external/ipfs_datasets
D="$P/workspace/test-logs/decoder-object-readout-20261003"
S="$P/workspace/test-logs/ui-modal-coverage-20261002/validation-source-r2"
CUDA_VISIBLE_DEVICES='' OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
python3 "$D/experiment-source/scripts/ops/autoencoder/benchmark_source_field_readout_probe.py" \
  --phase training --dependency-root "$S" --extension-root "$D/experiment-source" \
  --manifest "$D/training-manifest.json" --plan "$D/training-plan.json" \
  --output "$D/probe-manual-01/results"
```

The underlying command alone does not acquire the campaign resource reservation;
the guarded wrapper is the campaign launch path. CPU-only settings also avoid
an unrelated accelerator initialization during these CPU tests. No weight
downloads or backend changes are required.

Inspect the probe without retraining by reading `outcomes.json`,
`independent-audit.json`, and each `probe-r1/results/<arm>/probe.json`. Its
independent saved-arithmetic audit can be repeated with a new output file:

```bash
python3 "$D/independent_probe_audit_r2.py" \
  --source "$D/experiment-source" --manifest "$D/training-manifest.json" \
  --plan "$D/training-plan.json" --results "$D/probe-r1/results" \
  --output "$D/independent-audit-recheck.json"
```

## Full-decoder comparison, 2026-10-03

The optional head rate improves final-attempt formula reconstruction strongly
for the 384D and 768D lanes, while 8D gains remain small. Both 384D candidates
reach 47/48 exact development paragraphs; 768D reaches 46/48 and 45/48. The
8D candidates reach 1/48 and 2/48. These endpoints remain separate from selected
checkpoints and production qualification.

This comparison has twelve fresh fits: widths 8, 384, and 768, seeds 1729 and
2718, and baseline versus `non_action_learning_rate_multiplier=10`. The same
48 training and 48 validation paragraphs recur across widths and seeds. Each
partition contains 180 clauses, with 12 paragraphs at each length 1, 2, 4, and 8.
The validation cohort has been repeatedly exposed during development. The
pooled exact counts change from 83 to 188 out of 288 validation scores and from
147 to 212 out of 288 training scores; these are repeated observations of the
same cohorts, not 288 fresh holdouts. Current 8D inputs remain nonsemantic
linguistic-feature hashes; 384D and 768D use authenticated cached semantic
inputs. No encoder is trained here, and this is not a dimension-only ablation.

Both recipes retain the original initializer, base rate `0.001`, batch size 8,
four curriculum stages of 20 epochs, count/source-value weights `0.25`,
action-contrastive weight `0.05`, and first/last generated-boundary weight
`0.05`. Generated scalar-field supervision is disabled. Encoder context and
decoder output limits remain 512, generation temperature remains zero, and
global clipping and per-length selection gates are unchanged. The opt-in group
also has proportional scheduler floors and scheduler reduction epsilon zero;
its higher rate increases AdamW decoupled shrinkage per step. This is not a
pure gradient-scale intervention.

All twelve fits completed 340 updates, 2,440 ordinary decoder/count row
presentations, 225,840 target-token presentations, and 25,600 source-field
labels. All six baseline arms replayed the predecessor's tensors, numerical
reports, and nine controls exactly, excluding only four declared timing or
time-derived receipt paths. Generated boundary work can differ as predictions
change; equal ordinary exposure does not imply equal compute.

### Final-attempt reconstruction and raw readouts

The tables below use the private **last complete attempt** unless explicitly
marked selected. `boundary-first-last` is the baseline; `source-head-lr10` is
the optional-rate candidate. Both entries in paired columns use that order.
Raw source scores use all 32 vocabulary logits at reference-present clause
slots. Generated scores come from source-only, temperature-zero decoding.
Reference token CE is a separate, teacher-forced reconstruction measurement.

| Width | Seed | Validation exact baseline / LR10, of 48 | Training exact baseline / LR10, of 48 | Validation reference CE | Fit seconds |
|---:|---:|---|---|---|---|
| 8 | 1729 | 1 / 1 | 8 / 9 | 0.130294 / 0.149074 | 43.907 / 44.901 |
| 8 | 2718 | 1 / 2 | 9 / 11 | 0.127689 / 0.150540 | 46.140 / 44.361 |
| 384 | 1729 | 13 / 47 | 24 / 48 | 0.108073 / 0.019463 | 60.788 / 68.299 |
| 384 | 2718 | 9 / 47 | 27 / 48 | 0.103594 / 0.018021 | 71.893 / 70.809 |
| 768 | 1729 | 17 / 46 | 31 / 48 | 0.079033 / 0.018836 | 95.071 / 90.992 |
| 768 | 2718 | 42 / 45 | 48 / 48 | 0.029421 / 0.017547 | 92.356 / 83.278 |

| Width | Seed | Arm | Validation exact at lengths 1/2/4/8 | EOS / syntax | Duplicates | Extra / missing rules | Generated actor/action/modality/object, of 180 |
|---:|---:|---|---|---|---:|---|---|
| 8 | 1729 | boundary-first-last | 1/0/0/0 | 48 / 48 | 10 | 157 / 157 | 110/75/144/88 |
| 8 | 1729 | source-head-lr10 | 1/0/0/0 | 48 / 48 | 9 | 155 / 155 | 104/79/141/88 |
| 8 | 2718 | boundary-first-last | 1/0/0/0 | 48 / 48 | 11 | 159 / 159 | 104/66/144/89 |
| 8 | 2718 | source-head-lr10 | 2/0/0/0 | 48 / 48 | 11 | 152 / 152 | 105/77/141/92 |
| 384 | 1729 | boundary-first-last | 8/1/3/1 | 48 / 47 | 0 | 57 / 63 | 153/165/136/172 |
| 384 | 1729 | source-head-lr10 | 12/11/12/12 | 48 / 48 | 0 | 1 / 1 | 180/179/180/180 |
| 384 | 2718 | boundary-first-last | 8/1/0/0 | 48 / 35 | 0 | 67 / 99 | 112/123/106/135 |
| 384 | 2718 | source-head-lr10 | 12/11/12/12 | 48 / 48 | 0 | 1 / 1 | 180/179/180/180 |
| 768 | 1729 | boundary-first-last | 9/4/4/0 | 48 / 45 | 0 | 50 / 63 | 134/152/155/165 |
| 768 | 1729 | source-head-lr10 | 12/11/11/12 | 48 / 48 | 0 | 2 / 2 | 180/178/180/180 |
| 768 | 2718 | boundary-first-last | 12/12/11/7 | 48 / 48 | 0 | 7 / 7 | 178/175/180/180 |
| 768 | 2718 | source-head-lr10 | 12/12/11/10 | 48 / 48 | 0 | 3 / 3 | 180/177/180/180 |

| Width | Seed | Arm | Panel | Raw actor/action/modality/object correct, of 180 | Raw object full-vocabulary CE | Raw object mean target margin |
|---:|---:|---|---|---|---:|---:|
| 8 | 1729 | boundary-first-last | training | 140/154/143/93 | 0.802564 | 0.029679 |
| 8 | 1729 | boundary-first-last | validation | 124/94/144/91 | 0.790985 | -0.001392 |
| 8 | 1729 | source-head-lr10 | training | 176/161/161/112 | 0.662513 | 0.098005 |
| 8 | 1729 | source-head-lr10 | validation | 102/84/141/91 | 0.704141 | 0.002776 |
| 8 | 2718 | boundary-first-last | training | 151/156/150/93 | 0.784904 | 0.028939 |
| 8 | 2718 | boundary-first-last | validation | 130/72/144/90 | 0.777866 | -0.001330 |
| 8 | 2718 | source-head-lr10 | training | 176/157/159/110 | 0.670731 | 0.080713 |
| 8 | 2718 | source-head-lr10 | validation | 102/80/141/92 | 0.708879 | 0.000335 |
| 384 | 1729 | boundary-first-last | training | 144/180/132/180 | 0.573729 | 3.739844 |
| 384 | 1729 | boundary-first-last | validation | 110/163/133/180 | 0.551381 | 3.782518 |
| 384 | 1729 | source-head-lr10 | training | 180/180/180/180 | 0.000967 | 9.979659 |
| 384 | 1729 | source-head-lr10 | validation | 180/180/180/180 | 0.000928 | 10.391770 |
| 384 | 2718 | boundary-first-last | training | 153/180/135/180 | 0.493308 | 3.877246 |
| 384 | 2718 | boundary-first-last | validation | 127/176/137/180 | 0.470825 | 3.906514 |
| 384 | 2718 | source-head-lr10 | training | 180/180/180/180 | 0.001485 | 9.961083 |
| 384 | 2718 | source-head-lr10 | validation | 180/180/180/180 | 0.001256 | 10.290207 |
| 768 | 1729 | boundary-first-last | training | 134/180/159/180 | 0.574957 | 3.794883 |
| 768 | 1729 | boundary-first-last | validation | 111/172/152/180 | 0.577769 | 3.736125 |
| 768 | 1729 | source-head-lr10 | training | 180/180/180/180 | 0.000993 | 9.831734 |
| 768 | 1729 | source-head-lr10 | validation | 180/180/180/180 | 0.000840 | 10.212077 |
| 768 | 2718 | boundary-first-last | training | 180/180/180/180 | 0.125650 | 5.229338 |
| 768 | 2718 | boundary-first-last | validation | 175/180/180/180 | 0.126488 | 5.244842 |
| 768 | 2718 | source-head-lr10 | training | 180/180/180/180 | 0.001403 | 10.141876 |
| 768 | 2718 | source-head-lr10 | validation | 180/180/180/180 | 0.001199 | 10.361246 |

Raw source-head outputs are diagnostics over reference-present slots. Generated scalar matches use the existing saved fidelity scorer, including missing or invalid output. Neither score is formal-logic semantic validation.

### Selected checkpoints and unchanged rejection gates

| Width | Seed | Arm | Selected epoch | Selected validation exact / syntax, of 48 | Selected extra / missing rules | Final selection rejection conditions |
|---:|---:|---|---:|---|---|---|
| 8 | 1729 | boundary-first-last | 0 | 0 / 0 | 0 / 180 | length=1/whole_rules_extra regressed; length=2/whole_rules_extra regressed; length=4/whole_rules_extra regressed; length=8/whole_rules_extra regressed |
| 8 | 1729 | source-head-lr10 | 0 | 0 / 0 | 0 / 180 | length=1/whole_rules_extra regressed; length=2/whole_rules_extra regressed; length=4/whole_rules_extra regressed; length=8/whole_rules_extra regressed |
| 8 | 2718 | boundary-first-last | 0 | 0 / 0 | 0 / 180 | length=1/whole_rules_extra regressed; length=2/whole_rules_extra regressed; length=4/whole_rules_extra regressed; length=8/whole_rules_extra regressed |
| 8 | 2718 | source-head-lr10 | 0 | 0 / 0 | 0 / 180 | length=1/whole_rules_extra regressed; length=2/whole_rules_extra regressed; length=4/whole_rules_extra regressed; length=8/whole_rules_extra regressed |
| 384 | 1729 | boundary-first-last | 0 | 0 / 0 | 0 / 180 | length=1/whole_rules_extra regressed; length=2/whole_rules_extra regressed; length=4/invalid_rule_count regressed; length=4/whole_rules_extra regressed; length=8/whole_rules_extra regressed |
| 384 | 1729 | source-head-lr10 | 0 | 0 / 0 | 0 / 180 | length=2/whole_rules_extra regressed |
| 384 | 2718 | boundary-first-last | 0 | 0 / 0 | 0 / 180 | length=1/whole_rules_extra regressed; length=2/invalid_rule_count regressed; length=2/whole_rules_extra regressed; length=4/invalid_rule_count regressed; length=4/whole_rules_extra regressed; length=8/invalid_rule_count regressed; length=8/whole_rules_extra regressed |
| 384 | 2718 | source-head-lr10 | 0 | 0 / 0 | 0 / 180 | length=2/whole_rules_extra regressed |
| 768 | 1729 | boundary-first-last | 0 | 0 / 0 | 0 / 180 | length=1/whole_rules_extra regressed; length=2/whole_rules_extra regressed; length=4/invalid_rule_count regressed; length=4/whole_rules_extra regressed; length=8/whole_rules_extra regressed |
| 768 | 1729 | source-head-lr10 | 0 | 0 / 0 | 0 / 180 | length=2/whole_rules_extra regressed; length=4/whole_rules_extra regressed |
| 768 | 2718 | boundary-first-last | 0 | 0 / 0 | 0 / 180 | length=4/whole_rules_extra regressed; length=8/whole_rules_extra regressed |
| 768 | 2718 | source-head-lr10 | 52 | 14 / 17 | 0 / 161 | length=4/whole_rules_extra regressed; length=8/whole_rules_extra regressed |

### Optimizer behavior and auxiliary work

| Width | Seed | Arm | Initial → final group LR | Committed rate reductions | Clipped updates / 340 | Peak preclip norm | Boundary labels | Collection / loss-helper seconds |
|---:|---:|---|---|---:|---|---:|---:|---|
| 8 | 1729 | boundary-first-last | base: 0.001 → 0.001 | 0 | 113 / 340 | 754.9347 | 3239 | 20.210 / 6.957 |
| 8 | 1729 | source-head-lr10 | base: 0.001 → 0.001, non_action_head: 0.01 → 0.01 | 0 | 89 / 340 | 306.7021 | 3229 | 21.278 / 6.756 |
| 8 | 2718 | boundary-first-last | base: 0.001 → 0.001 | 0 | 91 / 340 | 467.8382 | 3431 | 22.310 / 7.016 |
| 8 | 2718 | source-head-lr10 | base: 0.001 → 0.001, non_action_head: 0.01 → 0.01 | 0 | 58 / 340 | 195.3345 | 3380 | 20.145 / 7.017 |
| 384 | 1729 | boundary-first-last | base: 0.001 → 0.0005 | 1 | 138 / 340 | 292.7348 | 2804 | 25.721 / 14.367 |
| 384 | 1729 | source-head-lr10 | base: 0.001 → 0.001, non_action_head: 0.01 → 0.01 | 0 | 71 / 340 | 317.8484 | 3190 | 28.671 / 15.149 |
| 384 | 2718 | boundary-first-last | base: 0.001 → 0.0005 | 1 | 110 / 340 | 177.8101 | 2917 | 31.515 / 15.036 |
| 384 | 2718 | source-head-lr10 | base: 0.001 → 0.001, non_action_head: 0.01 → 0.01 | 0 | 66 / 340 | 7146.0010 | 3370 | 30.831 / 15.557 |
| 768 | 1729 | boundary-first-last | base: 0.001 → 0.0005 | 1 | 139 / 340 | 273.9439 | 3034 | 42.148 / 22.571 |
| 768 | 1729 | source-head-lr10 | base: 0.001 → 0.001, non_action_head: 0.01 → 0.01 | 0 | 99 / 340 | 10289.4531 | 3139 | 38.221 / 22.515 |
| 768 | 2718 | boundary-first-last | base: 0.001 → 0.001 | 0 | 87 / 340 | 125.2469 | 3334 | 40.035 / 22.440 |
| 768 | 2718 | source-head-lr10 | base: 0.001 → 0.001, non_action_head: 0.01 → 0.01 | 0 | 80 / 340 | 268.8762 | 3212 | 34.658 / 21.693 |

The base group has the same initial rate and scheduler policy in both arms, but its realized schedule can differ as losses change. Both 384D baselines and the 768D/1729 baseline reduced their base rate to `0.0005`; all candidates retained `0.001`. The measured gains therefore include this feedback through the unchanged scheduler, as well as the explicit head-rate and decay change.

The common global clipping operation covers both parameter groups in the original parameter order. Clipping statistics therefore describe the combined gradient, not an independently clipped head. First/last boundary supervision runs every committed update in both arms. It uses the unchanged contextual bulk replay and full-vocabulary CE; no generated-field auxiliary or strict causal retry is enabled in this comparison. Changed model predictions can change generated lengths and selected boundary labels even though the loss policy remains fixed.

### Wall-time scope

| Width | Seed | Arm | Fit seconds | Repeated training rows/second | Numerical seconds/48 | Numerical seconds/span | Full panel seconds/span |
|---:|---:|---|---:|---:|---:|---:|---:|
| 8 | 1729 | boundary-first-last | 43.907 | 55.57 | 0.303249 | 0.006318 | 0.009257 |
| 8 | 1729 | source-head-lr10 | 44.901 | 54.34 | 0.302477 | 0.006302 | 0.009303 |
| 8 | 2718 | boundary-first-last | 46.140 | 52.88 | 0.325137 | 0.006774 | 0.009803 |
| 8 | 2718 | source-head-lr10 | 44.361 | 55.00 | 0.305905 | 0.006373 | 0.009440 |
| 384 | 1729 | boundary-first-last | 60.788 | 40.14 | 0.493564 | 0.010283 | 0.021289 |
| 384 | 1729 | source-head-lr10 | 68.299 | 35.73 | 0.496205 | 0.010338 | 0.021123 |
| 384 | 2718 | boundary-first-last | 71.893 | 33.94 | 0.490393 | 0.010217 | 0.021128 |
| 384 | 2718 | source-head-lr10 | 70.809 | 34.46 | 0.498443 | 0.010384 | 0.021328 |
| 768 | 1729 | boundary-first-last | 95.071 | 25.67 | 0.690534 | 0.014386 | 0.033727 |
| 768 | 1729 | source-head-lr10 | 90.992 | 26.82 | 0.610666 | 0.012722 | 0.031680 |
| 768 | 2718 | boundary-first-last | 92.356 | 26.42 | 0.590731 | 0.012307 | 0.030880 |
| 768 | 2718 | source-head-lr10 | 83.278 | 29.30 | 0.568303 | 0.011840 | 0.029899 |

The numerical runner took **1,101.954 seconds**, and the twelve training calls
sum to **812.796 seconds**. The launch-return-through-child-reap interval was
1,104.728 seconds and includes monitoring/accounting; it is not an isolated
child-execution measurement. The guardian wrapper took 1,135.453 seconds and
exited with an error after the numerical child had completed. These timing
scopes must not be combined or treated as equivalent.

Evaluation uses one CPU worker, bridge names `[]`, prover evaluation `false`,
metric disk cache disabled, and 48 samples per evaluation. Source vectors and
contexts are authenticated cached inputs. No encoder execution, weight download,
cold parser measurement, or bridge-on evaluation occurred; legal-IR target
count is unmeasured. Numerical seconds include reference CE and source-only
generation. Full panels add control construction and fidelity/readout scoring;
additional potential-residual observations and serialization are separate.
Repeated training rows per second are not spans formalized per second.

These are single fits on a shared host, with different actual generated-boundary
work and occasional scheduler reductions. The mixed elapsed-time differences
are not an equal-wall-time comparison, a reproducible speedup estimate, or
evidence of fastest convergence. Shorter generation alone does not establish
faster correct conversion.

### What the improved endpoints still miss

All four 384D/768D candidates have 180/180 correct raw actor, action, modality,
and object readouts on both training and the exposed validation panel. All four
reconstruct 48/48 training paragraphs. Their final development outputs have
correct lengths and valid measured syntax for all 48 paragraphs, yet contain
respectively 1, 1, 2, and 3 incorrect action substitutions: `approve` becomes
`examine`. Raw reference-slot readouts can therefore be correct while the
combined recurrent/prefix-conditioned formula decoder still emits wrong actions.
The saved panels establish this separation; they do not identify which
particular downstream contribution causes it.

`whole_rules_extra` and `whole_rules_missing` measure unmatched rule content.
A substitution increments both even at the correct output length. For example,
the 384D candidates each generate 180 rules and have one extra plus one missing
rule. Matching counts and syntax do not establish faithful reconstruction.

The unchanged selector rejects every final attempt. Eleven runs retain their
initial epoch-0 state. The 768D/2718 candidate instead selects **epoch 52**,
with 14/48 exact and 17/48 syntax-valid validation paragraphs, only 19 generated
rules, zero extra rules, and 161 missing rules. Its later endpoint has 45/48 exact
paragraphs, 180 rules, reference CE 0.017547, and three extra plus three missing
rules; it is rejected for extra-content regressions at lengths 4 and 8. The
partial selected checkpoint is not a fully qualified model, and the improved
unselected endpoint is not promoted. The selection table preserves each run's
actual rejection conditions instead of relaxing them to admit better averages.

All nine inference controls remain retained for both selected and final roles:
conditioned validation, training, zero condition, source shuffle, cross-length
shuffle, context-only shuffle, context reverse, context rotate, and recurrent
residual off. Residual-off control preserves raw scalar readouts while changing
predictions. Its results are separate from the ordinary conditioned panel.

### Training-only 8D readout-to-generation diagnosis

The separately retained seed-1729 training panel has 180 clause occurrences.
At the final attempt, raw object correctness changes from 93/180 to 112/180;
generated object correctness changes from 94/180 to 112/180. In the candidate,
raw and generated object outputs agree in 176/180 positions. They are both wrong
in 66 positions; two raw-correct object predictions become wrong during
generation, while two raw-wrong predictions become correct. The raw object
readout remains a substantial limitation on this training panel. This is a
positional diagnostic for one training seed, not a causal proof about all errors
or a validation score.

The combined decoder's 340 updates supply 6,400 source-clause presentations,
compared with 61,200 in the standalone full-batch head probe: 9.5625 times as
much source-clause exposure in the probe at the same update count. The combined
trainer also has a length curriculum, other objectives, and global clipping.
For this pair, 113 baseline updates and 89 candidate updates were clipped;
no standalone probe updates were clipped. These differences prevent an
equal-work or isolated-clipping causal comparison with the standalone probe.
The 8D development reference CE worsens for both seeds, despite small increases
in exact paragraphs. Better training readouts do not establish generalization.

Source: [training readout transfer receipt](../../workspace/test-logs/decoder-source-head-lr-20261003/training-readout-transfer-8d-1729.json).

### Evidence, resource cleanup, and remaining work

The [outcomes analysis](../../workspace/test-logs/decoder-source-head-lr-20261003/outcomes.json)
passed 1,356,213 checks. The
[independent numerical audit](../../workspace/test-logs/decoder-source-head-lr-20261003/independent-numerical-audit.json)
passed 713,191 checks; the subsequent
[combined numerical/resource audit](../../workspace/test-logs/decoder-source-head-lr-20261003/independent-audit.json)
passed 714,113 checks with no findings. The latter incorporates the numerical
audit, so these are not additive independent test counts. It authenticates saved
arithmetic, inventories, optimizer telemetry, selection, and recovery evidence;
it does not independently replay every optimizer update. The earlier 72, 166,
and 2,708 test scopes and retained failed CUDA-environment attempt are described
above. The immutable initial documentation review covers the probe/API portion;
this completed section requires its own final documentation review.

The numerical child exited **0** after all twelve fits were durable. The guardian
exited **1** when scheduler lease release raised `ResourceConfigurationError`
after the disk-release step. The original failure and exit receipts remain
retained. [Read-only reconciliation](../../workspace/test-logs/decoder-source-head-lr-20261003/resource-reconciliation.json)
verified the existing released disk reservation, exact attempt directory
identity, dead owner and child group, and an absent scheduler lease. It did not
reset the scheduler, release a lease, modify other claims, rerun a model, or
rewrite the original exit. The failure-time scheduler configuration and the
actors responsible for its change or subsequent lease removal were not
captured. This is recovered accounting, not a clean end-to-end guardian success.
Initial reservation, sampled resource checks, and end reconciliation do not
prove continuous scheduler-lease coverage.

The resource audit records 60 observations, with a maximum observed RSS of
2,301,554,688 bytes. **Peak RSS and continuous memory enforcement are not
measured.** The reservation was 4,096 MiB, one CPU slot, and 3,000,000,000 storage
bytes; these are resource bounds, not measured peaks. The completed-attempt
release inventory is 818,464,439 bytes, before additive reconciliation-receipt
bytes. The existing ledger records the disk reservation as released.

The option remains experimental. The measured next gaps are:

- **8D source learning:** the object readout remains weak and its training
  exposure differs greatly from the standalone probe. A matched exposure and
  optimizer-interaction test is needed before claiming a better representation
  or changing the architecture.
- **Larger-width generation:** correct raw scalar heads still become incorrect
  generated actions. Inspect the actual source-only prefix and downstream
  contributions while preserving full-vocabulary output and strict fidelity.
- **Gradient stability:** the 384D/2718 and 768D/1729 candidates reach preclip
  norms of 7,146.0010 and 10,289.4531. Global clipping stays at 1, but fewer
  clipped steps or better endpoints do not prove stable convergence. Those
  spikes need diagnosis before wider use.
- **Scheduler lifecycle:** resolve the cleanup configuration mismatch and verify
  the guarded lifecycle before claiming readiness for unattended long runs.
  Successful numerical fits do not erase the guardian failure.

All twelve initial, selected, and final-attempt states and all 216 control panels
remain evidence. No production checkpoint is promoted. These measurements do
not prove global convergence or fastest convergence, and the development cohort
is not a fresh holdout. Frozen identity-projection MSE is not learned source
reconstruction. No native logic-family or Lake qualification was performed by
these fits. Numerical fitting, readout accuracy, measured syntax, matching counts,
and DuckDB/Hugging Face rows do not confer admission.

Lake `lake build <Lib>` remains the only Lean admission. The historical 8D
linguistic teacher is unchanged. The Constitution is not formalized and must not
be marked `roundtrip_ok`.
