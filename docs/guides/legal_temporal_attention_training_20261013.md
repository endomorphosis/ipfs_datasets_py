# LegalIR temporal attention experiment, 2026-10-13

The opt-in temporal attention adapter completed its bounded training and passed the technical retention checks. It did not improve the fresh development measures or pass the preregistered selection gates. The default decoder is unchanged.

## Implementation and training

`SpanTemporalAttentionAdapterDecoder` in `ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_temporal_attention.py` adds a 64-scalar query and a temporal presence readout over the existing span features. It combines masked attention with mean pooling and adds no encoder. The original 34 tensors remain frozen. Three tensors store 1096 trainable scalars; 322 are active, including only temporal head rows 6:8.

The candidate starts equivalent to the N4 split-feature parent. It receives 32 fresh Adam updates on the authenticated 168 authored training examples, with seed 1729, batch 12 and learning rate 0.001. The comparison uses the already trained N6 CE checkpoint with zero new control updates. This is a fixed historical comparison, not a new randomized or equal-FLOPs study.

## Measured result

| Authored engineering measure | Historical N6 CE | Attention |
|---|---:|---:|
| Legacy complete IR, greedy and joint |95/96|95/96|
| Fresh development temporal presence |25/36|25/36|
| Fresh test temporal presence |19/36|19/36|
| Fresh development complete joint IR |0/36|0/36|
| Fresh test complete joint IR |0/36|0/36|
| Older authored evaluation complete joint IR |50/72|49/72|

The legacy requirement was 96/96, with all 32 permission cases retaining P. Permission retention passes, but complete-IR retention does not meet 96/96. Fresh development matches the fixed control on both selection measures, so the required strict improvement is absent. No candidate is selected and no default promotion occurs. Test examples did not affect selection.

Temporal presence on training examples was already 168/168 before training and remains 168/168 afterward. Complete training IR remains 153/168. Learned and uniform attention produce the same temporal-correct and complete-IR outcomes on legacy 96 plus fresh 72, while numerical scores change. This control measures inference dependence and does not identify causal training effects.

All 632 initial complete-head comparisons and 632 final protected-head comparisons pass binary32 checks. The independent standard-library recount verifies 35 panel summaries, 32 scored row sets and 20 paired comparisons directly from saved outputs. Full checkpoints and raw captures are kept in the separate Hub archive; Git retains source, tests and compact public evidence.

## Preservation and accounting

Attempt 01 failed at the inherited parent's 128-row source API limit before any update, after 704 completed inference forwards. Its artifacts and 200 MB retained claim remain preserved. Attempt 02 splits the parent 168 capture into 128+40 without changing the recipe or retraining the control. The successful attempt uses 1760 inference forwards plus 32 training batch forwards, for 1792 model forwards and 384 training row occurrences. Across both attempts the observed counts are 2464 inference forwards and 2496 total model forwards, with 32 optimizer updates in total.

All 74 successful outputs were frozen before authored-reference scoring. The successful owned storage claim was released after durable preservation. The terminal audit preserves all 532 prior records, including the failed retained claim, and observes 533 records after the successful claim. Resource evidence is sampled; it does not establish continuous coverage or hard kernel memory quotas.

## Scope and next experiment

The fresh 72 examples are reviewed authored engineering references and become exposed diagnostics after this release. They are not independent statutory gold. Eight statutory source examples remain unscored. Configured 384D inputs are dormant placeholders with latent conditioning disabled. No genuine 8D/384D/768D latent semantics, broad logic-family compatibility, legal semantic accuracy or new Lake compilation is qualified.

The next proposal is an opt-in actor start/end correction from the common N4 parent, preserving modality and other heads. A manual authored-reference review separates the 15 remaining training whole-IR failures into 12 selected actor-boundary errors, two selected condition-boundary errors and one overall abstention. The aggregate 13 actor-role nonmatches include the 12 selected boundary errors plus that abstention. Ten selected actor outputs truncate at Office; two choose an internal quoted-name fragment. The condition errors omit the full time guard. Review source-local modal and quote boundary features and grammar candidate coverage, preregister the actor-only tensor/row/moment policy and batch budget, then compare a bounded head-only correction on the authenticated 168 rows. This manual authored-reference review does not provide legal-expert or statutory gold. Add interruption fixtures for conditions, exceptions and semicolon applicability. Keep new development/test source groups separate; the now-exposed 72 examples cannot serve as future blind tests. Statutory/context review and a separately bounded compiler run remain prerequisites for stronger claims. This proposal is design only. No additional training or admission was performed for this proposal.

## Evidence and archive

[Public result summary](../implementation/reports/evidence/legal-temporal-attention-20261013-01/public-result-summary-v01.json), [independent result review](../implementation/reports/evidence/legal-temporal-attention-20261013-01/result-independent-review-v01.json), [compact training metadata](../implementation/reports/evidence/legal-temporal-attention-20261013-01/training-metadata-summary-v01.json), [next measured gaps](../implementation/reports/evidence/legal-temporal-attention-20261013-01/next-experiment-gaps-v01.json) and [full-evidence pins](../implementation/reports/evidence/legal-temporal-attention-20261013-01/full-evidence-pins-v01.json) describe the exact retained evidence.

Hub repository: `Publicus/legal-ir-autoencoder`.
Release prefix: `releases/20261013-temporal-attention-v1`.
Immutable Hub revision and verified archive URL: [3440e82e07555b9f7e1d2608cac762ef66eecae4](https://huggingface.co/Publicus/legal-ir-autoencoder/tree/3440e82e07555b9f7e1d2608cac762ef66eecae4/releases/20261013-temporal-attention-v1).
Publication receipt: [verified publication receipt](../implementation/reports/evidence/legal-temporal-attention-20261013-01/hf-publication-verification-v01.json).

[Compact manual authored training-error review](../implementation/reports/evidence/legal-temporal-attention-20261013-01/authored-training-error-review-v02.json) refines the older aggregate gap counts. This compact packet is retained in Git evidence and is outside the already sealed 136-file Hub release specification.
