# Optional catalog tokens v1

`ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_catalog_tokens_v1`
provides an explicit grammar for compact outputs that reference a nonempty
subset of a supplied predicate catalog. The full catalog is validated, retained,
and committed even when some declarations are unused. The existing compact
content and token owners retain their requirement that every declared predicate
occur; this module does not change their source or contracts.

This is a grammar and typed reconstruction interface. It does not execute a
model, train a head, establish a source-derived context, grant inference-context
permission, or supply legal or proof authority.

## Public interfaces

The six public functions are:

```python
prepare_catalog_context_v1(
    signature_raw, argument_roles_raw, *,
    expected_signature_sha256, expected_argument_roles_sha256,
)
build_compact_catalog_token_codec_v1()
compact_catalog_token_codec_sha256(codec)
encode_compact_catalog_tokens_v1(
    content_raw, context_raw, *, expected_content_sha256,
    expected_context_sha256, codec, expected_codec_sha256,
)
compact_catalog_allowed_token_ids_v1(
    prefix_ids, context_raw, *, expected_context_sha256,
    codec, expected_codec_sha256,
)
decode_compact_catalog_tokens_v1(
    generated_ids, context_raw, *, expected_context_sha256,
    codec, expected_codec_sha256,
)
```

Raw inputs are bounded exact UTF-8 JSON bytes with independently supplied
lowercase SHA256 values. Generated IDs are a bounded list of plain integers.
There is no target request, expected tree, identity sidecar, source-permission
receipt, or answer dictionary argument on the generation interface.

`prepare_catalog_context_v1` delegates the complete supplied signature and role
ledger to the existing public `legal_compact_content_v1.prepare_context_v1`.
Its return value is exactly:

```json
{
  "schema": "legal-relational-compact-catalog-context/v1",
  "selection_policy": "referenced_predicates_in_catalog_order/v1",
  "catalog": {"schema": "legal-relational-compact-context/v1", "signature": {}, "argument_roles": []}
}
```

The empty signature and role list above are placeholders for the complete valid
old context; they are not admissible inputs. Context preparation removes the
supplied signature ID as the original owner does. It does not determine whether
the names, arities, ordered roles, or catalog selection came from permitted
source material. Callers must preserve those separate provenance facts.

## Separate grammar and codec commitment

The profile is `object-relational-compact-catalog-tokens/v1`; the format is
`fixed-json-lexical-compact-catalog/v1`. The codec schema is
`legal-compact-catalog-token-codec/v1`. It retains the original 537 ordered lexical
tokens and PAD/BOS/EOS IDs 0/1/2, and records the original codec hash in
`parent_codec_sha256`. Its own complete canonical codec hash differs because the
grammar, context schema, and selection policy differ.

The generated content still uses `legal-relational-compact-content/v1`. Predicate
indices address the full supplied catalog. The original pinned parser handles
constructors, lexical variable binding, quantifier numbering, arity, node and
depth limits. A local subclass changes only the document rule: a complete
document must quantify and reference a nonempty declared subset. It need not
reference every declaration. No global parser, old codec, or old owner is
patched.

No numerical head or checkpoint is admitted by matching the 537 output width.
The existing head, selector, checkpoint, training-example and batch interfaces
remain incompatible with this new profile until their own explicit integration
and qualification. The old codec is refused by the new interface and the new
codec is refused by the old interface.

## Complete-candidate projection and identity

For a complete candidate, the result preserves the entire input wrapper under
`catalog_context`. Its `selection` records:

- `catalog_content` and its canonical hash, containing the original generated
  catalog indices, binders, modal scopes and ordered arguments;
- ascending `selected_catalog_indices`, ascending `unused_catalog_indices`, and
  a full `catalog_to_effective` list with null for each unused declaration;
- `selected_role_row_indices`, locating the original role-ledger row for each
  selected declaration;
- `effective_context` and `effective_content`, their hashes, and the complete
  public original-owner `prediction` with `prediction_sha256`;
- `catalog_prediction_id`, committing the full original context and content.

