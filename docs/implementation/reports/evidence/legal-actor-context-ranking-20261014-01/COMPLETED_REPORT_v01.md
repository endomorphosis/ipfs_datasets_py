# Actor context ranking experiment, 14 October 2026

The fixed 32-update actor context ranking experiment completed its technical checks but failed the scientific acceptance criteria. It improves two training actor spans without improving complete-rule training accuracy, gains two complete rules on the authored development panel, and loses one previously correct older tuning rule. The candidate is archived for comparison and is not promoted as a default.

## Results

Counts below compare the F15 parent with this F16 candidate. Raw and joint are separate decoding routes. Complete IR requires every scored rule field to match; actor accuracy alone is insufficient.

| Scope | Rows | Raw complete IR, parent → candidate | Joint complete IR, parent → candidate |
|---|---:|---:|---:|
| Old tune | 96 | 94 → 93 | 94 → 93 |
| Fresh tune | 36 | 8 → 8 | 19 → 19 |
| Fresh challenge | 36 | 25 → 25 | 25 → 25 |
| Old authored evaluation | 72 | 50 → 50 | 53 → 53 |
| Authored development | 72 | 45 → 47 | 46 → 48 |
| Authored evaluation | 72 | 27 → 27 | 34 → 34 |
| Fresh development | 36 | 0 → 0 | 0 → 0 |
| Fresh test | 36 | 0 → 0 | 0 → 0 |
| Training | 168 | 154 → 154 | 154 → 154 |

Training actor exact matches increase from 156 to 158 on both routes. Both newly correct actors still accompany incorrect frozen modality, so full-rule accuracy remains 154/168. The mean filtered training hinge decreases from 0.2145724126270839 to 0.17247733615693592. These panels have been repeatedly exposed; their names do not establish blind generalization.

The scientific gate required at least 155/168 complete training rules on both routes, no complete-rule loss IDs across all nine scopes against either F15 or N11, and retention of all 32 tracked permission modality decisions. The first two criteria fail. `native-tuning-calendula-t4-q5-p` loses actor and complete-rule correctness on both routes against both comparators. All 32 permission modality decisions remain P without abstention; this does not establish retention of all 32 complete permission rules.

The 14 remaining joint training errors comprise five actor-only, one actor-and-exception, two condition-only, two modality-only, and four modality-and-actor cases. Actor-only training cannot repair the six wrong modality decisions, the exception-presence problem, or the two condition boundary errors. Category counts overlap where stated.

## What actually ran

`SpanActorContextRankingAdapterDecoder` starts from F15, copies 42 tensors, freezes 36 nonactor tensors, and trains six actor tensors with 258 active scalars out of 908 stored scalars. The original main loss `(2 * modality_CE + six facet means) / 8` is retained, with `0.25 * mean(ReLU(1 + wrong_actor_score - gold_actor_score))` added. The span domain is bounded at 128 tokens; exact gold actors and candidates overlapping present gold nonactor spans are excluded from the ranking negatives.

One fresh Adam run uses 32 updates, batch size 12, seed/order 1729, learning rate 0.001, betas 0.9/0.999, epsilon 1e-8, zero weight decay, `foreach=False`, and gradient clipping at 5. Latent input is disabled. The configured dimension 384 is a placeholder, not evidence of active latent decoding. There was no retry, search, or second model run after scoring.

The qualified child reports 1,312 model forwards: 1,280 inference and 32 training forwards. Six F15 captures containing 240 rows were reused with zero new parent forwards. All 632 initial full heads and decoded outputs match F15. At the final state, modality, all presence heads, and nonactor boundary score vectors remain bit equal across 632 sources. Joint decoding can still change a field because actor selection participates in joint constraints; score equality alone is not a full-rule retention proof.

The 62 frozen result files total 71,147,530 bytes. Primary analysis, a separate recount, and independent result review agree. The declared model roster contains 40 modules plus one supplemental attention source; 17 model modules were actually loaded. Runtime and terminal checks passed, the experiment's lease is absent, its claim is released, and all 542 preceding records are preserved. Final experiment charge is 71,459,330 bytes. Sampled model-process-group peak RSS was 804,515,840 bytes; model-phase wall time was 175.48282306396868 seconds. These are sampled process measurements, not an absolute peak, isolated fitting duration, or kernel memory quota.

The earlier failed resource import smoke and the successful corrected smoke are retained separately. The frozen native resource snapshot belongs to this completed run. Newer upstream scheduler changes are preserved during integration, without claiming the old run exercised the new scheduler.

