# Actor refinement with the learned conditions head frozen

This experimental checkpoint continues the trained N11 LegalIR decoder for 32 updates. It copies all 42 tensors, freezes the 36 nonactor tensors including all rows of the learned conditions head, and trains six actor projection, query and context-gate tensors (258 active scalars). Fresh Adam uses learning rate 0.001, batch size 12 and seed 1729. Actor ranking is disabled.

| Exposed authored scope | Parent raw → candidate raw | Parent joint → candidate joint |
| --- | --- | --- |
| Training, 168 rows | 154 → 154 | 154 → 154 |
| Older authored evaluation, 72 rows | 48 → 50 | 51 → 53 |
| Authored development, 72 rows | 45 → 45 | 46 → 46 |
| Newer authored evaluation, 72 rows | 27 → 27 | 33 → 34 |
| Fresh development, 36 rows | 0 → 0 | 0 → 0 |
| Fresh test, 36 rows | 0 → 0 | 0 → 0 |

Independent recount found zero complete-IR loss IDs across all nine scored scopes and retained all 32 permission cases. The fixed success criterion required at least 155/168 on both training routes, so **scientific success is false** and no default model is promoted. These repeatedly exposed authored diagnostics do not establish blind generalization or statutory semantic accuracy.

All 632 initial outputs matched N11 before any update. After training, all modality, four presence and nonactor boundary scores remained bit-equal across the same 632 sources. Query and gate values changed on all 32 updates. There were 1,280 inference forwards and 32 training forwards, covering 1,664 source occurrences; copied parent captures added no forwards. All 62 outputs were frozen before scoring.

The checkpoint is 12,230,969 bytes, SHA-256 `f421514dc02cb3542e7587767191aa99bd32551f145e0af4d01c47595d4d73c4`. The release includes all 40 raw algorithm files in package-relative paths, contract tests, recipes and actual evaluation evidence. The decoder class is `SpanActorRefinementAdapterDecoder` in `source/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_actor_refinement.py`.

This run uses disabled latent conditioning with 384-dimensional placeholders. Genuine 8D/384D/768D latent semantics, broader logic-family qualification, independently reviewed US Code semantic gold, isolated archive numerical reload and `lake build legal` remain unqualified. The eight statutory source examples are unscored.

Older completed results have a separate lossless recovery archive at immutable HF revision `0228887c8e33cb23e9679889a9496f87140021e6`, prefix `archives/20261014-owned-released-results-v1`. It preserves 1,162 exact files, including historical checkpoints, and was independently restored and verified before local archival. No model tensor codec was changed.
