# Actor context ranking: completed negative experiment

This checkpoint continues the trained F15 LegalIR decoder for 32 updates, adding a filtered actor-span ranking hinge to the actor cross-entropy objective. It copies all 42 tensors, freezes 36 nonactor tensors, and trains six actor projection, attention-query and context-gate tensors with 258 active scalars. Fresh Adam uses learning rate 0.001, batch size 12 and seed 1729; the hinge has weight 0.25 and margin 1.

| Exposed authored scope | F15 raw → candidate raw | F15 joint → candidate joint |
| --- | --- | --- |
| Training, 168 rows | 154 → 154 | 154 → 154 |
| Older tuning, 96 rows | 94 → 93 | 94 → 93 |
| Older evaluation, 72 rows | 50 → 50 | 53 → 53 |
| Newer evaluation, 72 rows | 27 → 27 | 34 → 34 |
| Fresh development, 36 rows | 0 → 0 | 0 → 0 |
| Fresh test, 36 rows | 0 → 0 | 0 → 0 |

Training actor accuracy increased from 156/168 to 158/168 on both routes. The two additional correct actors occur on rows whose frozen modality is still wrong, so complete-rule accuracy did not improve. The older tuning item `native-tuning-calendula-t4-q5-p` lost complete-rule correctness on both routes relative to both F15 and N11. All 32 tracked permission modality decisions remained P without abstention; that does not mean all 32 complete rules were preserved.

The fixed acceptance criterion required at least 155/168 complete rules on both training routes, zero complete-rule loss IDs against both comparators across nine scored scopes, and permission-modality retention. **Scientific success is false; this checkpoint is not promoted.** Both scoring implementations agree. These repeatedly exposed authored diagnostics do not establish blind generalization or statutory semantic accuracy.

The initial full heads and decoded outputs matched F15 across 632 sources before update zero. Final modality, all four presence pairs and nonactor boundary scores remained bit-equal across those sources. The run made 1,312 model forwards over 1,664 source occurrences; six copied parent captures added no forwards. All 62 outputs were frozen before scoring.

The checkpoint is 15,143,581 bytes, SHA-256 `5bb6425888b4cffe5c9875b5d262b2895c8c02e4745acd231f33c4a79908ff84`; its model-state hash is `12567c93c427c33bb2904ed71992d2c870dc9b70c79a7efbea36c355e654ff10`. The release inventories 40 admitted model modules plus one separately pinned attention source, contract tests, recipes, the resource-source snapshot and actual evaluation evidence. The decoder class is `SpanActorContextRankingAdapterDecoder` in `source/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_actor_context_ranking.py`.

Latent conditioning was disabled with 384-dimensional placeholders. This run does not qualify genuine 8D/384D/768D latent semantics, broader logic families, isolated numerical reload, statutory semantic correctness or `lake build legal`. Its eight statutory examples remain unscored. A previous, separate scope-family phase recorded a limited successful native build; it supplies no statutory semantic labels for this experiment.

The new ranking objective reduced the training mean filtered hinge from approximately 0.2146 to 0.1725 without increasing complete-rule accuracy. Follow-on work should distinguish remaining actor errors from frozen modality, presence and condition-boundary errors, preserve earlier correct rules, and evaluate independently reviewed statutory meaning with complete governing context.
