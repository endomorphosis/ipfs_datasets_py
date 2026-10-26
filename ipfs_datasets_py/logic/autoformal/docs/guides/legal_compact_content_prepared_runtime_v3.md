# Operation-local prepared compact inference v3

The additive `legal_compact_content_prepared_runtime_v3` consumes the existing
trained compact v2 checkpoint without changing its weights, codec or optimizer
history. Existing v2 callers remain available and unchanged. This successor is
an explicit API; installing it does not change the default LegalIR loader.

Each bounded generation validates the complete checkpoint and restores at most
one private evaluation model. Subsequent decisions use that model with the full
current prefix. The session ends with the public call: there is no cross-call
cache, public mutable session or incremental hidden-state algorithm. Source,
input, runtime, model-state and RNG checks remain part of the operation.

The explicit public operations are:

- `inspect_compact_content_prepared_checkpoint_v3`
- `score_compact_content_prepared_v3`
- `generate_compact_content_prepared_v3`
- `compact_content_prepared_generation_sha256`
- `validate_compact_content_prepared_generation_v3`
- `prepare_compact_content_prepared_batch_prediction_v3`

Generation accepts the original checkpoint, conditioning vector, prefix IDs,
raw context, independently retained checkpoint/context hashes, token allowance,
and prefix/context origin. Structural inspection and terminal/refused prefixes
must allocate no numerical model or optimizer. A nonterminal call verifies the
live numerical runtime and executes current saved weights. Reports distinguish
preparation/model restoration from actual forwards and preserve all emitted
prefixes, logits, selections, lineage and exposure declarations.

Replay creates a fresh operation. The batch adapter retains its required
original-input replay; reuse within one call does not waive validation of a
later call. Comparison with v2 must account for deliberately different v3
schema/profile and producer identities, while checking identical numerical
and selection semantics under the declared runtime.

This remains the fixed 384-conditioning, 537-token, 512-ID compact profile.
Dimensions alone do not establish compatibility with genuine GTE embeddings,
768D or native4096 profiles. No encoder, training, source meaning, context
permission, held-out performance, graph admission or Lean proof is established
by this optimization. All semantic authority flags and training/gold masks
remain unchanged in meaning.

Qualification must compare actual v2/v3 scores and bounded trajectories,
terminal/refusal behavior, mutation detection, restore counts, RNG preservation
and end-to-end elapsed times. Passing those checks demonstrates an inference
engineering result, not improved statutory reconstruction. See the parent
workspace `artifacts/legal-ir-prepared-runtime-20261018-01/` for the selected
cohort, original execution outcome and measured costs; source presence alone
is not an execution receipt.

The existing [historical completion metadata](../../../../../docs/autoformalization/evidence/legal-ir-generic-compact-owner-navigation-20261023.json) records34 authored cases,57 GRU forwards and38 restores, with zero training. Its original request pins the current three generic trainer/runtime bodies and the prepared-v3 owning test. These are attributed historical observations, not a fresh qualification of the current dependency closure or the other two owning suites. The four-row varied-population regression is a separate selected test.
