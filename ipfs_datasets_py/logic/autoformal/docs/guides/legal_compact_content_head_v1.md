# Numerical head for compact LegalIR content

This opt-in engineering profile connects the existing numerical GRU to the qualified ordered 537-token compact-content codec. It uses CPU float32 and an explicit 384-coordinate conditioning vector. It introduces no new AST, grammar, embedding producer or legal semantics.

The canonical owner is `logic/formalization/autoencoder/legal_compact_content_head_v1.py`. The earlier flat-rule trainer and its public checkpoints remain separate contracts. The new checkpoint identifies its own task/profile, exact ordered vocabulary and hash, 512-total-ID output ceiling, dimensions, dtype, implementation sources, Torch version and all 13 model-state tensors.

The public API creates or warm-starts a snapshot, hashes it, validates it by strict restore, serializes it, loads independently committed raw bytes, and scores a supplied prefix:

- `create_compact_content_head_v1(*, config=None, parent_checkpoint=None, expected_parent_sha256=None)`.
- `compact_content_head_sha256(checkpoint)`.
- `validate_compact_content_head_v1(checkpoint, *, expected_checkpoint_sha256)`.
- `compact_content_head_bytes_v1(checkpoint, *, expected_checkpoint_sha256)`.
- `load_compact_content_head_v1(checkpoint_raw, *, expected_raw_sha256)`.
- `score_compact_content_head_v1(checkpoint, conditioning, prefix_ids, context_raw, *, expected_checkpoint_sha256, expected_context_sha256)`.

## Geometry and inputs

The model reuses `modal_latent_formula._model`: a residual projection, conditioning layer, token embedding, single-layer GRU and output layer. Input and projected output each have 384 coordinates. Projection width, GRU hidden width, token embedding width, vocabulary size and total output length are recorded separately. The residual bypass means projection width is not a demonstrated compression bottleneck.

A supplied conditioning vector is a numerical observation. Width and a checkpoint hash do not verify the embedding producer, source geometry, context permission or lawful source interpretation. Raw text and target-derived signature/role context do not become neural inputs in this profile. The symbolic context is supplied separately for the existing prefix constraints and selector only.

Score intake accepts a supplied prefix rather than an expected answer or identity sidecar. For an admissible nonterminal prefix it computes real model logits and calls the existing public finite-score selector. Its report retains all 537 scores, raw/selected decisions and offered/resulting prefixes. A terminal or blocked prefix records an explicit disposition without fabricating a numerical forward. No generation loop, complete target prediction, decoding accuracy or speed comparison follows from a single-step forward.

## Weight identity and restoration

Seeded construction is explicit. An optional warm start first validates the supported trained 384D parent through its existing owner, preserves the parent's compatible geometry and delegates exact transfer to the existing transfer owner. The transfer ledger identifies ten copied nonlexical tensors and three vocabulary-dependent tensors. Shared lexical rows map by exact token spelling; unseen rows use the parent row mean. Mean initialization does not establish learned symbol meaning. The donor remains unchanged. Its expected canonical checkpoint hash uses the existing parent owner’s `checkpoint_digest` convention; the new head’s UTF8 canonical identity and received raw-byte identity remain separate.

The new checkpoint is weights-only. Parent optimizer moments and training examples are not imported. A later training consumer must create a fresh optimizer and bind its actual data/eligibility contract. Trained weights and optimizer progress require a separately versioned checkpoint contract; they cannot be relabelled as this zero-step v1 snapshot. This profile does not provide optimizer resumption, a training API or compatible loading of arbitrary historical lineages. The separately qualified native4096 source-span consumer's Adam resumption remains evidence for that different grammar and input contract.

Restoration checks the whole closed checkpoint: ordered vocabulary/task/profile/output ceiling, metadata commitments, every tensor name and shape, exact exported float32 values, finite conversion and implementation binding. Integer tensor leaves and doubles that would round to a different float32 value are refused. Wrong dimensions, extra state, bools, nonfinite values and overflowing finite doubles are refused. No partial tensor installation is a successful restore. Canonical checkpoint identity and received raw-byte identity are separate commitments.

Numerical operations require the caller's admitted CPU scope and one Torch thread. Construction uses the existing locally seeded RNG-preserving mechanism. A numerical restore requires the checkpoint’s recorded Torch version to match the installed version. This version guard does not authenticate binaries. Installed Torch and NumPy are third-party runtime dependencies; source fences and test-child raw compilation do not prove their binary provenance or a hermetic operating system.

## Qualification scope and remaining work

Engineering tests use fabricated conditioning and explicitly authored targets. A tiny old-grammar parent fixture may perform one real CPU update solely to test validated transfer from a trained donor. This compact head performs zero new-target optimizer updates. Real logits and exact state/logit reload checks qualify mechanics, not source-held-out performance or legal meaning.

All source/review/training/gold authority remains false and eligibility masks remain zero. Source occurrence/cache joins, interpretation and governing definitions, permitted context, producer binding, exposure/splits and complete-population consumer eligibility remain required before statutory fitting or evaluation. Reuse the current qualified semantic-token batch/reconstruction owner rather than making another denominator.

[Implementation evidence](../../../../../../../artifacts/legal-ir-compact-numerical-head-20261017-01/README.md) records exact API/report schemas, source generations, numerical diagnostics and owned resource closeout.
