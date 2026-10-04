# Continue a retained source-v2 decoder

The source-v2 training entry point initializes from a native Legal parent and
rebuilds its vocabulary and input normalization. Passing an already trained
source-v2 checkpoint to that entry point cannot preserve the learned decoder.
`source_checkpoint_continuation_v1` instead loads the complete saved decoder
state, preserves its token meanings and input coordinates, and starts fresh
Adam. This provides a saved-weight warm start; source-v2 checkpoints contain no
serialized optimizer moments, scheduler/RNG state, or batch cursor.

The existing source-v2 implementation and retained checkpoint bytes remain the
inputs to this separate, versioned continuation owner. The first version accepts
only the original ordered training and validation caches for a genuine 384D
source-v2 checkpoint. It supports the families accepted by that frozen runtime:
LegalIR, IntentIR, SecurityIR, and UI/UX IR. CodebaseIR, 8D/768D transfer, learned
prose reconstruction, and FOL/TDFOL decoder training need their own compatible
contracts and checkpoints.

## Retained inputs and decoder identity

`prepare()` is stdlib-only and does not execute a model or numerical owner. It
checks the absolute checkpoint path, regular-file descriptor, bounded bytes,
expected SHA256, closed checkpoint schema, all thirteen tensor shapes and their
digest, saved codec and transformation, and both original split manifests.
Cached rows must preserve IDs, text, vectors, targets, and order exactly. Fit and
validation IDs, source hashes, normalized source hashes, and embedding hashes
must remain disjoint. Targets cannot add vocabulary or exceed the saved token
limit. The numerical adapter also applies the original typed target validators.

The continuation binding separates IR family, dimension, dimension role, IR
schema version, decoder task, and output format. The supported task is
`typed_ir_reconstruction`, with `semantic_json` output and genuine 384D input
embeddings. The old checkpoint has no independently authenticated output IR
schema selector, so `schema_version` remains null. The checkpoint container
schema and lexical codec schema do not supply that missing identity. Arbitrary
schema labels, a legal-text task, FOL output, latent 8D geometry, or native 768D
geometry cannot be attached to this decoder by relabeling metadata.

The initial adapter uses each checkpoint's stored normalization. For example,
the retained raw checkpoint has an identity transform, while the retained
semantic checkpoint has its own 384-coordinate mean and RMS scale. Both have
the same lexical vocabulary but are distinct model states and coordinates.

## Execute through the authenticated source capsule

The saved checkpoint pins its original source owners, including the numerical
model and native IR validators. A changed dependency in the current checkout
can legitimately fail those pins. Use the authenticated retained source capsule
with these two new continuation modules admitted alongside it. Do not replace
old implementation hashes with current hashes to make loading succeed.

Within that admitted execution environment:

```python
from ipfs_datasets_py.logic.formalization.autoencoder import (
    source_checkpoint_continuation_v1 as continuation,
)

result = continuation.warm_start(
    "legal_ir",
    original_training_cache["rows"],
    original_validation_cache["rows"],
    source_checkpoint={"path": absolute_checkpoint_path, "sha256": expected_sha256},
    config={
        "strategy": "semantic_v2",
        "epochs": 4,
        "max_optimizer_steps": 20,
        "batch_size": 12,
        "learning_rate": 0.0003,
        "max_seconds": 120,
        "validation_interval": 1,
        "patience": 0,
    },
)
```

Only optimization budgets, batching/seed, learning rate, selection strategy, and
loss weights can change. Architecture, codec, input normalization, embedding
provenance, maximum target tokens, and semantic paths remain fixed. This API
does not regenerate embeddings, invoke a model provider, accept test rows, or
perform a dimension transfer.

The numerical adapter strictly loads every saved tensor and checks the actual
loaded-state digest before creating Adam. Adam initially has zero state entries.
It measures initial free-running validation and retains the parent as its first
best candidate. `semantic_v2` selects by exact generated IR, then train-derived
varying-leaf accuracy, then the weighted objective as a tie-breaker. The
`reference_ce` strategy remains an explicit ablation. Every selected state must
have complete validation coverage; a worse update is not automatically adopted.

The owner checks finite loss, gradients, parameters and optimizer state, and
restores the selected weights. Training metrics distinguish attempted optimizer
steps from selected steps. If the parent stays selected, the new selected epoch
and step are zero although actual updates were attempted. Lineage separately
records the donor's selected step and original run step count: those are not
interchangeable. CPU RNG state and thread settings are restored around numerical
work. The soft deadline is checked at operation boundaries; an in-flight
operation or final serialization can finish after it. A supervised launcher must
provide the outer wall, CPU, memory and output limits appropriate to the run.

## Save and reload the continuation envelope

The returned `source-checkpoint-continuation/v1` envelope records the new
producer source hashes, exact donor file pin, loaded/selected weight digests,
fresh optimizer semantics, decoder binding and measurements. Its
`source_checkpoint` field contains the compatible legacy source-v2 inference
payload. The envelope identifies the new producer without changing the old
runtime implementation pins or presenting it as an old training run.

After saving the envelope with a new file SHA256, use:

```python
runtime = continuation.load_runtime(
    {"path": absolute_envelope_path, "sha256": envelope_sha256},
    expected_domain="legal_ir",
)
predictions = runtime.infer([
    {key: row[key] for key in ("id", "source_text", "embedding")}
    for row in original_validation_cache["rows"]
])
```

The loader authenticates the original donor bytes and closed lineage, compares
the preserved codec, transform, architecture, implementation, split manifests
and protected configuration with that donor, checks selection/fresh-optimizer
metrics, and loads through the original runtime. If the recorded donor path is
unavailable, `parent_resolver` may return an absolute path to a local copy with
the same SHA256 and byte count. It cannot substitute another checkpoint.

The envelope is a separate serialization contract: the old source-v2 file loader
cannot directly parse it. This first version starts from a pinned original
source-v2 checkpoint; chaining continuation envelopes as new training parents
requires a separately versioned contract. The public API returns the envelope
without overwriting the parent or publishing it to a registry or model hub.

## Evidence and remaining training work

Direct-file controls use portable synthetic checkpoints and inert injected
backends. They verify orchestration and malformed-input rejection without
importing Torch or package/model owners. Injected backends cannot claim actual
numerical execution. Real tensor loading, gradient updates, fresh Adam and
source-free predictions require separately admitted numerical execution and its
persisted receipts. Producer hashes identify source bytes; they do not attest
execution or semantic quality.

The continuation and runtime never grant teacher, proof, source-semantics,
admission or publication authority. Reusing the original validation split is a
development evaluation, not a fresh independent holdout. The existing poor
semantic reconstruction and lost legal wording remain separate problems:
repair modality/actor/action/object fidelity and evaluate a separately learned
prose decoder with sufficient retained surface information before using this
decoder as a semantic teacher for the 768D path.
