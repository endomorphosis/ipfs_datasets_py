# Generated-prefix supervision for the formula sidecars

The experimental 8D, 384D and 768D formula sidecars combine scalar source-head logits with a recurrent decoder. Correct raw scalar predictions do not guarantee correct generated formulas. The next comparison separates changes to generated-prefix replay from adding supervision at incorrect generated scalar sites.

This path does not change the historical 8D linguistic teacher. Its 8D inputs are linguistic-feature hashes, not verified semantic embeddings. The larger sidecars use authenticated cached semantic embeddings. The identity projection remains frozen; learning in this comparison is confined to the formula-decoder parameters, with no teacher-distillation loss. These authored Legal examples are a small, repeatedly exposed development panel, not a fresh federal-law holdout.

## Entry points

- Training API: `ipfs_datasets_py/logic/formalization/autoencoder/long_span_source_value_training.py`, `train`.
- Collection and full-vocabulary losses: `generated_field_training.py` in the same directory.
- Sealed comparison runner: `scripts/ops/autoencoder/benchmark_generated_replay_consistency.py`.
- Previous head learning-rate experiment and evidence: [source_head_training.md](source_head_training.md).

`joint_generated_replay=True` explicitly selects the joint boundary/field replay implementation even when `generated_field_weight=0`. That zero-weight control still collects and measures first-wrong scalar sites, and includes their positions when constructing replay. It does not attach a zero-multiplied field-loss graph to the optimizer objective. Omitting the new option preserves the existing path.

With a positive field weight, training supervises the first incorrect generated site per scalar field (actor, action, modality and object). Generation finishes without reference documents, after which the loss helper authenticates training-only labels and clause alignment. It never forces tokens, closes syntax, or reduces the vocabulary. Invalid or unavailable source slots receive no fabricated labels.

Keep `generated_site_interval=1` when isolating this change. On the joint path, larger intervals skip both generated-field and generated-boundary supervision.

## Matched comparison

Every arm starts fresh and uses the previously tested non-action head learning-rate multiplier of 10:

| Arm | Boundary replay | Generated-field weight |
| --- | --- | ---: |
| `source-head-lr10` | Existing boundary helper | 0 |
| `joint-replay-zero` | Joint boundary/field helper | 0 |
| `joint-replay-fields` | Same joint helper | 0.05 |

The last two arms separate the field objective from the replay implementation. The first arm must reproduce the published predecessor's numerical reports and controls, excluding only recorded elapsed times and their dependent collection digest.

The comparison uses widths 8/384/768, seeds 1729/2718, 48 training and 48 exposed development rows, source lengths 1/2/4/8, 340 optimizer updates, 2,440 row presentations, 225,840 target-token presentations and 25,600 scalar-label presentations per fit. The encoder context and decoder output limit remain 512; temperature remains zero; all 32 output tokens stay in the loss denominator. Existing source-value/count losses, contrastive loss, clipping, selection and qualification rules are unchanged.

The intervention applies to fresh training trajectories. The preceding higher-width endpoints already reconstructed all 48 training rows correctly; training-only first-wrong supervision is inactive once a row is correct. Development mistakes are never inserted into the training inventory. The saved-data diagnosis found that all seven remaining higher-width development action mistakes used the unseen actor/action pairing `notary`/`approve`; the training set contains 15 of 25 actor/action combinations. This suggests a compositional generalization gap. Saved panels establish correct raw/applied head margins, but do not contain the final combined decision logits, so they do not establish numerical recurrent margins.

## Evidence boundaries

Report selected and final-attempt models separately, along with all nine source-conditioning controls, auxiliary active sites, full-vocabulary losses, replay retries and wall time. A rejected final attempt is not a promoted checkpoint. Comparisons on these reused development rows do not establish held-out convergence or a global minimum.

A resource guardian must observe its own unchanged, live scheduler lease while the child runs, and stop only its owned process group if the lease or shared configuration changes. Read-only observations use the scheduler's existing stable lock; the observer must not reset shared configuration, reacquire a lost lease or modify foreign claims. Bounded sampled observations establish observed coverage, not mathematically continuous coverage.

Numerical or syntax success grants no Lean admission. Only a successful `lake build <Lib>` with the required evidence can do that. This study performs no Lake build, native qualification, bridge-on evaluation, source encoder execution, weight download, Hub upload or production promotion. The Constitution remains unformalized.

## Measured results

The decision is to retain the replay control as an opt-in experiment and leave production defaults unchanged. Both 384D zero-weight controls improved from 47/48 to 48/48 exact; the 768D results were mixed (46/45 to 48/42), and 8D did not improve. The additional field loss was not a reliable improvement.

All 18 fits completed their 340 updates. The six baseline trajectories reproduced the published predecessor exactly apart from the registered timing exclusions. Results below are last-attempt diagnostics on the same 48 exposed development rows; they are not automatically selected or qualified weights.

| Width | Seed | Baseline exact / 48 | Joint zero exact / 48 | Joint fields exact / 48 |
| --- | --- | ---: | ---: | ---: |
| 8 | 1729 | 1 | 1 | 1 |
| 8 | 2718 | 2 | 2 | 1 |
| 384 | 1729 | 47 | 48 | 45 |
| 384 | 2718 | 47 | 48 | 48 |
| 768 | 1729 | 46 | 48 | 46 |
| 768 | 2718 | 45 | 42 | 45 |

Across the six repeated width/seed evaluations per arm, the development exact totals are source-head-lr10: 188/288, joint-replay-zero: 189/288, joint-replay-fields: 186/288. These are repeated evaluations of 48 documents, not 288 distinct held-out examples.

