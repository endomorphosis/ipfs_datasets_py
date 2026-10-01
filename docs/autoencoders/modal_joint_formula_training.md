# Joint formula training for the 8D and 384D modal autoencoders

The `legacy_v1`, `legacy_v1_optimized` and `current_v2` facades support a
separately owned learned latent formula head. Supplying explicit formula targets
to their existing training method activates `modal-latent-joint-formula/v1`.
Every subsequent training call must include formula targets; a missing target
raises before an update rather than silently training only reconstruction.

Each model instance owns its own residual projection, formula GRU, vocabulary,
Adam moments and training cursor. Its checkpoint binds the exact core state,
lineage, dimension, configuration and listed implementation sources. A legacy
head cannot attach to the 384D model, another core checkpoint, or the optimized
legacy profile. No implicit conversion, weight download or architecture switch
occurs.

For bounded 384D reconstruction experiments using this unchanged decoder, see
the [versioned training profiles](reconstruction_training.md). They compare
input gain and reconstruction regularization with identical initial head
weights and update budgets. A changed core configuration requires its own
checkpoint binding; it is not a migration of existing trained weights.

## What trains

The numerical core produces its raw additive embedding before sample memory or
the historical target-assisted safety projection. A new residual projection
maps that vector into the representation used by the learned formula decoder:

```text
z = frozen modal core's raw embedding representation
p = z + W_up * tanh(W_down * z + b_down) + b_up
formula logits = GRU(previous formula token, initial_hidden(p))
loss = formula_weight * token_cross_entropy
     + reconstruction_weight * MSE(p, input_embedding)
```

Both terms train the residual projection; formula token loss also trains the
decoder. Reports record nonzero gradient/update evidence for each parameter
group and a separate formula-to-projection gradient norm. The old Python sparse
tables are frozen in this profile. This is joint training of the new projection
and formula decoder, not autodifferentiation through the historical sparse
optimizer. The historical unconfigured facade remains available unchanged.

The core still consumes embeddings and parser-derived modal features. The
learned head receives only the resulting vector; it does not receive source
tokens, target formulas, a compiler result or a retrieval table during inference.
Source text is retained for provenance. This is consequently not an independent
source-text-only formalizer. Read the
[historical investigation](historical_modal_decoder_research.md) for the exact
roles of spaCy, IR compilation and historical reconstruction metrics.

## Train through the common interface

Use a fresh process pinned to the canonical checkout. Reserve CPU/resources in
the caller and set one Torch thread before training. Existing worker scheduler
and storage policies are not bypassed by this library API.

```python
import torch
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as runtimes

torch.set_num_threads(1)
runtime = runtimes.open_runtime(
    "legal_ir", "legacy_v1",  # choose current_v2 explicitly for 384D
    checkpoint=existing_core_json,
    expected_sha256=exact_core_sha256,
    compute_device="cpu",
)

# These are existing typed LegalSample objects with explicit 8D or 384D vectors.
# Each supplied target must bind the exact corresponding sample ID and text.
training_targets = [
    {"id": sample.sample_id, "source_text": sample.text, "canonical_ir": ir}
    for sample, ir in training_pairs
]
tuning_targets = [
    {"id": sample.sample_id, "source_text": sample.text, "canonical_ir": ir}
    for sample, ir in tuning_pairs
]
result = runtime.train(
    [sample for sample, _ in training_pairs],
    validation_samples=[sample for sample, _ in tuning_pairs],
    formula_targets=training_targets,
    validation_formula_targets=tuning_targets,
    formula_options={"learning_rate": 0.01, "batch_size": 8,
                     "hidden_size": 32, "projection_width": 16},
    epochs=20, max_seconds=60,
)
assert result["report"]["training_executed"]  # inspect stopped_reason if false
observations = runtime.infer(inference_samples)
saved = runtime.model.save_formula_checkpoint("new-branch.formula.json")
```

