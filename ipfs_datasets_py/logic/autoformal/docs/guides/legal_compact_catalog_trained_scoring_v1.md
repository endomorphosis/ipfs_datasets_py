# One-step trained-weight catalog scoring

`legal_compact_catalog_trained_scoring_v1` consumes an original trained CONTENT
checkpoint and applies the existing optional-catalog selection policy to one
actual score vector. The checkpoint keeps its original codec, weights, permanent
initialization, immediate parent and historical optimizer metadata. Nothing is
rewritten or relabeled as catalog training.

This guide describes the interface and its limits. An installed source hash or
this document does not establish completed numerical qualification; that requires
a separate admitted run and its exact retained receipt.

```python
from ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_catalog_trained_scoring_v1 import (
    score_compact_catalog_trained_v1,
)

observation = score_compact_catalog_trained_v1(
    checkpoint,
    conditioning,
    prefix_ids,
    catalog_context_raw,
    expected_checkpoint_sha256=checkpoint_sha256,
    expected_catalog_context_sha256=catalog_context_raw_sha256,
)
```

The checkpoint is an ordinary dictionary in the exact existing v2 training
format. `conditioning` is an ordinary list of 384 finite numbers, each with
absolute value at most `1e8`; booleans are refused. `prefix_ids` is an ordinary
nonempty list of at most 512 exact integers. Empty prefixes are refused because
the trained forward reads the final position's logits. The context must be the
complete bytes of an existing catalog wrapper, independently committed by its
raw SHA-256. Use `prepare_catalog_context_v1` to assemble that wrapper; this owner
does not build a catalog from a target or source nomination.

Ordinary-container bounds and original hashes are checked before importing the
public owners. The whole input envelope is capped at 96 MiB, the checkpoint at
64 MiB, context bytes at 512 KiB and the complete output at 4 MiB. Each codec and
the complete logits vector has a 32 KiB serialized cap. Oversized values,
nonfinite numbers, cycles, foreign container types and incomplete output are
refused without truncation. These are finite input/output budgets, not physical
memory containment or resource admission. Numerical use must run under the
applicable owned-validation resource request and current-pressure backoff policy.

## Separate training and inference contracts

The operation calls the public
`inspect_compact_content_trained_checkpoint_v2` without allocating a numerical
owner or optimizer. It retains the original complete `training_codec` and
`training_codec_sha256`, then builds and validates the existing catalog
`inference_codec` and `inference_codec_sha256` separately. The two identities must
be distinct, and the catalog codec's parent commitment must equal the original
training codec hash.

The `bridge` and `bridge_sha256` record exact canonical equality of the complete
ordered 537-token vocabulary, PAD/BOS/EOS IDs and meanings, sequence limits,
constructor inventory, node/depth limits and supported integer geometry. Matching
only the vocabulary width is insufficient. The training grammar requires complete
declared-predicate use; catalog inference permits a nonempty referenced subset in
catalog order. Both complete codecs and the explicit policy difference remain in
the report.

`lexical_bridge_verified` describes these mechanical comparisons. It does not
authenticate training for the new policy. `catalog_training_verified` is false
both at the report boundary and inside its authority/bridge declarations. A
self-consistent independently pinned future checkpoint can be inspected under the
same exact profile; resealing state does not authenticate historical training,
producer identity or a new accepted profile.

## Forward and zero-forward outcomes

The original complete wrapper is passed to
`compact_catalog_allowed_token_ids_v1`. Its whole catalog, including unused
declarations, remains validated and committed. The new owner checks the returned
prefix receipt's exact IDs, raw/canonical catalog bindings, source descriptors,
allowed-ID inventory, bounds and authority fields.

If the public prefix owner allows a next token, the pinned trained runtime's
model-only `_forward` consumes the already inspected original checkpoint,
conditioning and prefix. This restores current weights only, verifies the actual
one-thread CPU float32 runtime and preserves ambient CPU RNG through the existing
runtime contract. The catalog is never supplied to that numerical primitive.

The `scored` report retains all 537 finite float scores, `logits_sha256`,
`output_shape` equal to `[1, len(prefix_ids), 537]`, and `actual_runtime`.
The actual score list is passed directly to `select_compact_catalog_token_v1`.
The returned full selection receipt is checked against the original prefix,
catalog, codec and score hashes, raw and constrained maxima, lowest-ID tie rule,
selected ID and exact one-token extension. There is no replacement parser,
optimizer, source encoder or generation loop.

One numerical forward is recorded even when only EOS is permitted. Such a forced
selection does not establish a learned structural decision. A supplied complete,
rejected or budget-exhausted prefix instead returns `status="no_forward"` with
the prefix owner's reason, unchanged `next_prefix_ids`, and null `logits`,
`logits_sha256`, `selection`, `output_shape` and `actual_runtime`. No numerical
owner is imported or restored on that path. Invalid original context, checkpoint,
codec bridge or ordinary input bounds are operation failures, not fabricated
model outcomes.

## Report and custody

The report schema is `legal-compact-catalog-trained-score/v1`; its profile is
`original-trained-content-weights-catalog-selection/v1`. It retains:

- The original checkpoint and current weights hashes, original training profile,
  initialization/parent commitments, recorded training progress, population
  hash/count and optimizer metadata/state hash.
- Both complete codecs, their separate identities and the lexical bridge.
- The original conditioning and its hash, pure float32 numeric conversion,
  supplied prefix and unchanged or one-token-extended prefix.
- Exact context text under `catalog_context_raw_utf8`, its raw hash, canonical
  wrapper/catalog hashes and the complete public prefix receipt.
- The full scores and selection receipt when executed, with declared runtime
  always separate from the actual runtime observed during a forward.
- Source descriptors, complete authority fields and numerical accounting.

`numerical_forward_count` and `original_forward_count` are integer zero or one.
`replay_forward_count` and `reference_forward_count` stay integer zero: this API
performs neither. Qualification harnesses must count any independent arithmetic
reference or replay work separately. `numerical_forward_executed`,
`model_restore_performed`, `model_executed`, `runtime_verified` and
`runtime_torch_version_verified` are true only after a successful actual forward;
all are false on `no_forward`. A recorded checkpoint runtime remains a declaration
on that path.

Ordinary original inputs, detached inputs and retained cross-owner values are
checked around grammar and numerical work. Canonical source paths, raw SHA-256,
physical file identities and public import anchors are checked around imports,
calls and complete output serialization. A closing custody failure refuses a
result; if work already raised, its first exception is preserved and receives a
note about the closing failure. These are finite endpoint custody checks, not a
hermetic interpreter or proof of arbitrary loaded bytecode.

All semantic, source-encoder, context-permission, prefix-independence, historical
training, statutory-accuracy, acceptance and Lean authority flags remain false.
`training_mask` and `evaluation_gold_mask` are exact integer zero.
`training_executed`, `optimizer_executed`, `optimizer_constructed` and
`optimizer_state_restored` are false. Numerical execution grants no legal,
training, evaluation, admission or proof credit.

## Separate future work

This owner does not duplicate the separately owned trained-source bridge,
prepared sessions, decoder architecture, catalog continuation or batch intake.
A later source consumer must freeze exact nomination disposition and catalog
mapping before any forward. A later continuation trace must preserve original
and replay counts and pass unchanged observations to the existing batch owner.
Source-encoder authentication, permission, reviewed legal meanings and actual Lean
checking each require their own independent inputs and acceptance gates.