| Width | Seed | Baseline training exact / 48 | Joint zero training exact / 48 | Joint fields training exact / 48 |
| --- | --- | ---: | ---: | ---: |
| 8 | 1729 | 9 | 11 | 13 |
| 8 | 2718 | 11 | 11 | 15 |
| 384 | 1729 | 48 | 48 | 48 |
| 384 | 2718 | 48 | 48 | 48 |
| 768 | 1729 | 48 | 48 | 48 |
| 768 | 2718 | 48 | 48 | 48 |

Selected and final attempts must remain separate. The saved summary records selected epochs and predictions, each final rejection reason, extra/missing rules, all scalar readouts and all nine controls. No checkpoint is promoted by this comparison.

| Width / seed / arm | Selected epoch | Selected development exact / 48 | Fit wall seconds | Numeric evaluation ms / span |
| --- | ---: | ---: | ---: | ---: |
| 8-source-head-lr10-1729 | 0 | 0 | 47.846 | 6.611 |
| 8-joint-replay-zero-1729 | 0 | 0 | 50.522 | 6.610 |
| 8-joint-replay-fields-1729 | 0 | 0 | 49.654 | 7.341 |
| 8-source-head-lr10-2718 | 0 | 0 | 78.374 | 7.138 |
| 8-joint-replay-zero-2718 | 0 | 0 | 52.342 | 7.355 |
| 8-joint-replay-fields-2718 | 0 | 0 | 45.935 | 6.461 |
| 384-source-head-lr10-1729 | 0 | 0 | 68.670 | 11.211 |
| 384-joint-replay-zero-1729 | 80 | 48 | 66.152 | 9.733 |
| 384-joint-replay-fields-1729 | 0 | 0 | 70.635 | 9.596 |
| 384-source-head-lr10-2718 | 0 | 0 | 71.553 | 9.948 |
| 384-joint-replay-zero-2718 | 80 | 48 | 76.583 | 9.286 |
| 384-joint-replay-fields-2718 | 80 | 48 | 70.989 | 10.210 |
| 768-source-head-lr10-1729 | 0 | 0 | 90.719 | 12.185 |
| 768-joint-replay-zero-1729 | 80 | 48 | 88.572 | 13.249 |
| 768-joint-replay-fields-1729 | 0 | 0 | 101.527 | 12.450 |
| 768-source-head-lr10-2718 | 52 | 14 | 89.778 | 13.232 |
| 768-joint-replay-zero-2718 | 0 | 0 | 89.356 | 12.363 |
| 768-joint-replay-fields-2718 | 0 | 0 | 90.528 | 12.724 |

Timing uses one CPU worker, 48 samples per evaluation, bridge names `[]`, provers disabled and the legal-IR metric disk cache disabled. Source embeddings are already cached; the encoder and cold natural-language parser are not timed. The numeric API measures generation and CE; it excludes additional source-readout diagnostics, artifact writes and the recurrent-residual observation. No bridge-on legal-IR evaluate was performed, so no bridge speedup is claimed. The host was shared and this experiment matches optimizer steps and ordinary exposure, not wall time.

Summed fit wall times across six fits per arm: source-head-lr10: 446.940 s, joint-replay-zero: 423.526 s, joint-replay-fields: 429.268 s. Auxiliary collection/replay work and strict retries are retained per update in the raw receipts.

The guarded run completed with clean child and guardian exits. Resource accounting reserved 3,000,000,000 bytes, 4,096 MiB and one CPU slot under the existing 140,000,000,000-byte campaign cap. Maximum sampled process-group RSS was 2279800832 bytes; the absolute peak was not measured. Own-lease observations were healthy throughout the sampled active period. The longest active-monitoring gap was 1.344262 seconds; this is not continuous lease proof. Finalization intervals are reported separately in the independent audit.

Validation: 2,801 frozen regression tests, 62 isolated guardian tests, and 1842743 independent numerical/resource checks passed. Sixteen previously excluded setup cases for an incompatible retained 384D release were not run or counted as passes. No native family validator or Lake build ran.

Full artifacts, provenance, source files and predecessor references: [evidence manifest](../implementation/reports/evidence/decoder-action-consistency-20261003/manifest.json) and [results](../implementation/reports/evidence/decoder-action-consistency-20261003/results.json).

The extra field loss also produced a large finite pre-clipping gradient spike in the 384D/1729 run (about 289,244, versus about 318 for its baseline). Global clipping stayed at 1, and the final candidate regressed to 45/48 exact and 46/48 syntactically valid. This comparison does not demonstrate improved training stability.

One joint replay needed the existing strict incremental retry: 768D with field loss, step 95. The rejected bulk replay had maximum absolute logit difference about 0.0000452064. Original-batch incremental replay matched the collection exactly. The tolerance was unchanged; the rejected graph was discarded. All other joint fits used zero retries. Both the rejected and successful replay work are included in the receipts.

The saved 384D comparison locates the first replay-logit differences at updates 48 and 22, followed by differing model hashes at updates 49 and 23. Pre-update hashes and collected boundary logits initially match, and rounded boundary CE is initially equal. Joint replay uses 45 logical replay tokens across two active rows (37 and 8 tokens), versus 37 tokens across one row. The longest prefix remains 37; the joint batch has 74 padded row-tokens. This supports a finite-precision execution-path explanation; individual gradient tensors were not retained, so the mechanism is not proved. The successful zero-weight controls score zero exact documents under source shuffle. Reverse/rotate controls retain the 12 one-clause documents, whose order cannot change. These controls demonstrate source dependence, not formal semantic qualification.

The shared-host fit totals must not be treated as a demonstrated speedup. In particular, the 8D/2718 baseline took about 78 seconds, including about 36 seconds in boundary-loss work; the other 8D runs typically spent about 8 seconds on that work. A fresh holdout and a separately controlled timing study remain necessary before changing defaults.
