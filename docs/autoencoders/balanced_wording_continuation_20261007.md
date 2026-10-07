# Native 384D wording continuation: measured retention failure

The controlled continuation completed, including native source preparation, two matched fits and sixteen greedy evaluation panels. Replacing the existing normative auxiliary bank with the reviewed balanced bank reduced reconstruction fidelity. Continuing on the existing bank retained both wording banks and improved previously exposed development paragraphs from 31 to 33 exact reconstructions out of 48. Neither result is a fresh semantic holdout or a production qualification.

## Actual formula reconstruction

Each cohort contains 48 paragraphs and 180 rules. These are complete greedy outputs at temperature zero, compared by rule order and all seven formal facets. The parent already reconstructed the new bank perfectly before training.

| Weights | Original TRAIN | Retained normative TRAIN | New balanced TRAIN | Exposed development v3 |
| --- | ---: | ---: | ---: | ---: |
| Published numerical parent | 48/48 | 48/48 | 48/48 | 31/48 |
| Existing-bank continuation | 48/48 | 48/48 | 48/48 | 33/48 |
| Balanced-bank replacement | 48/48 | 33/48 | 48/48 | 19/48 |

Selected and last-attempt weights are identical within each arm. All sixteen physical panels were still generated and saved, so their repeated results are aliases of the same weights rather than independent fits. The original nine diagnostic panels were also retained at both endpoints for both arms: 36 physical training panels.

Each of the sixteen cohort-evaluation panels emitted 180 schema-valid rules, reached EOS in all 48 paragraphs, and had no cardinality or ordinal ordering errors. This statement excludes the original intervention panels, whose outputs can lose cardinality. These facts do not establish meaning preservation. The balanced arm changed 19 modalities on retained wording, leaving 161/180 correct. Ten were already wrong in the source-only head; another nine had a correct source head but a wrong combined decoder output. Its exposed-development outputs had 140/180 correct modalities and 179/180 correct actions, with 41 substituted whole rules. The existing-bank continuation had 161/180 correct development modalities and 179/180 actions, with 20 substituted rules. Missing and extra whole rules are counted separately, including substitutions.

The source-only clause bank tells the same retention story, but has a different denominator and must not be substituted for emitted formulas. The new bank was already 720/720 correct at the parent. Replacement lowered its modality cross-entropy to approximately 0.0000937 while reducing retained-bank source modality accuracy to 170/180; the ten errors changed obligations into permissions. Confidence on an already-correct bank increased while retained behavior deteriorated. The original retained-bank action-head error remains in both arms, although recurrent contributions repair it in the retained full formulas.

The [sampled outputs](evidence/balanced-wording-20261007/sampled-outputs.json) preserve complete reference and generated IR documents from both arms for three authored paragraphs. They include a retained-wording regression and a development error; they are illustrations of the measured outputs, not independently reviewed law or a substitute for complete cohort rates.

## Matched training and timings

Both arms used the same parent tensors, seed 1729, 170 original-rule/template draws, original decoder stream and checkpoint selection, and inherited losses. Each received 1,020 wording auxiliary presentations at weight 0.05. The optimizer and scheduler started fresh; this was a weight continuation, not an Adam-state resume. Exposed development and sealed labels were never fit inputs or selectors.

| Phase | Measured model/driver time | Guardian wall time |
| --- | ---: | ---: |
| Native preparation: 216 unique source strings | 7.269 s encoder / 7.687 s driver | 45.440 s |
| Successful preflight | 25.760 s driver | 64.819 s |
| Both fits and inherited panels | 151.618 s driver | 187.307 s |
| Sixteen postfit panels | 36.880 s driver | 71.187 s |

The existing-bank fit took 38.261 s, or 31.886 original training row presentations/s. The balanced-bank fit took 38.546 s, or 31.650/s. These counts exclude auxiliary presentations from the throughput numerator. Greedy generation with cached vectors took 9.461–10.903 ms per paragraph across selected panels, in batches of eight. This timing excludes encoder, compiler, bridge, prover and posthoc scoring work. No throughput improvement over a historical baseline is claimed.

Measurement settings were CPU only, one worker, bridge names `[]`, external prover evaluation false, metric disk cache disabled, and warm prepared source-vector caches. OS page-cache warmth was uncontrolled. There was no bridge-on legal-IR evaluation or target-count timing in this experiment.

Native preparation used the existing local verified gte-small384 assets with CPU float32, batch four, and the unchanged 512-token encoder ceiling. No weights were downloaded. Original 384D paragraph/context vectors have authenticated caller bytes but lack saved encoder-producer receipts; existing normative and new balanced vectors have actual producer evidence. The experiment preserves this provenance difference.

The owned leases and process groups were released after each successful phase. Largest periodically sampled RSS was 1,147,809,792 bytes during training and 811,638,784 during evaluation, below the 1,536 MiB admission limit; these are sampled maxima, not measured peaks. Training retained 151,900,366 bytes within its 400 MB reservation; evaluation retained 51,549,459 within 100 MB. The final evaluation inventory charged 142,506,944,422 bytes to the existing 145 GB campaign cap across its named roots. No cap was raised in this experiment.

## Repairs and remaining boundaries