## Published checkpoint and evidence

The [immutable Hugging Face release](https://huggingface.co/Publicus/legal-ir-autoencoder/tree/f5bebab6d6a75c2e4cd1ed1fa09eb3481e1dcd14/releases/20261014-actor-context-ranking-v1) contains 201 new files totaling 81,437,344 bytes. All 201 files were forcibly downloaded at that revision and compared byte for byte, including the opaque checkpoint. All 5,646 pre-release file identities are preserved in the final 5,847-path repository map.

Checkpoint: 15,143,581 bytes, SHA-256 `5bb6425888b4cffe5c9875b5d262b2895c8c02e4745acd231f33c4a79908ff84`. Child-reported model-state SHA-256: `12567c93c427c33bb2904ed71992d2c870dc9b70c79a7efbea36c355e654ff10`. Publication verification hashes checkpoint bytes; it does not parse the checkpoint or independently recompute tensor values.

The first upload stopped after creating chunk 3 because Hugging Face appended one checkpoint LFS rule to `.gitattributes`. The original strict failure is retained. Independent observation established that this was the only changed old file and that the first 20 new payload identities were exact. A separately reviewed finite resume restored the exact baseline attributes, preserved those 20 files, and uploaded only original chunks 4–9. No original chunk was retried. Every remaining commit passed prior-identity and new-byte checks before the final forced readback. The overall protocol includes the explicit attributes correction; payload operations remain additions only. Git clone LFS materialization and isolated numerical reload are not qualified by this readback.

The public source capsule includes bounded source, control results, failed and successful checks, runtime metadata, result analysis, recount, and independent reviews. Raw checkpoints, model captures, reference bodies, and private resource bodies remain outside the Git source capsule. Actual source and root merge identities are recorded separately after exact-head review.

## Integration and remaining work

Integration starts with source main `904f885c180eb9dfcdef80199f708125428d3859` and retains both published F16 draft commits through `54aae1d13faea237eddde301754db85afd1e127a`. Root intake starts at `dd528f888484f47b9665c2a5d1477d2a4dec7e0b`. At the reviewed branch census, 37 of 38 selected published source heads were already ancestors of source main; the only remaining head was this phase's own draft. All 29 selected root heads were already integrated. This is a finite public-head census, not an audit of unpublished worktrees or private branches. Saved historical recovery identities and the newer accelerator pointer are retained. A separate owned integration clone keeps the original training checkout and all frozen raw source-path pins intact.

The next-training design is a proposal, not an implemented or measured improvement. It starts from F15 and would train the actor, modality, condition boundary, and exception-presence readouts together, with a masked F15 teacher term only for training components that F15 already gets right. It requires an explicitly differentiable readout route because changing `requires_grad` alone does not overcome current `no_grad` projections and merge operations. The proposed 14 tensors have 713 active scalars out of 2,403 stored; 28 tensors stay frozen. A future qualified run must preserve the exact loss normalization, masks, teacher provenance, fixed recipe, and all-scope retention checks, including the two F16 development gains as an additional diagnostic. No extra training was performed in this phase.

Real US Code semantic fidelity remains unmeasured here. The eight statutory pilot items are unscored. The user-supplied `justicedao/open-us-law-span-cache` is a reference source, not evidence of independent human adjudication. The useful next fidelity step is candidate-blind review of the existing statutory items, with edition, governing context, definitions, cross-references, seven-field annotations, and explicit unresolved or unsupported cases retained. A frozen source alignment receipt still reports 418 pending review units, zero review receipts, zero accepted graphs, and governing context not closed; that receipt is not a live census of all work.

This phase executes no `lake build legal` and qualifies no additional logic family. A separate earlier scope-family phase records a successful native build of 14 modules for 12 requests, including nine ground TDFOL views and three qualifier-free DCEC views; it does not establish statutory semantic truth. Newer modal and temporal compiler work is preserved with its declared scope and limits. Build validity, source fidelity, and supported logic-family semantics remain separate gates.

There is no matched semantic evaluation of genuine 8D, 384D, and 768D latent decoders in this experiment. Such a comparison needs reviewed section-grouped data and matched source-only, latent-only, combined, and ablation controls. The low exposed fresh-panel counts remain a material limitation. Hosted CI status must be reported from its actual observations; local qualified checks do not establish a hosted CI pass.
