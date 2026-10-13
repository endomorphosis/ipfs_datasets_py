---
language: en
tags:
- legal
- formalization
- experimental
- pytorch
---
# LegalIR temporal attention experiment (2026-10-13)

One opt-in source text temporal attention adapter, archived as an experimental result. It did not pass the preregistered selection gates and is not the default decoder.

The original 34 parameter tensors are frozen. A 64-scalar query and an 8-by128 temporal head plus bias are the three trainable tensors (1096 stored scalars; 322 active). Only temporal head rows 6:8 train. The model combines mean pooling and masked attention over the existing span features, with no new encoder. It starts exactly equivalent to the N4 split-feature parent, then receives 32 fresh Adam updates on the same 168 authored training examples, seed 1729, batch 12, learning rate 0.001.

| Authored engineering measure | Historical N6 CE | Attention |
|---|---:|---:|
| Legacy complete IR, greedy and joint |95/96|95/96|
| Fresh development temporal presence |25/36|25/36|
| Fresh test temporal presence |19/36|19/36|
| Fresh development complete joint IR |0/36|0/36|
| Fresh test complete joint IR |0/36|0/36|
| Older authored evaluation complete joint IR |50/72|49/72|

Training temporal presence is 168/168 both before and after training; complete training IR is 153/168 before and after. The initial training baseline prevents treating that perfect temporal score as a new gain. Learned versus uniform attention changes no temporal-correct or complete-IR outcomes on legacy 96 plus fresh 72. The query changes numerical scores; this control does not identify causal training effects.

All 632 initial complete-head comparisons and 632 final protected-head comparisons pass binary32 checks. All 32 legacy permission cases retain P. The fresh 72 examples are reviewed authored engineering references, now exposed by this release. They are not independently reviewed statutory gold. Eight statutory source examples remain unscored.

The configured 384D inputs are dormant placeholders and latent conditioning is disabled. This run establishes no genuine 8D/384D/768D latent semantics, broad logic-family compatibility, legal semantic accuracy or new Lake compilation. No `lake build legal` run was performed for this candidate.

The 32-step candidate is compared with the fixed, already trained historical CE checkpoint, with zero new control updates. This is not a new randomized comparison or an equal-FLOPs study. Historical control: https://huggingface.co/Publicus/legal-ir-autoencoder/tree/0a89f3bfaa9db3ff028801b06fe6ee68ad73be19/releases/20261013-temporal-adapter-v1

A preserved first attempt failed at the inherited parent's 128-row API limit before any update, after 704 inference calls. The successful technical retry chunks the 168-row parent capture as 128+40. It makes 1760 inference forwards plus 32 training batch forwards, using 384 training row occurrences. The failed attempt's 200 MB claim remains retained; the successful claim was released after durable output preservation. Other claims/caps/roots/configuration remain unchanged.

Load the custom JSON checkpoint with `SpanTemporalAttentionAdapterDecoder` from the archived source module. The checkpoint SHA256 is a56ad426a802ce80f11568e0fa72a777ff8da38b5fa0fe0f54bca303a63a8384. Inspect the complete 74-file result bundle, frozen source contract, parent-only analysis and independent recount before interpreting outputs. The next measured gap is actor/condition/exception boundary extraction, particularly interrupted clauses; 13 of 15 remaining training whole-IR failures have incorrect actor spans.
