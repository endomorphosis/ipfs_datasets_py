**F18 modality and conditions retention — completed training, failed acceptance (2026-10-15).**

`SpanModalityConditionsRetentionAdapterDecoder` continues from the exact trained F15 parent. It trains six modality/conditions tensors with 325 active scalars, freezes 36 tensors, and preserves every actor and presence parameter. Complete training IR remains **154/168 on both greedy and joint routes**, below the fixed minimum of 155. Technical checks passed within the scope below; scientific success, the separate parent-ablation signal and default promotion are **false**.

The fixed recipe uses fresh ordered Adam, seed 1729, batch size 12, learning rate 0.001 and 32 updates. Two conditions-only errors identified from the frozen F15 training predictions receive weight 2 over their entire conditions facet. Other rows have weight 1. The objective preserves modality coefficient 2, full-batch mean normalization, outer denominator 8 and six-component teacher-correct KL at temperature/coefficient 1 with denominator 6B. Actor ranking is disabled. Evaluation predictions do not determine training masks.

Complete IR includes modality and all six roles; an abstention is a nonmatch. These are previously exposed authored engineering diagnostics.

| Scope | Rows | F15 → F18 greedy complete IR | F15 → F18 joint complete IR |
| --- | ---: | ---: | ---: |
| training168 | 168 | 154 → 154 | 154 → 154 |
| old_tune | 96 | 94 → 94 | 94 → 94 |
| fresh_tune | 36 | 8 → 8 | 19 → 20 |
| fresh_challenge | 36 | 25 → 26 | 25 → 26 |
| old_authored_eval | 72 | 50 → 51 | 53 → 54 |
| authored_dev | 72 | 45 → 45 | 46 → 46 |
| authored_eval | 72 | 27 → 27 | 34 → 34 |
| fresh_dev | 36 | 0 → 0 | 0 → 0 |
| fresh_test | 36 | 0 → 0 | 0 → 0 |

Training modality exactness improves 161→162 greedy and 162→163 joint. Actor remains 156 on each route; conditions remain 165 greedy and 166 joint. Neither targeted conditions error is repaired: the selected span still stops after a quoted application name, omitting the remainder of the conditions clause. Every other field is correct on those two examples. This observation does not establish a representation-capacity or optimization cause.

No complete-rule correct ID is lost relative to F15 or N11 across the nine scored scopes. Relative to F16, two authored-dev actor-duration-name IDs are missing on both routes. Relative to F17, those two IDs plus one fresh-tune object-duration-title ID and one old-authored-eval object-duration-title ID are missing on both routes. Gains elsewhere do not cancel these loss-ID vetoes. All 32 protected permission modalities remain correct without abstention; that is a modality guard, not a claim that every permission rule is complete.

Raw abstentions change 24→23 on fresh_tune, 3→4 on fresh_challenge and 11→13 on authored_dev. Training retains one raw abstention. Complete-rule retention can therefore hold against F15 while additional already-incorrect examples abstain. Both fresh_dev and fresh_test remain 0/36 complete IR on both routes.

Primary analysis and a separately authored counter agree across 60 panels, 54 scored sets and 36 comparator/scope groups. Initial full-head parity and final frozen actor/all-presence/other-boundary checks cover 632 sources. A separate recorded arithmetic check covers 384 CE rows, 2,304 KL components and 384 modality CE checks from logged candidate logits. Nonmodality CE logits were not completely logged; complete CE-kernel verification, independent autograd/Adam replay and numerical checkpoint reload are unqualified. The two scorers share disclosed coordinate/greedy/joint AST definitions; the counter and training168 audit share an author. Full codec/grammar semantics are not independently requalified.

One training attempt completed. There were 32 experimental updates and one separate synthetic fixture Adam step, 1,312 experimental forwards plus one fixture forward, and 1,664 experimental source occurrences plus two fixture occurrences. The 62 frozen result files total 80,553,403 bytes. Metadata-checker refusals and corrected source versions are retained; they did not trigger retraining or change frozen outputs.

