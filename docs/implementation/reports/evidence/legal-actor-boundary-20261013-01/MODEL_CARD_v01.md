---
language:
- en
tags:
- legal-ir
- autoformalization
- experimental
---

# LegalIR actor boundary pilot, 2026-10-13

This experimental checkpoint completed 32 actor-only updates. Complete authored training IR remained **153/168** and actor accuracy remained **155/168**. One previously exposed authored evaluation panel improved from **32/72 to 33/72** complete joint IR. Fresh development and test complete IR remained **0/36** each. The checkpoint is archived for reproducibility; it is not selected or promoted to the default decoder.

## Architecture and training

`SpanActorBoundaryAdapterDecoder` starts from the common N4 split-feature checkpoint, rather than the trained N7 attention candidate. The original 34 tensors are frozen. Four copied pointer tensors store 780 scalars, with only the actor start/end row active (130 scalars). The other five copied rows remain unchanged with zero gradients and Adam moments. All presence, modality and other-role pointer outputs retain the parent's exact binary32 values on the measured 632 sources.

Training uses the same 168 authored examples, fresh Adam, learning rate 0.001, batch size 12, seed/order seed 1729 and 32 updates. The actor ranking term is disabled. Latent conditioning is disabled; the configured 384D vectors are dormant placeholders. There are no external encoder calls. This does not train or qualify genuine 8D, 384D or 768D latent decoding.

## Measurements

| Exposed authored measure | Initial | Trained |
|---|---:|---:|
| Training complete IR, raw and joint |153/168|153/168|
| Training actor exact, raw and joint |155/168|155/168|
| Training gold actor top1 |156/168|156/168|
| Training gold actor top8 |168/168|168/168|
| Authored evaluation complete joint IR |32/72|33/72|
| Authored evaluation joint actor exact |60/72|63/72|
| Older authored evaluation joint actor exact |59/72|61/72|
| Legacy complete IR, raw and joint |94/96|94/96|
| Fresh development complete joint IR |0/36|0/36|
| Fresh test complete joint IR |0/36|0/36|

Complete IR compares all seven fields, including modality. Legacy 94/96 reflects two temporal-field mismatches; legacy actor and modality accuracy are both 96/96 and all 32 permission cases retain P. Training joint modality remains 161/168, including one abstention. Six selected modality errors overlap actor errors. All 15 training complete-IR failures persist.

Five training gold actor ranks improve, with rank sum 215 to 206, while top1/top8 coverage stays fixed. All 168 gold actor spans were already retained in top8. Complete gold assignments survive the retained candidate domain for 160/168 training rows, but 0/36 on each fresh panel. Actor ranking, fixed-head errors and fresh candidate coverage are distinct remaining gaps; increasing the actor candidate limit alone does not address them.

## Evidence and accounting

[The checkpoint](cells/actor-boundary-ce/results/cell-checkpoint.json) is JSON, 6,450,800 bytes, SHA256 `14aad029259bb52d58ea56e320306590546c58c3e4e4a8b568f8982e2a9252d7`. The source and contract tests are included under `source/`; the recipe and public evidence are included separately. Source hashes are part of the checkpoint's implementation contract, so use the matching source versions.

The successful attempt has 1,520 inference forwards plus 32 training batch forwards, 384 training row occurrences and 1,904 total source occurrences. Initial complete-head parity and final protected-head parity each pass on 632 sources. All 62 outputs were frozen before reference scoring, totaling 61,920,310 bytes. Independent direct recount agrees with the qualified analyzer. The first attempt failed before model loading, inference or updates; its retained claim and failure evidence are preserved. Postrun audit corrections did not rerun the model.

## Scope

All scored references are previously exposed authored engineering diagnostics, not independently reviewed statutory gold. Eight statutory source examples remain unscored. This release establishes neither legal semantic accuracy, broader logic-family compliance, a new `lake build legal` result nor genuine latent semantics. It makes no blind generalization claim. Further work should compare an explicit actor span ranking objective under the same bounded budget and separately address modality, presence, source context and formal compiler validation.