`canonical_ir` uses the existing seven-facet rule schema: `rules` contains one
rule with `modality`, `actor`, `action`, `object`, `conditions`, `exceptions` and
`temporal`. Vocabulary is fitted from training targets only. Unknown target
atoms, duplicate sources, overlapping training/tuning sources, changed resume
manifests and malformed inputs are rejected. Tuning is observational in this
version; no automatic selection or promotion is performed. Keep held-out
canaries outside both arrays.

The first head supports exactly `typed_deontic_rule_v1`. Its 64-token bound and
temperature zero are fixed. It preserves explicit exception and temporal
atoms, but successful generation does not establish their semantic accuracy.
Other logic projections remain unsupported by this head; the existing
eight-family requirement is still outstanding. Domain-specific native heads
for Intent, Security and UI/UX retain their own schemas and projections; this
legal head is never attached to those classes. The separate
`source_conditioned_formula_v1` text model also remains separate.

## Save, resume and infer

The formula file contains the projection, decoder, codec, Adam moments and cursor.
It references the exact core by hash; it does not copy or overwrite core weights.
Keep both artifacts. Files must be fresh on save. Loading requires the exact
formula file SHA256:

```python
resumed = runtimes.open_runtime(
    "legal_ir", "legacy_v1",
    checkpoint=existing_core_json, expected_sha256=exact_core_sha256,
    formula_checkpoint=saved["path"], formula_sha256=saved["sha256"],
    compute_device="cpu",
)
continued = resumed.train(
    training_samples, validation_samples=tuning_samples,
    formula_targets=training_targets,
    validation_formula_targets=tuning_targets,
    epochs=10, max_seconds=60,
)
```

Omit `formula_options` on resume: the optimizer configuration and manifests are
immutable. Epochs are additional epochs; a partial-epoch cursor finishes that
epoch before proceeding. An optional `max_optimizer_steps` bounds numerical
work. The deadline is checked during preparation and at batch boundaries;
in-flight tensor operations, final validation and serialization may finish
after it. Do not interpret it as an operating-system kill deadline.

After attachment, `encode`/`decode` reconstruct the learned projected embedding;
`evaluate`, common `infer`, and default `decode_formal_logic` use the learned
projection/head. Their joint inference report includes formulas, reconstructed
embeddings, reconstruction MSE and explicit authority flags. This differs from
the old numerical `AutoencoderEvaluation` object. Explicit compiler modes remain
available for a separately labeled comparison; compiler output is never a
fallback for failed learned generation. Batch inference accepts at most 128
samples; facade training accepts at most 256 per split. Batch calls also amortize
the exact numerical-core hash check.

`state.save_json` remains the historical numeric-state API and does not save the
new head. Always retain the formula sidecar for joint training. Existing fleet
jobs are not silently redirected, and the prior source-conditioned/native
formula transport codec does not accept this new checkpoint schema. Fleet/Hub
adapters for this profile require an explicit integration before a distributed
campaign can use it.

Cached inference checks its actual tensor contents against the loaded checkpoint
before and after each batch. This also detects writes through `tensor.data`,
which Torch version counters can miss. Checkpoint and codec properties return
defensive copies. Editing the cached model directly requires an explicit new
checkpoint and attachment; a changed model cannot keep reporting the old hash.
The joint facade also rejects a sidecar that no longer matches its cached head
before inference, projection, saving or resumed training. The tensor reference
uses one additional model-sized allocation; checks run per batch, not per token.

Finite stored weights can still overflow during projection. Formula inference
now abstains on a nonfinite projection or decoder condition before activation
saturation can hide that failure. Projection-only inference raises on nonfinite
output. Neither path falls back to compiler output or an input vector. These are
execution-integrity checks; they do not establish formula fidelity or alter the
training objective, vocabulary, temperature, token bound or qualification gates.

Lake must check actual generated output through the decoded-schema evaluator.
A grammar check, low reconstruction loss, formula loss, registry row or schema
typecheck alone does not establish a legal admit or source meaning. Qualification
flags stay false and the Constitution remains unformalized.
