# Explicit inference for the LegalIR weighted checkpoint

`ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_content_weighted_runtime_v1`
consumes the complete weighted-training checkpoint. It validates the independent
checkpoint and objective-policy commitments with the weighted owner, then reuses
the existing prepared runtime's private model-only session. The full checkpoint
is passed intact; its schema is never changed to the old v2 format.

The supported model remains the existing authored compact384, fixed537 h0-only
decoder. Both supported objective policies, 1:1 and 1:4 forced/choice weighting,
remain part of checkpoint identity. Inference does not apply those weights to
logits, token selection or grammar. The current trained tensors determine the
scores. Other widths, statutory supervision and source-encoder qualification
remain separate work.

## API

`inspect(checkpoint, *, expected_checkpoint_sha256, expected_policy_sha256)`
performs one complete weighted-checkpoint inspection and returns metadata. It
constructs no numerical model or optimizer.

`generate(checkpoint, conditioning, prefix_ids, context_raw, *,
expected_checkpoint_sha256, expected_policy_sha256,
expected_context_sha256, max_new_tokens, prefix_origin, context_origin)`
continues an explicit prefix for a positive bound of at most 64 new tokens and
512 total IDs. Use `max_new_tokens=1` for a single score/selection observation.
The independent checkpoint hash is over the whole canonical typed JSON value;
retain the separate raw file hash when reading a serialized artifact.

The allowed prefix-origin declarations are `bos_seed`, `authored_fixture`,
`target_derived_label` and `caller_supplied_unverified`. A `bos_seed` prefix must
be exactly `[1]`. Context declarations accept the last three values. These
declarations are not authenticated provenance or permission.

The first active prefix restores one canonical model into evaluation mode. Each
step performs the unchanged full-prefix forward inside inference mode; later
steps reuse that model only within the enclosing call. The existing public
grammar and selector supply allowed tokens and lowest-token-ID tie behavior.
No Adam optimizer, historical moments, training loss, backward or update is
constructed or executed. The private session checks model state, conditioning,
runtime, source/input custody and CPU RNG, and closes even when a call fails.
There is no cross-call model cache or incremental hidden state.

Complete or blocked supplied prefixes retain their disposition without a model
allocation. Their reports do not claim a verified live numerical runtime.
Malformed inputs or changed checkpoint, policy, context or source bindings are
refused before numerical dispatch.

## Reports and exposure

Generation reports use `legal-weighted-content-generation/v1`. They retain the
full checkpoint, policy, weights, codec, inventory, donor, initial/immediate
parent and progress identities, plus context and conditioning commitments.
Each actual numerical step records its offered prefix, all 537 logits and their
hash, the public prefix report and selection, the resulting prefix, and whether
the model was restored or reused. Restore/forward counts are enclosing-call
counts. Terminal/blocked calls have an empty numerical trace and zero counts.

The final prefix and decoded candidate remain unchanged observations. Status is
`supplied_complete`, `complete`, `blocked` or `step_budget_exhausted`; the final
status and public token intake must agree. A budget exhaustion is not converted
into successful completion. Raw maxima in the trace are measured on constrained
prefixes, not a separate unconstrained generation.

The weighted checkpoint contains the exposed training references and inventories.
Its validator reads those references even when the numerical prefix is BOS only.
Reports therefore set `target_access_for_checkpoint_validation=true`, separately
from declared target access in the supplied prefix/context. Only conditioning
and prefix IDs are sent to the numerical model. This distinction does not make
the examples held out or establish reference-data isolation.

## Qualification scope

The enclosing workspace keeps the finite direct/restored inference qualification
under `artifacts/legal-ir-weighted-inference-20261018-01`. Its fixed small roster
checks the actual weighted step-two checkpoint, complete score-vector parity,
whole versus split continuation, and no-work refusals. Original source/native
admission and independent saved readback remain necessary evidence; installing
this source is not a qualification result.

This consumer performs no checkpoint update or production promotion. Numerical
parity and syntactically valid output do not establish improved reconstruction,
statutory fidelity, held-out generalization, scoped graph admission or Lean4
validity. The longer controlled reconstruction comparison requires its own
fixed roster and accounting. Existing adverse BOS results remain separate.
