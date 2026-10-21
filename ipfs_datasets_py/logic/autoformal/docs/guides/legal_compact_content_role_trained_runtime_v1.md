# Role checkpoint model-only inference v1

`legal_compact_content_role_trained_runtime_v1` is an explicit consumer of the
intact `legal-compact-role-training-checkpoint/v1` checkpoint. It validates the
role checkpoint through its own owner and restores only the current model into
the existing prepared numerical lifetime. It does not construct or restore Adam,
perform a training objective, convert the checkpoint to an older schema, or
change default dispatch.

## Public operations

```python
inspect(checkpoint, *, expected_checkpoint_sha256, expected_policy_sha256)

score(checkpoint, conditioning, prefix_ids, context_raw, *,
      expected_checkpoint_sha256, expected_policy_sha256,
      expected_context_sha256, prefix_origin, context_origin)

score_prefixes(checkpoint, conditioning, prefixes_ids, context_raw, *,
               expected_checkpoint_sha256, expected_policy_sha256,
               expected_context_sha256, prefix_origin, context_origin)

generate(checkpoint, conditioning, prefix_ids, context_raw, *,
         expected_checkpoint_sha256, expected_policy_sha256,
         expected_context_sha256, max_new_tokens,
         prefix_origin, context_origin)
```

All operation inputs remain under the role owner's existing bounded fast custody
context. Independent expected checkpoint, role policy and context hashes are
required. The complete immutable zero-step basis, role inventories, current
weights, historical optimizer state, objective and lineage are validated before
any model construction. That validation reads exposed targets; the report states
this separately from numerical inference.

`inspect` constructs no model and returns the role lineage and the hash and field
inventory of the target-free serving view. Runtime values are still declarations
until an actual model-only forward verifies them.

`score_prefixes` accepts 1–64 supplied prefixes, each 1–512 IDs, with one shared
384D conditioning vector and independently pinned context. It performs one
full-prefix forward for each prefix with nonempty scope-allowed choices. Its
`scores` list exposes the final-position vector of 537 logits, output shape,
allowed-token prefix report, restore and reuse observations. It selects no token.
`score` returns the same population report with one member. Whole versus split
scoring compares the same supplied prefixes in a single call or separate calls;
it does not imply incremental hidden-state caching. The unchanged numerical
owner exposes only the final-position logits; an external qualified observation
hook is needed to retain all sequence positions from that actual forward.

`generate` allows 1–64 newly selected tokens and preserves the unchanged lexical
scope filter, deterministic token selector and final typed decoder. A single
private model restore serves all forwards in that call. Each forward consumes
the complete supplied-or-generated prefix. `trace` retains prefix IDs, actual
full537 final-position logits, selection, prefix report, next prefix and model
restore/reuse flags. Terminal and blocked supplied prefixes construct no model.
Whole two-token versus two separate one-token continuations can qualify exact
continuation and lifecycle behavior without claiming full reconstruction.

## Target-free numerical view

The new `legal-role-model-serving-view/v1` is a field projection, not a relabeled
checkpoint. It contains current runtime, configuration, fixed codec, model state
and parameter order, plus the role/basis/current-weight lineage commitments. It
contains neither basis text or target rows/inventories nor optimizer tensors.
Hash commitments to those histories remain provenance, not model inputs. The
existing `_PreparedModel` receives only this view and the supplied conditioning
vector; the view has an independent immutability fence. Only conditioning and
prefix IDs enter numerical forward computation.

The numerical owner retains its byte-pinned model construction, exact state
restore, evaluation mode, immutable parameter/buffer/module inventory, CPU RNG,
source and runtime guards. Its closing check runs in `finally` on both success
and failure. No private model lifetime or hidden state escapes a public call.
Role, prepared runtime, token and scope dependency sources remain pinned and are
reported; caller and captured operation data remain fenced throughout.

## Scope of the result

Role objective weights are training provenance and never rescale inference
logits. `baseline` and `semantic_priority` retain distinct role checkpoints and
policies while consuming the same grammar and scope policy. Exact output parity,
finite scores and typed syntax do not establish statutory interpretation, source
encoding, reconstruction improvement, graph admission or Lean proof validity.
Every authority field remains false, and the public operations grant no native
resource admission. Callers must use the existing resource/source owner for
bounded qualification work.

The checkpoint validator's target access is explicit. The serving view is
target-free, but externally supplied prefixes and contexts can themselves be
exposed labels and must declare that origin. Conditioning, context permission
and prefix-origin declarations are not authenticated by this API.

This additive consumer is specific to the qualified authored 384D/fixed537
checkpoint geometry. It does not qualify 768D, 4096D, USCode source/span/entity
joins, repository-trained source encoders, or learned formalization accuracy.
