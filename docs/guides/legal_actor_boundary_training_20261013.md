# LegalIR actor boundary experiment, 2026-10-13

The opt-in actor start/end adapter completed 32 updates. Authored training complete IR remained **153/168** and actor exactness remained **155/168**. One exposed authored evaluation panel improved from **32/72 to 33/72** complete joint IR. Fresh development and test complete IR remained **0/36** each. No checkpoint is selected or promoted to the default decoder.

## Implementation and measured behavior

`SpanActorBoundaryAdapterDecoder` in `ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_actor_boundary.py` starts from the common N4 split-feature checkpoint. It preserves the original 34 tensors and trains four copied start/end tensors. Only actor row 0 is active: 130 scalars out of 780 stored scalars. The remaining 650 copied scalars retain their original values, zero gradients and zero Adam moments. Full six-row copies preserve the parent matrix-operation geometry.

The recipe uses 168 authored training examples, fresh Adam, learning rate 0.001, seed/order seed 1729, batch size 12 and 32 updates. The inherited actor ranking term is disabled. Configured 384D vectors are dormant placeholders with latent conditioning disabled and zero external encoder calls.

| Exposed authored measure | Initial | Trained |
|---|---:|---:|
| Training complete IR, raw and joint |153/168|153/168|
| Training actor exact, raw and joint |155/168|155/168|
| Training actor gold top1 |156/168|156/168|
| Training actor gold top8 |168/168|168/168|
| Authored evaluation complete joint IR |32/72|33/72|
| Authored evaluation joint actor exact |60/72|63/72|
| Older authored evaluation complete joint IR |51/72|51/72|
| Older authored evaluation joint actor exact |59/72|61/72|
| Legacy complete IR, raw and joint |94/96|94/96|
| Fresh development complete joint IR |0/36|0/36|
| Fresh test complete joint IR |0/36|0/36|

Complete IR compares all seven fields, including modality. Legacy 94/96 is caused by two temporal mismatches; legacy actor and modality each remain 96/96, and all 32 permission cases retain P. The same authored evaluation ID gains complete IR on raw and joint routes, with no complete-IR losses across the paired diagnostic panels. These are exposed diagnostics, not blind evaluation.

Five training gold actor ranks improve, with rank sum 215 to 206, without changing top1/top8 counts or training exactness. All 168 training gold actors were already retained in top8. Full gold assignments survive the retained domain for 160/168 training examples, but 0/36 on each fresh panel. Fresh actor top8 coverage is 30/36 development and 13/36 test. Ranking and fixed-head/candidate-coverage blockers need separate treatment.

All 15 training complete-IR failures persist: five selected actor-only failures, six selected modality-plus-actor failures, one selected actor/object/exceptions failure, two selected condition failures and one abstention. Four selected O cases and two selected F cases incorrectly retain P. The joint selector fixes modality and optional-field presence before span search, so actor-only updates cannot repair those wrong fixed decisions. The prior actor-error counts must not be interpreted as 13 independently recoverable whole-rule errors.

## Validation and preservation

Ten detached contract tests passed. Both actual 632-source gates passed: complete-head parent parity before training and protected-head binary32 retention after training. Only actor start/end scores are excluded from the final protected comparison. All 632 actor vectors changed; protected vectors remain identical. The independent standard-library recount agrees with the qualified analyzer on 837 comparisons across 23 state panels, 21 scored sets and nine paired panels.

The successful trial performs 1,520 inference forwards plus 32 training batch forwards, with 384 training row occurrences and 1,904 total source occurrences. All 62 outputs were frozen before reference scoring, totaling 61,920,310 bytes. The checkpoint is 6,450,800 bytes. The initial attempt failed during source preflight before any model loading, inference or update. Its retained 200 MB claim remains preserved. Postrun audit corrections changed neither the model nor the scoring definitions and caused no retraining. The terminal audit preserves all 534 prior claim records and observes only the successful run's new released claim, for 535 records total. No storage cap was raised.

## Next training comparison

The measured gap supports testing an actor span ranking objective. The existing `legal_span_targeted_loss.py` already supplies `_actor_auxiliary`, `_combine_total_loss` and a closed policy with coefficient 0.25 and margin 1. Its negatives exclude spans overlapping present gold nonactor facets. The next recommended protocol should reuse that implementation through a new explicit actor-only ranking objective, with the same common parent, 32-update/384-row-occurrence budget, frozen 34 tensors, inactive copied rows and protected-head checks.

The sealed initial proposal in `next-experiment-gaps-v01.json` used coefficient 1 and a wider all-valid-span domain. The later [reuse audit](../implementation/reports/evidence/legal-actor-boundary-20261013-01/next-ranking-reuse-audit-v01.json) identifies these as intentional policy and arithmetic extensions, rather than a toggle of the existing implementation. It recommends reusing coefficient 0.25 and the existing domain first. The audit is a subsequent Git addendum outside the already sealed 135-file Hub specification. No ranking trial or fusion has run.

All scored references remain exposed authored engineering examples. Eight statutory examples remain unscored. This pilot does not qualify legal semantic accuracy, broader logic families, a new `lake build legal` result or genuine 8D/384D/768D latent semantics. Independent statutory references, source-context coverage and family-specific formal validation remain necessary for those claims.

## Archive and evidence

The weights and raw captures are in [the immutable Hub archive](https://huggingface.co/Publicus/legal-ir-autoencoder/tree/fa37360840c070f9318d6ad2baef87d785eac504/releases/20261013-actor-boundary-v1), with 135 new files totaling 69,977,808 bytes. Existing Hub releases are preserved. Git retains the new source, tests, recipe and compact evidence.

[Public summary](../implementation/reports/evidence/legal-actor-boundary-20261013-01/public-result-summary-v01.json), [independent result review](../implementation/reports/evidence/legal-actor-boundary-20261013-01/result-independent-review-v01.json), [freeze](../implementation/reports/evidence/legal-actor-boundary-20261013-01/actor-boundary-output-freeze-v04.json), [next measured gaps](../implementation/reports/evidence/legal-actor-boundary-20261013-01/next-experiment-gaps-v01.json) and [publication verification](../implementation/reports/evidence/legal-actor-boundary-20261013-01/hf-publication-verification-v01.json) bind the retained artifacts.

[The subsequent architecture comparison](../implementation/reports/evidence/legal-actor-boundary-20261013-01/architecture-comparison-followup-v01.json) verifies exact initial score vectors, source coordinates and decoded outputs across all 632 N7/N8 sources. Their trained branches differ by temporal presence in N7 and actor boundaries in N8. N7 improves legacy complete IR 94 to 95 but reduces older authored joint IR 51 to 49; N8 retains 94 and 51 respectively. These effects explain the architecture tradeoff. Disjoint component composition over the common frozen base is a testable future design, but decoded fields can interact through nonoverlap and abstention. Combining two separately trained 32-update branches represents 64 component updates and does not establish an equal-budget comparison. No fusion has run. This comparison is also outside the sealed Hub release.
