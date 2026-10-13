---
language: en
tags:
  - legal-ir
  - autoformalization
  - experimental
  - span-extraction
  - deontic-logic
---

# LegalIR split-feature decoder: experimental checkpoint

This release trains an independent span feature branch while freezing the parent modality feature branch. On the previously exposed authored evaluation panel, joint exact LegalIR outputs increase from 22/72 for the preceding full-parameter arm and 27/72 for a saved-score hybrid to 32/72. Legacy exact outputs fall from 96/96 to 94/96. **The checkpoint fails the declared retention gate and is not selected or promoted as a default.**

The task is structured LegalIR span extraction with obligation (O), permission (P), and prohibition (F). Exact agreement with authored LegalIR targets is an engineering measurement. It does not establish correct interpretation of US Code, executable theorem proofs, or support for every logic family.

## Architecture and training

The original byte embedding, token projection, bidirectional recurrent features, and modality head remain frozen. A separate copy of the original features feeds the trainable presence, start, and end span heads. The original path runs without gradient recording; span loss updates only the copied feature path and six span-head tensors. There are 34 parameter tensors: 17 trainable and 17 frozen, including four dormant latent tensors. There are two feature paths per source forward; equal compute with the earlier arms is not claimed.

The parent is the retained source-only checkpoint-400 (SHA256 `5df537d8c7141578c1355af43317b9c5a327305295a11760aee2897244bc5dbb`). Before training, both feature copies and all four saved head payloads, tokens, greedy outputs, and joint outputs match the parent over 392 source occurrences. After training, all 392 saved modality vectors remain bit-identical to the parent. That check covers saved outputs; tensor, gradient, and optimizer-moment replay was not independently performed.

One run used the same 168 training rows as the preceding permission-retention experiment: seed/order 1729, fresh Adam, 32 updates, batch size 12, learning rate 0.001, presence weight 1, modality weight 2, and actor hinge disabled. The configured latent dimension is 384, but latent conditioning is disabled. There were zero external latent/context encoder calls. This is not a trained or evaluated 8D, 384D, or 768D latent-conditioned decoder.

## Saved-output results

Values are exact LegalIR matches as **greedy / joint**. The joint decoder uses the retained fixed 8-candidate, 50,000-search-limit configuration. All panels share authored templates and were previously exposed; none is independent statutory gold.

| Panel | Rows | Parent | Prior full parameters | Prior span heads only | Saved-score hybrid | Split features |
|---|---:|---:|---:|---:|---:|---:|
| Legacy tuning | 96 | 96 / 96 | 93 / 93 | 96 / 96 | 96 / 96 | 94 / 94 |
| Authored development | 72 | 0 / 0 | 40 / 42 | 4 / 4 | 39 / 39 | 44 / 45 |
| Authored evaluation | 72 | 6 / 6 | 19 / 22 | 6 / 6 | 25 / 27 | 26 / 32 |

The saved-score hybrid combines parent modality logits with the prior full arm's saved span scores. It is a diagnostic assembly, not another trained checkpoint.

The two legacy regressions are temporal-presence false negatives on `native-tuning-calendula-t6-q7-o` and `native-tuning-calendula-t6-q7-p`. All other legacy role counts remain 96/96; temporal matches are 94/96. All 32 legacy permission rows retain P, with zero P-to-O, P-to-F, or abstentions. On the newer 24 permission rows, the frozen modality branch retains the parent's 14 P, 4 O, and 6 F choices. Freezing preserves those existing errors too.

The remaining `actor_duration_name` class has joint exact 0/12 on development and 2/12 on evaluation. Evaluation object spans match 45/72. Eight law-source rows remain unreviewed and unscored; their decoded-output counts are not accuracy measurements.

## Artifact and use

Checkpoint: `results/cell-checkpoint.json`, 3,592,389 bytes, SHA256 `95bd50a7cc6e25381ad126e3d955f0816c31470ec469fb22ceca297e35115035`.

Checkpoint schema: `bounded-split-feature-span-legal-formula-checkpoint/v1`. The opt-in API is `legal_span_split_features.load_checkpoint(path, expected_sha256=...)` and `SpanSplitFeatureDecoder(checkpoint).decode_formal_logic(...)`. Checkpoint loading restores model tensors and belongs inside the qualified runtime. The split checkpoint uses its own architecture and must not be loaded as a parent single-feature checkpoint.

The source module and contract tests are included in this release. The preceding trained arms and retained reference material are available in [the immutable permission-retention release](https://huggingface.co/Publicus/legal-ir-autoencoder/tree/c1aa22e1677a7887ece53aac7caa52cef23ca8d7/releases/20261012-permission-retention-v1). Release receipts bind exact source, checkpoint, output, and analysis identities. The 53 current output files were frozen before new target scoring. Pure contract checks passed 194 tests and 383 subtests.

## Runtime and limitations

The bounded training run completed 32 actual updates in 35.292 seconds of model wall time, with sampled model RSS 752,267,264 bytes and terminal storage 33,605,972 bytes. Its own 200 MB claim was released; all original 528 storage ledger records were preserved. Limits remained two CPU threads, 1,536 MiB RSS, one model child, 200 MB storage, and 300 seconds. Sampled RSS is not a continuous peak guarantee.

This release provides one seed and an exposed authored comparison. It has no blinded evaluation, statistical significance claim, independent statutory gold, actual Lake build, broader logic-family qualification, or genuine latent dimension comparison. Structural validity and exact authored agreement must be distinguished from legal fidelity. Retention failure prevents default promotion. See the accompanying gap plan for the next finite experiments and promotion gates.
