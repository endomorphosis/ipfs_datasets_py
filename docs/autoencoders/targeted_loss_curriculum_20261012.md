---
language: en
tags:
  - legal-ir
  - autoformalization
  - experimental
  - source-span-decoder
---

# Four retained LegalIR targeted-loss candidates

This additive release archives a matched 2×2 comparison of actor-ranking loss OFF/ON and condition/exception presence CE weights 1/2. All four candidates are experimental. None passes the older permission-preservation gate; no default is promoted.

The decoder extracts a bounded single-rule LegalIR structure from source spans. Configured latent dimension is 384, latent conditioning is disabled, and all four runs recorded zero encoder calls. These weights do not qualify genuine 8D, 384D or 768D autoencoder conditioning, independently reviewed US Code fidelity, broader logic families or `lake build legal`.

## Matched training contract

Each cell begins with the same retained source-only 400-update parent and fresh Adam moments. It uses the same 168 training rows, row order, source geometry, initialization/order seed 1729, batch size 12, learning rate 0.001 and 32 returned updates. There are 128 new updates in total, with 384 row occurrences per cell. The first 96 training rows preserve the older rehearsal population; the remaining 72 mix the earlier actor/scope layouts. Inference and its K=8 joint candidate procedure are unchanged.

The normalized main objective is `(2 × modality CE + six facet-loss means + (presence weight − 1) × (condition-presence CE + exception-presence CE)) / (8 + 2 × (presence weight − 1))`. Ranking ON adds `0.25 × mean(max(0, 1 + highest-scoring valid wrong actor span − gold actor span))`. Its training domain covers all bounded source spans, excludes padding/reversed spans, the exact gold actor and overlaps with present gold nonactor facets. Empty negative domains contribute differentiable zero. OFF logs the same counterfactual diagnostics without applying their gradient.

The authoritative checkpoint outer schema is `bounded-targeted-loss-span-legal-formula-checkpoint/v1`, with lineage `bounded_source_span_targeted_loss_v1` and policy `bounded-source-span-targeted-loss-policy/v1`. Use `legal_span_targeted_loss.py` and its dedicated loader. Nested legacy fields describe initialization; they do not redefine the actual weighted objective or convert this checkpoint into a legacy training checkpoint. Prior producer bytes and schemas were retained.

## Measured outcomes

“Raw” is the ordinary span readout; “joint” uses the unchanged compatibility selector. Exactness here means agreement with authored engineering references, not established legal equivalence.

| State | New authored evaluation raw /72 | New authored evaluation joint /72 | Older raw and joint /96 | Older P→O, each readout | New evaluation joint P→O |
|---|---:|---:|---:|---:|---:|
| Common parent | 6 | 6 | 96 | 0 | 4 |
| Ranking OFF, presence 1 | 19 | 22 | 93 | 3 | 13 |
| Ranking OFF, presence 2 | 18 | 18 | 86 | 4 | 13 |
| Ranking ON, presence 1 | 18 | 23 | 94 | 2 | 13 |
| Ranking ON, presence 2 | 16 | 16 | 90 | 2 | 13 |

| State | Exposed development raw /72 | Exposed development joint /72 | Previously exposed evaluation raw /72 | Previously exposed evaluation joint /72 |
|---|---:|---:|---:|---:|
| Common parent | 0 | 0 | 12 | 12 |
| Ranking OFF, presence 1 | 40 | 42 | 49 | 52 |
| Ranking OFF, presence 2 | 40 | 41 | 46 | 47 |
| Ranking ON, presence 1 | 39 | 39 | 49 | 49 |
| Ranking ON, presence 2 | 36 | 38 | 51 | 51 |

Every candidate fails the necessary exposed older gate of raw 96/96, joint 96/96 and zero P→O errors. The highest joint count, 23/72, is not a selected checkpoint. This is one matched seed without replication or significance claims. Prior experiments' different evaluation panels must not be compared as though they were the same held-out population.

The descriptive new-evaluation joint-exact main effects are −0.5 cases for ranking ON versus OFF and −5.5 cases for presence weight 2 versus 1; the difference of differences is −3 cases. Stronger presence weighting also raises temporal false negatives from 0/1 to 9/8 in the respective OFF/ON cells. Actor ranking raises gold-compatible K=8 coverage to 72/72 in both ON cells, but reduces compatible rank-one counts from 62/57 to 50/48. Candidate coverage and final exact selection remain distinct problems. These measurements support investigating permission retention and loss interference before increasing auxiliary weights.

## References, exposure and limits

The new development/evaluation panels each contain 72 authored rows across six classes, with disjoint provision, lexical, identity and source groups. All 151 saved outputs from all four completed runs were frozen before the scoring helper opened the new full evaluation references. The builder author could see the references and all panels share authored templates; this is not independent blinding or reviewed statutory gold. Development, older evaluation and tuning panels are exposed diagnostics. Eight real-law source rows per state remain unreviewed and unscored, regardless of output coverage.

Scores and selected structures were recomputed from saved head outputs using frozen pure selectors and structural stubs. Checkpoints were raw-hashed and kept opaque during analysis. This does not independently replay gradients or qualify legal semantics, codec behavior for every logic family, a proof backend or a compiler. Training full-domain ranking filters before argmax; inference top-K is formed before compatibility. Compatible gold rank alone therefore does not guarantee raw inference coverage.

## Checkpoints and evidence

All four files are retained under `cells/<cell>/results/cell-checkpoint.json`:

| Cell | Bytes | SHA256 |
|---|---:|---|
| rank0-presence1 | 2743806 | `7c19510cceb44388cf8d5d2af991ba9010ff347c30b9303c142fcf68af58eb28` |
| rank0-presence2 | 2743861 | `bb39e83b801b8ee026c123a858b204e9b81c971e36370dc8ad36acfd88d4fb3d` |
| rank1-presence1 | 2740867 | `446d8b2165290a76b8534bbe3205395f05eb64e7f51320e21d5d657564ee1b02` |
| rank1-presence2 | 2740909 | `b68ccc8c054a1edc15c770552c8f9354bf8d7b570de448d9bd0e72b9b754d77f` |

The original parent's model-state hash is `54e745f0dc75a79c11828048ad5deb44b0f07dcac5b9083bde17948b5206bfcb`. `evidence/targeted-result-analysis-v01.json` contains all panel, facet, class, pair, ranking, regression and policy observations; `evidence/four-cell-output-freeze-v01.json` binds the 151 raw outputs. Runtime/result/source independent reviews, training protocols, the exact source/data export and recipes are included. Pure validation passed 156 tests plus 266 subtests without failures, errors or skips.

Each serial run completed under the existing resource guardian with a distinct released 200 MB reservation, two CPU slots, a 1536 MiB sampled RSS envelope and a five-minute child deadline. Shared ledger caps and earlier record bodies were preserved. These are sampled process and endpoint observations, not a kernel hard memory limit or continuous custody proof. Full shared-ledger bodies and private snapshots are excluded from this public release. Earlier weights and releases are preserved; the publication manifest and immutable readback receipt establish the final upload inventory separately from training correctness.

Next qualification priorities are permission-preserving updates, replicated ranking/loss comparisons, independently reviewed statutory source/context references, real encoder-conditioned profiles, typed family-specific output contracts and actual bounded Lean builds. No semantic accuracy percentage is claimed.
