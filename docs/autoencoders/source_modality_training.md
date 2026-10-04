# Auxiliary source-modality training

This opt-in experiment adds supervised source-modality examples to the existing
Legal formula-sidecar curriculum. It tests a coverage gap in the 384D source
head, using already cached training vectors. It leaves the default objective,
checkpoint selection and historical 8D linguistic teacher unchanged.

## Entry points

- `source_modality_auxiliary_training.adapt_original_training_bank` authenticates
  the original authored training records against their cached source vectors.
- `prepare_bank` prepares either the 113 unique clauses already used by the
  paragraph curriculum or all 180 clauses in the original training bank.
- `validate_training_binding` binds that bank to the actual fit's 48 training
  paragraphs and 113 clause vectors, and excludes actual validation sources.
- `long_span_source_value_training.train` accepts an explicit
  `auxiliary_source_modality_bank` and positive
  `auxiliary_source_modality_weight`. Both must be supplied together. The default
  `None`/zero pair imports no auxiliary helper and adds no loss graph.
- `scripts/ops/autoencoder/benchmark_source_modality_training.py` runs the fixed
  six-fit comparison and retains the original controls and exposed-cohort scores.

The comparison's positive arms explicitly enable
`generated_boundary_retry_on_mismatch=True`. This opt-in boundary path first
checks bulk replay against the original collected logits. If that check fails,
it discards the failed graph and retries once using the original collection batch
and token-by-token execution. All selected logits must still pass the unchanged
absolute and relative tolerances. The baseline retains the original default
boundary path. Extra forward work and any batch-grouping differences are reported;
they must not be mistaken for free supervision or an unchanged positive-arm graph.

The first attempted comparison reproduced its initial baseline, then stopped the
first auxiliary fit when bulk boundary replay failed the original check. A guarded
reproduction reached the failure after 53 committed updates and retained the
failing model, collection, contexts and all logit differences. The original failed
run did not save its private committed-step count. Original-batch full-prefix replay exceeded
the tolerance by a factor of 1.704; original-batch incremental replay was bit-exact
with both gradients enabled and disabled. Singleton incremental replay also
failed, showing why preserving batch membership matters. No optimizer update
continued after that failure. The revised comparison starts all six fits afresh;
the failed attempt remains part of the evidence.

The current helper intentionally supports the authored Legal 32-token codec and
these specific bank sizes. Accepting 8D, 384D or 768D vectors does not mean this
experiment validated all three input systems or other IR modalities.

## Why test source coverage

The previous source-margin comparison left 59 modality errors across its two
positive 384D final states: each changed obligation (`O`) to permission (`P`).
An independent reconstruction of saved source-head arithmetic agrees with the
emitted tokens at all 360 modality positions. It was calibrated against saved
native full-vocabulary logits, with explicit float32 and tanh allowances. This is
a saved-state calculation, not a new native forward pass. The positive 384D
argmax margins exceed those allowances; one baseline near-tie remains uncertain.

The original curriculum contains 180 clause occurrences but only 113 unique
source clauses. Its training modality predictions are already correct. This
comparison therefore tests broader source coverage, rather than training-label
underfit. The 180-source bank adds both missing content combinations and wording
variants; those two effects cannot be separated by this experiment.

## Objective and cost

At every committed optimizer update, choose one clause from each of six strata:
obligation, permission and prohibition, each in the two original wording styles.
The deterministic cyclic sampler is keyed by seed and committed step, without
using the paragraph sampler's RNG or advancing state on an aborted update.

```
loss = ordinary_objective + 0.05 * mean(six full-vocabulary modality cross-entropies)
```

Only source slot zero's modality field supplies the auxiliary loss. Its direct
gradients reach the modality readout and shared non-action projection. Shared
features and the unchanged global gradient clip can affect other fields, so
actor, action, object, ordering and cardinality still need separate measurement.
The auxiliary path performs no encoder, count-head, recurrent or greedy forward
pass. It prepares transformed tensors once per private model, using the original
113-source normalization without refitting it.