The checkpoint is 21,058,430 bytes with SHA256 `90031d084f2d86cf860c5fc95d2dae374dc254adec70bd85a90893f98c5a1555`. Its bytes are opaque to the post-training reviewers. Portable numerical reload is not established.

The terminal resource sample preserves all 549 opening ledger bodies, adds only the successful released 200 MB claim, and observes its scheduler lease absent. Observed apparent bytes plus full nonreleased reservations and a separate 200 MB future allowance total 134,569,257,120 bytes against the unchanged 145,000,000,000-byte cap. This is sampled accounting; it approves no foreign release or continuous resource witness.

Latent conditioning remained disabled with a 384D placeholder and zero external encoder calls. F18 qualifies no active 8D/384D/768D comparison, independently reviewed US Code meaning, new logic family, fresh `lake build legal`, or portable numerical reload. Eight statutory sources remain unscored.

The next proposal separates saved-head composition from conditions-end ranking diagnostics and a possible conditions-context adapter. F17 actor features and F18 modality/conditions readouts have disjoint downstream source paths, but checkpoint lineage/policy metadata is not drop-in compatible and joint selection can couple fields. A new donor-bound validator, exact zero-residual arithmetic and fresh guarded captures are required before any composed model can be claimed. No composition or additional training has occurred.

This single-rule continuation complements the separate grouped v1/v2 and existing latent-decoder efforts in the [inference and qualification guide](../autoencoders/inference_and_qualification.md). Those implementations and their checkpoints are preserved.

Implementation: [decoder](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_modality_conditions_retention.py), [contract tests](../../tests/unit/optimizers/logic_theorem_optimizer/test_legal_span_modality_conditions_retention_contracts.py). Evidence: [public summary](evidence/legal-modality-conditions-retention-20261015/public-result-summary-v01.json), [independent result review](evidence/legal-modality-conditions-retention-20261015/modality-conditions-retention-result-independent-review-v01.json), [conditions-error observation](evidence/legal-modality-conditions-retention-20261015/postfreeze-conditions-error-observation-v01.json), [proposal frozen before the counter completed](evidence/legal-modality-conditions-retention-20261015/next-experiment-proposal-v01.json).

The diagnostic release is published at [immutable Hugging Face revision c9cce458](https://huggingface.co/Publicus/legal-ir-autoencoder/tree/c9cce4586dd96518088662fb12831173e98e36cc/releases/20261015-modality-conditions-retention-v1): **395 files, 105,151,374 bytes**. A forced immutable Hub CLI download matched every original payload hash, including the checkpoint. The final repository has 6,471 paths. All 6,076 postattributes identities remain exact; relative to the original baseline, the sole prior-file change is the explicitly planned 155-byte checkpoint-specific `.gitattributes` appendix, and the other 6,075 identities remain exact. Payload operations are additive; the overall protocol includes that declared attributes change.

The first payload request stopped on an SSL connection closure after the attributes commit. A separate read-only three-query reconciliation proved all 18 requested files absent at the exact postattributes revision. The separately qualified resume uploaded the same frozen payload in 42 groups, targeting 4 MiB and at most 16 files per group, with larger bounded files as singletons. It did not repeat the attributes operation or rerun the original publisher. Failure, reconciliation and resume receipts are retained. Byte-exact download verification establishes archive custody; numerical reload, automatic Git LFS materialization and semantic accuracy remain unqualified.

Publication evidence: [independent completion review](evidence/legal-modality-conditions-retention-20261015/hf-publication-completion-independent-review-v01.json), [release manifest](evidence/legal-modality-conditions-retention-20261015/release-manifest-v01.json), [successful cold resume invocation](evidence/legal-modality-conditions-retention-20261015/hf-action-resume-invocation-v01.json).
