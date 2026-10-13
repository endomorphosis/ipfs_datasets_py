# Temporal presence routing diagnostic, 2026-10-13

Copying the retained parent's temporal-presence scores into the split-feature decoder's saved outputs restores both legacy regressions, but loses newer authored successes. The route remains an opt-in diagnostic. No trained checkpoint or default decoder changed.

| Saved-score readout | Legacy greedy / joint | Authored development greedy / joint | Authored evaluation greedy / joint |
| --- | --- | --- | --- |
| Trained split features | 94 / 94 of 96 | 44 / 45 of 72 | 26 / 32 of 72 |
| Parent temporal presence, learned boundaries | 96 / 96 of 96 | 34 / 35 of 72 | 24 / 30 of 72 |
| All parent optional presence, learned boundaries | 96 / 96 of 96 | 18 / 19 of 72 | 21 / 27 of 72 |

The two legacy errors are `native-tuning-calendula-t6-q7-o` and `native-tuning-calendula-t6-q7-p`. Their learned temporal pointers still select the correct date-bearing text, but temporal presence flips to absent. Across all 392 sources, 56 parent/trained temporal argmax disagreements run from parent-present to trained-absent. Many newer disagreements concern duration-bearing conditions, exceptions, or names that should not become temporal deadlines. Restoring parent temporal presence raises development temporal false positives from 3 to 17 and evaluation false positives from 0 to 8. The evaluation's three trained temporal false negatives disappear, but whole-rule joint correctness falls by two.

The experiment uses four fixed variants on all seven original panels, replays the exact original greedy and joint decisions, and retains every trained start/end and modality score in both routed variants. Joint selection remains top-K 8 with a 50,000-node budget. Adding a temporal constraint can still change selected spans or cause abstention; unchanged boundary scores do not guarantee unchanged decoded spans. All 32 legacy permissions remain P, with no permission abstentions or P-to-O/F changes. Legacy 96/96 is necessary for retention and is insufficient for promotion.

## Opt-in API

`ipfs_datasets_py.logic.legal_ir.presence_routing.compose_presence_scores` validates both complete score packets against the exact source text, requires matching occurrence IDs and source hashes, and returns detached composed scores with component provenance. Its default copies only the two temporal-presence logits. It never opens a checkpoint, runs a model, or changes the joint decoder's rules. Pass `result["occurrence"]["scores"]` explicitly to the existing `select_joint_spans`; no automatic routing is installed.

The helper validates score/source compatibility. It does not authenticate the scores as outputs of a particular model; callers retain responsibility for immutable checkpoint and capture provenance. This diagnostic uses the independently reviewed, immutable N4 captures.

## Evidence and next training comparison

The workspace contribution `artifacts/legal-temporal-presence-20261013-01/` retains the fixed experiment plan, executable analyzer, compact summary, independent replay receipt, and a concrete temporal-head training proposal. The full local analysis is 5,157,031 bytes with SHA256 `284040c26ed56e3dbff94e88108d9635d49344a48be794cf7b53e1684f7d9226`; the compact summary retains its identity and every panel count and matched recovery/regression ID. Raw captures and existing weights remain in the [immutable N4 Hugging Face release](https://huggingface.co/Publicus/legal-ir-autoencoder/tree/70525bcf70e801e78f4882b4834494d67ec0d2b6/releases/20261013-split-feature-v1).

The next comparison should train a separate temporal-presence head on authenticated training rows while freezing learned features, all boundary heads, modality, and other presence outputs. Compare temporal cross-entropy with the same cross-entropy plus a balanced signed-margin objective. This can isolate presence repair without putting the learned boundaries at risk. The proposal is not executed by this diagnostic, and no new model is selected or published.

All 384 reference targets were previously exposed and share authored templates. Eight law-source rows remain unreviewed and unscored. These results do not establish independent US Code accuracy, genuine 8D/384D/768D conditioning, broader logic-family qualification, or a `lake build legal` result. There were zero new optimizer updates, model/encoder/compiler calls, checkpoint JSON parses, or numerical imports in the analyzer.