Bank preparation excludes validation, test, canary and previously exposed
evaluation sources by identity, normalized text and vector hash. The trainer
also checks the actual current training/validation contexts before allocating a
private training copy or cache. The runner has already constructed its initial
candidate at this point. File provenance is authenticated by the runner; the
helper checks correspondence between the supplied records and vectors.
Bank hashes, cohort bindings, selected source IDs, all
32 logits, per-row losses, gradient weighting and committed exposures are retained.
Memory estimates include cached tensors and receipts; they are not RSS quotas.
Deadline checks discard uncommitted work, including expiration after backward or
clipping. Saved numerical states omit optimizer state and are not resumable jobs.

## Fixed comparison and evaluation

The three arms are the original `source-head-lr10` baseline, auxiliary training
from `used113`, and auxiliary training from `full180`, each at seeds 1729 and
2718. All are 384D, initialized afresh. Source-margin replay is off in all arms.
The baseline must reproduce its archived numerical results apart from explicitly
registered timing fields. The primary comparison is `full180` versus `used113`;
the baseline measures the combined cost of auxiliary work and its opt-in retry
policy.

Each arm retains 340 optimizer updates, 2,440 paragraph presentations, 225,840
target-token presentations and 25,600 original scalar-label presentations. Each positive arm
adds exactly 2,040 clause presentations: 680 per modality, 340 per stratum.
Additional supervision is explicitly counted, not treated as a free speedup.
Optimizer/scheduler configuration, clipping, selection criteria and the
48-paragraph development set remain fixed. Adaptive learning rates may differ
between arms when their validation losses differ.

Retain initial, selected and final-attempt states, and all nine original controls
for both endpoints. Evaluate all 12 selected/final endpoints on the prior R6
cohort only after all fits complete. Save every source-only prediction before
loading reference JSON for scoring. That cohort is now exposed development data;
its scores cannot establish fresh generalization or choose a promoted checkpoint.

Temperature and both token limits remain 0 and 512 respectively. No weights are
downloaded, no encoder executes, and cached source vectors are reused. The compiler,
decompiler and parser remain pinned to the frozen workspace tree. Benchmark
provenance distinguishes historical dependencies from the revised trainer,
including their separate source hashes and module names.

## Authority and next steps

This measures reconstruction of authored formulas in a closed codec. It does not
expand logic-family coverage, certify statutory semantics, prove convergence or
demonstrate end-to-end bridge throughput. The identity input projection is frozen;
its reconstruction MSE is not learned reconstruction. No trial is automatically
promoted. Only `lake build <Lib>` can admit the corresponding Lean artifact, and
this numerical comparison runs no Lake build or external prover. The Constitution
remains unformalized; no span acquires `roundtrip_ok` from these scores.

## Completed comparison, 2026-10-04

All six fresh fits completed 340 updates. Both auxiliary arms reached 48/48 exact
paragraphs on the original development set at each seed, and the unchanged
selection rule selected their final epoch 80 states. The baseline finished at
47/48 for each seed; its selection rule retained the initial epoch 0 state. Both
baseline runs reproduced their archived numerical states, reports and controls.
At the final epoch, both baselines substitute `examine` for `approve` in one
two-rule paragraph. That creates an extra rule relative to the reference and
fails the unchanged per-length nonregression gate. Cross-entropy and input MSE
are not the blocking checks. Auxiliary and exposed-cohort scores do not drive
checkpoint selection.

The broader exposed cohort did not improve. The following totals combine two
seeds on the same 48 paragraphs: 96 predictions, not 96 independent examples.
Modality and action counts use the corresponding 360 rule positions. Auxiliary
selected and final states are identical; the baseline endpoints are distinct.

| Arm and endpoint | Original development exact /96 | Exposed exact /96 | Exposed modality /360 | Exposed action /360 | Exposed full-vocabulary CE |
| --- | ---: | ---: | ---: | ---: | ---: |
| Baseline, selected initial state | 0 | 0 | 0 | 0 | 4.664420 |
| Baseline, final attempt | 94 | 61 | 302 | 359 | 0.028041 |
| Used113, selected and final | 96 | 57 | 301 | 357 | 0.029101 |
| Full180, selected and final | 96 | 58 | 293 | 360 | 0.027700 |

Actor, object, conditions, exceptions and temporal fields were 360/360 for all
three final arms on this cohort. Full180 reduced average cross-entropy relative
to Used113 but made eight more modality mistakes. Lower average token loss is
therefore insufficient evidence of better obligation/permission reconstruction.
The auxiliary objective remains off by default, and no candidate is promoted.

