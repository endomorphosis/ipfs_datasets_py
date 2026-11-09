# Opt-in lexical-scope filter for compact LegalIR decoding

`logic/formalization/autoencoder/legal_compact_content_scope_filter_v1.py`
refines the existing compact token grammar without replacing it. The public
`allowed_token_ids` and `select_token` functions use the explicit policy
`lexically-bound-variable-predicate-arguments/v1`. Their reports include the
original v1 result and the separate filter's source identities.

The previous fixed loss comparison produced four post-training continuations
that selected a predicate before introducing a bound variable. The old local
grammar permitted that choice, then rejected the variable argument. This filter
removes the impossible predicate choice before selection. It also rejects an
already supplied prefix on that branch without editing its token history.

The current context owner supports Object predicates with one to eight variable
arguments. Zero-arity predicates, constants, functions and additional sorts
remain unsupported. The number of distinct bound variables need not equal the
arity: `forall x. P(x,x)` remains valid. Filtering uses lexical scope, so a binder
inside a completed sibling does not remain visible. Connectives, quantifiers,
negation and O/P/F nodes remain available wherever the original grammar permits
them; a child may introduce a quantifier.

## Public calls

```python
from ipfs_datasets_py.logic.formalization.autoencoder import (
    legal_compact_content_scope_filter_v1 as scope_filter,
)

options = dict(
    expected_context_sha256=context_sha256,
    codec=codec,
    expected_codec_sha256=codec_sha256,
)
prefix = scope_filter.allowed_token_ids(prefix_ids, context_raw, **options)
selection = scope_filter.select_token(logits, prefix_ids, context_raw, **options)
next_ids = selection["next_prefix_ids"]
```

Inputs use the existing full 537-coordinate finite-score vector and exact public
codec. Selection takes the maximum over the refined allowed IDs, breaking ties
by lowest ID. It appends at most one token and retains the original full scores,
baseline selection, refined prefix report and resulting prefix. Malformed
inputs, context/hash mismatches and source-custody errors raise. Legitimate
complete, rejected or exhausted prefixes yield a no-selection observation.

For complete decoding, continue to use the original
`legal_compact_content_tokens_v1.decode_compact_content_tokens_v1`. Its typed
AST, binding, all-predicate-use, modal and final validation rules are unchanged.
The filter never introduces a constructor, symbol, binder or target-derived
answer. Local scope feasibility is not a proof that a partial formula can finish
within the remaining budget, or that a valid formula expresses the source.

## Compatibility and integration boundary

The old token/selector modules, codec bytes, 512-ID limit, training inventories
and checkpoint hashes remain unchanged. Existing consumers continue using their
original pinned behavior. This is an opt-in prefix and one-token selection
consumer, not a replacement for the weighted runtime's generation loop.

Using unchanged vocabulary coordinates does not establish unchanged grammar
semantics or qualify a numerical checkpoint. A future generation consumer must
record the checkpoint's original training grammar separately from this inference
filter and retain both source identities. A changed training inventory requires
its own grammar/objective lineage; do not rewrite old inventories or report old
0/2 reconstructions as repaired outcomes.

The implementation reuses the exact pinned selector's input/source validators
and token parser. It subclasses only the parser's tree-entry feasibility check;
the recursive AST parsing and complete checks remain with the old owner. Parser
private APIs are therefore intentionally byte-pinned dependencies. All authority
flags and training/evaluation masks remain false/zero.

Qualification records belong to the
[scope-filter increment](../../../../../../../artifacts/legal-ir-scope-filter-20261018-01/README.md).
Finite parser and saved-score checks do not run an encoder or numerical model,
measure a new reconstruction rate, train another dimension, or establish legal
fidelity or Lean admission.