The effective signature and role rows both follow selected catalog order.
Original role labels retain their order within each row. Only predicate indices
are remapped in the content tree. The complete original context, including its
original role-ledger row order, remains present in the outer report. The
unchanged public `decode_prediction_v1` then checks and materializes the
effective context and content through the existing typed AST and strict
relational owner.

The catalog prediction ID is `compact-catalog-prediction-v1:` followed by the
SHA256 of the canonical JSON object:

```json
{
  "schema": "legal-compact-catalog-prediction-identity/v1",
  "selection_policy": "referenced_predicates_in_catalog_order/v1",
  "codec_sha256": "<new complete codec hash>",
  "context_sha256": "<complete original wrapper canonical hash>",
  "content_sha256": "<original catalog-index content canonical hash>"
}
```

Changing an unused declaration or its roles changes this outer identity. The
effective request, typed AST, or their identities may remain identical when an
unused catalog entry changes. Those effective identities do not establish the
association with the full catalog: consumers must retain and verify the outer
report and `catalog_prediction_id`.

Generated IDs and binder identities in the typed prediction are fresh. An
archival exact-identity inverse of a separately supplied request remains a
different interface. Encoding an offered compact target here is useful for
transport and grammar checks; it does not make a target-derived catalog an
independent inference input.

## Evidence, bounds and failures

Encoding reports use `legal-compact-catalog-token-encoding/v1`; prefix reports
use `legal-compact-catalog-token-prefix/v1`; candidate reports use
`legal-compact-catalog-token-candidate/v1`. Reports distinguish raw context-byte
SHA256 from canonical context SHA256. Encodings also retain the original content
raw-byte hash and canonical content. Candidate reports retain the offered IDs,
recoverable lexical text/hex/hash, and framing facts. No input is truncated or
repaired to obtain a candidate.

A prefix report describes only locally admitted next tokens. It explicitly sets
`local_prefix_only=true` and `global_completability_proven=false`. A locally
admitted prefix is not a promise of a complete output within the remaining
budget. Complete candidate status is `valid_candidate`; unfinished framing is
`incomplete`; malformed grammar/framing is `rejected`. Budget exhaustion retains
its distinct reason (`output_limit_without_eos` or
`no_admissible_next_token_within_total_limit`) and has no successful selection.
Incomplete and rejected candidates keep `selection=null` and `counts=null`.

The bounds remain 512 total IDs including BOS/EOS, 512 nodes, depth 48, 64
predicate declarations and arity at most 8. Whole content bytes are bounded at
262,144, whole context bytes at 524,288, codec bytes at 32,768, and full serialized
reports at 2 MiB. The reused bounded JSON primitives retain their own finite
node/depth limits. Whole-input overflow, malformed API types, invalid catalog or
independent hashes, fixed-source failure, and owner errors abort the operation;
they are not classified as model rejection. Interruptions propagate. Invalid
unused declarations are refused even for empty or malformed generated IDs.

The module snapshots the exact fixed old token/content owners and four original
content dependencies before lazy imports, checks loaded origins/import anchors,
and closes the physical source fence after complete bounded serialization.
Operation reports retain all seven source records, including this owner. These
checks bind this source generation and its finite trusted dependencies; they do
not authenticate a hostile interpreter or establish source-text semantics.

Every report authority field is false. `training_mask` and
`evaluation_gold_mask` are integer zero. The included original prediction has
generated identity, a null source binding, and no training or proof authority.
Codec flags also deny numerical compatibility and verified inference context.

## Required later integration

This slice supplies no production consumer or new numerical execution path.
Before model use, the existing owners need explicit new-profile support for
context preparation/provenance, target encoding, allowed-token selection,
head/checkpoint compatibility, and denominator-preserving batch intake. Such
integration must retain the whole catalog and outer prediction identity,
distinguish source-only context from target-derived labels, and keep missing or
unqualified context outcomes in the selected population. It must not silently
convert the existing all-predicates profile or reinterpret its historical
results. Any numerical validation, training, legal review, source-permission
qualification, or Lean admission requires its own separate evidence.