Before the successful runs, independent source review caught a profile variable shadowed by a renderer module. A preflight then refused an incomplete renderer interface, and the first training attempt refused a missing authenticated parent-report input. The fixes restored the full renderer owner and added 28 recursive parent references to the phase manifest. Failed attempts, source versions and cleanup receipts remain preserved. The successful fits used the same frozen numerical source and matched profiles; failed attempts made no optimizer updates.

Independent stdlib audits checked native-vector bindings, all source-bank readouts, typed state hashes, complete formula denominators, full 32-token distributions, original TRAIN output parity, prediction durability and owned cleanup. The postfit audit covers 768 physical paragraph outputs, 2,880 reference rules and 11,520 scalar sites. Generation traces were saved before this evaluator explicitly parsed v3 references, but the frozen initializer retains historical metadata access and the cohort was previously exposed. There is no blinding claim.

The inherited numerical runtime explicitly imports a frozen historical tree and uses `legal_formula_codec._rule` for schema validation. It does not execute the current canonical compiler, parser or decompiler. Compiler-facing measurements must independently use the workspace tree and `require_workspace_logic_tree()`. Only an actual `lake build <Lib>` is a Lean admit. This experiment executed no Lake builds, native logic-family validation, checkpoint promotion, Hugging Face upload or Constitution formalization.

The 8D linguistic teacher and the 768D/4096D lineages remain separate and unchanged. The 32-token authored codec covers only empty conditions, exceptions and temporal qualifiers in this lane. Nonempty qualifier coverage, reviewed natural-law spans, family projections and fresh holdout reconstruction remain separate open work.

## Next retention experiment

Reject the balanced replacement as a reconstruction candidate. Keep the existing-bank continuation as numerical development evidence only. Its two additional exact development paragraphs do not prove generalization or global convergence.

The next bounded comparison should replay both authenticated wording banks while retaining original decoder supervision. Alternating banks must advance a bank-local draw ordinal: using the global step modulo 30 would cover only half the members in each stratum. A 170-update schedule can provide 85 updates and 510 presentations per bank, covering every one of its 180 clauses two or three times. Per-bank receipts and exposure ledgers must be explicit; a single-bank receipt cannot describe this training.

Candidate selection must check complete original and retained wording reconstructions, including modalities, omissions, extras, EOS and every facet, before accepting a numerical continuation. Exposed development remains posthoc only. Lower learning rates and retained-bank distillation losses are alternatives to compare after bounded replay is wired and measured. The new schedule and retention helper are preparation for that fit, not evidence that it has run or improved reconstruction.

## Integration with parallel contributions

The same day's published [retained-cache runtime](https://github.com/endomorphosis/ipfs_datasets_py/blob/main/docs/autoencoders/normative_cached_legal_ir_runtime.md) supplies an explicit, read-only inference contract for the existing selected 384D/768D states. Its four-state replay establishes parity with archived predictions; it does not fit the two continuations measured here. A future consumer needs explicit new checkpoint, recipe and source bindings rather than silently treating these states as already admitted by that contract.

The separate [source-span decoder pilot](https://github.com/endomorphosis/ipfs_datasets_py/blob/main/docs/implementation/legal_scope_span_decoder_pilot_20261007.md) learns raw-source support, modality and occurrence pointers. It retains a different architecture, corpus and unresolved meaning/context boundaries. Its reported 12/64 exact positive proposals are not pooled with this experiment's paragraph counts. Both contributions are preserved on main. This continuation adds reconstruction evidence and replay preparation without replacing either owner or promoting a default model.

## Reproduction and retained source material

The [evidence index](evidence/balanced-wording-20261007/evidence-index.json) binds the compact reports to the [immutable experiment archive](https://github.com/endomorphosis/lift_coding/blob/main/artifacts/autoencoder-balanced-wording-20261007/balanced-wording-evidence.tar.gz). It preserves all generated formulas, readout traces, failed attempts and producer sources. Raw checkpoints and prepared embedding inventories remain in the owned local attempts; reconstructed vectors and normalized feature observations are retained as numerical outputs.

The standalone [replay preparation helper](../../scripts/ops/autoencoder/dual_bank_wording_replay/dual_bank_retention.py) exports `build_schedule`, `validate_schedule` and `retention_gate`. Its sibling tests cover budget conservation, full coverage, malformed receipts and complete formula retention. It neither invokes nor modifies a trainer. The proposed fit still needs a reviewed dual-cache adapter and truthful per-bank training receipts.

The [main/worktree reconciliation](https://github.com/endomorphosis/lift_coding/blob/main/artifacts/autoencoder-balanced-wording-20261007/publication/final-main-worktree-reconciliation.md) also records older local-only tips and remaining provenance review. Their experimental cards and source material remain separate from live model owners; archived findings are not a runtime port or checkpoint promotion. Existing upstream cached-inference and source-span-decoder contributions are preserved by building this commit on current main.

The additive [dual-bank trainer adapter](dual_bank_wording_training_adapter.md)
now provides separately validated caches, bank-local dispatch and reconciled
per-bank training receipts. Its retained-parent forward probe executed no
optimizer updates; the new matched retention fit remains a separate experiment.