| Arm | Total fit seconds, two seeds | Paragraph presentations/second | Seconds/presented training paragraph | Final greedy seconds/span |
| --- | ---: | ---: | ---: | ---: |
| Baseline | 132.717 | 36.77 | 0.02720 | 0.00826 |
| Used113 | 130.057 | 37.52 | 0.02665 | 0.00836 |
| Full180 | 135.910 | 35.91 | 0.02785 | 0.00821 |

Each training rate uses 4,880 paragraph presentations across two seeds. Positive
arms additionally process 4,080 auxiliary clause presentations; these are not
included in that numerator. Fit timing includes the trainer's scheduled
validation, but excludes the later control panels and exposed-cohort evaluation.
Final greedy timing covers 96 exposed-cohort predictions per arm and excludes
teacher-forced scoring. Sequential CPU fits on a shared host do not establish a
speedup from these small differences. The complete child took 562.405 seconds;
the reservation/guardian wrapper took 613.918 seconds.

These are cached-vector formula-sidecar timings with one worker, bridge names
`[]`, prover evaluation false and metric disk cache off. No bridge-on evaluate
ran, and there are no legal-IR targets. The encoder was not executed. These
numbers are not a faster legal-IR or end-to-end autoformalization measurement.

The Used113/1729 run needed one strict original-batch retry: 37 token steps and
296 physical row-tokens. The other three auxiliary fits needed none. Accepted
logits passed the original tolerances; the failed bulk graph supplied no loss.
The default baseline replay path remains unchanged. The audit verified all
recorded replay work, including discarded work.

The frozen scoped suite passed 3,434 tests with no failures, errors or skips;
16 inherited incompatible 384D setup cases remain outside that suite and are
not counted as passes. Independent comparison audit: 496,128 checks with zero
findings. The prior failed attempt and its successful diagnostic are preserved.
Thirty live resource samples reached at most 1,502,552,064 resident bytes; this
is a sampled maximum, not an absolute peak. Durable release accounted for
471,061,156 bytes, and the owned lease was observed absent after cleanup.

The remaining training gap is source-modality generalization. Before another
fit, inspect obligation/permission errors by wording and content combination,
and distinguish confident wrong predictions from near-ties. Any new objective
needs its own predeclared comparison and a separately sealed fresh cohort after
development, followed by checks for 8D and 768D. Broader bank coverage alone has
not resolved this gap.

The [evidence guide](../implementation/reports/evidence/decoder-modality-gap-r2-20261004/README.md)
links the [results](../implementation/reports/evidence/decoder-modality-gap-r2-20261004/results.json)
and [archive manifest](../implementation/reports/evidence/decoder-modality-gap-r2-20261004/manifest.json),
including full logits, private numerical states, references, failed attempts,
resource receipts and the independent audit.

## Integration with concurrent upstream changes

While the numerical study was finishing, `origin/main` changed five compiler and
runtime dependencies. The publication candidate preserves those upstream bytes
from `b11f2514a0180fdbebb4bcd878beef21885cb7db`, with only the eight owned Python
changes overlaid. A separate isolated check passed the same 3,434-case scoped
suite in 71.15 seconds, after a focused check of the legacy 8D feature path.
The three original semantic gates also passed: the 10-day exception-bearing
obligation remains non-renderable as a threshold; the disclosure clause is a
prohibition; and the minimum-duration clause retains integer quantity 20 and
the correct decompiled text. Empty vocabulary still abstains for all three.
These checks execute no Lake build and grant no admission.

The separate check retains its earlier failed harness/environment attempts:
incorrect access to parser sidecar metadata, pytest path reporting while a test
forbids imports, and missing legacy snapshot JSON manifests in the initial
Python-only checkout. The completed candidate includes all three authenticated
legacy manifests. No test assertion, model source or weight was changed to fix
those environment issues.

The numerical six-fit study was not repeated against the newer dependencies.
Its original frozen sources remain separate from the publication sources in the
archive. The scoped suite exercises the legacy snapshot rather than the main
`modal_autoencoder.py` runtime and its new lazy worker-budget path. Static review
found that runtime's only AST change was in `_legal_ir_parallel_worker_count`, with
its signature unchanged; this is not execution coverage for the new scheduling
behavior. The integration check establishes the recorded scoped compatibility,
without extending the numerical, performance or semantic claims above.
