# LegalIR split-feature training, 2026-10-13

The experimental split-feature decoder improves joint exact agreement on the exposed authored evaluation panel to **32/72**, while legacy retention falls to **94/96**. It fails the declared 96/96 retention gate and is not selected or promoted as a default.

## Architecture and training

The original byte embedding, token projection, bidirectional recurrent features, and modality head remain frozen. An independent copy of the features feeds trainable presence, start, and end heads. The model has 34 parameter tensors: 17 trainable and 17 frozen, including four dormant latent tensors. Each source forward traverses two feature paths; equal compute with earlier architectures is not claimed.

Training reused the preceding 168 authored rows and source-only checkpoint-400: seed/order 1729, fresh Adam, learning rate 0.001, batch size 12, and 32 updates. Presence weight is 1, modality weight is 2, and the actor hinge is disabled. Modality loss contributes a constant and supplies no gradient to the copied span features. The configured dimension is 384, with latent conditioning disabled and zero external latent/context encoder calls.

Before training, all four saved head payloads, tokens, greedy outputs, and joint outputs match the parent over 392 source occurrences. After training, all 392 saved modality vectors remain byte-identical to the parent, including abstentions and eight unreviewed law rows. These saved-output checks do not independently replay model tensors or optimizer moments.

## Results

Counts are exact authored LegalIR matches as **greedy / joint**. Joint selection keeps the existing top-8, 50,000-node policy. The hybrid combines saved parent modality scores with prior full-parameter span scores; it is a diagnostic assembly, not a trained checkpoint.

| Panel | Rows | Parent | Full parameters | Span heads only | Saved-score hybrid | Split features |
|---|---:|---:|---:|---:|---:|---:|
| Legacy tuning | 96 | 96 / 96 | 93 / 93 | 96 / 96 | 96 / 96 | 94 / 94 |
| Authored development | 72 | 0 / 0 | 40 / 42 | 4 / 4 | 39 / 39 | 44 / 45 |
| Authored evaluation | 72 | 6 / 6 | 19 / 22 | 6 / 6 | 25 / 27 | 26 / 32 |

Both legacy regressions are temporal-presence false negatives: `native-tuning-calendula-t6-q7-o` and `native-tuning-calendula-t6-q7-p`. All other legacy role counts remain 96/96. All 32 legacy permissions retain P, with zero P-to-O, P-to-F, or abstentions. Freezing also retains the parent's newer permission head errors: 14 P, 4 O, and 6 F among 24 authored permissions.

## Opt-in use

Source: [legal_span_split_features.py](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_split_features.py). Tests: [test_legal_span_split_features_contracts.py](../../tests/unit/optimizers/logic_theorem_optimizer/test_legal_span_split_features_contracts.py).

The additive [Hugging Face release directory](https://huggingface.co/Publicus/legal-ir-autoencoder/tree/main/releases/20261013-split-feature-v1) contains the checkpoint, source, model card, and bounded public evidence. Use `cells/split-features/results/cell-checkpoint.json`, schema `bounded-split-feature-span-legal-formula-checkpoint/v1`, with SHA256 `95bd50a7cc6e25381ad126e3d955f0816c31470ec469fb22ceca297e35115035`.

Inside the qualified numerical runtime, load it with `legal_span_split_features.load_checkpoint(path, expected_sha256=...)`, construct `SpanSplitFeatureDecoder(checkpoint)`, and call `decode_formal_logic(texts, latents, latent_ablation="disabled")` with one 384-value placeholder vector per source. Loading restores this split architecture; the checkpoint is incompatible with the parent single-feature loader. Inspect each returned row's decoded/abstained status and provenance.

## Limits and next work

All 384 authored targets were previously exposed and share templates. The eight law rows have no reviewed targets and remain unscored. These counts establish neither independent US Code fidelity nor genuine 8D/384D/768D latent conditioning, broader logic-family support, or a successful `lake build legal`.

The next finite experiments should diagnose temporal-presence retention, improve actor and object binding, and obtain reviewed provision-group holdouts before claiming generalization. The `actor_duration_name` class remains joint exact 0/12 on development and 2/12 on evaluation. Authored evaluation object-span agreement is 38/72 with greedy decoding and 45/72 with joint selection. Preserve the current parent and experimental checkpoints while testing any proposed repair; no repair or default promotion is demonstrated here.
