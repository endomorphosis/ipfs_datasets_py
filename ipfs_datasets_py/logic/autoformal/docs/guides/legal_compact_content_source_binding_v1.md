# Exact native source binding for compact generation

`legal_compact_content_source_binding_v1` binds an explicitly selected source
occurrence to an exact native-profile embedding receipt and to the existing
compact generator's conditioning. It wraps the qualified unbound v1 generation
and batch adapter. Their bytes, source ownership, exposure flags and null encoder
declaration remain intact.

This is a byte, identity and vector consistency contract. It establishes neither
cryptographic inference attestation nor legal meaning, independent context
permission, training eligibility, compact-head training compatibility, held-out
accuracy, convergence or Lean admission. The adapter executes no encoder and
performs no optimizer updates. Binding an actual recorded source vector does not
make an untrained compact head a trained autoformalizer.

## Public operations

```python
prepare_compact_source_conditioning_v1(
    source_request, receipt_ref, *,
    expected_source_request_sha256, input_id, source_resolver,
)

bind_compact_content_generation_to_source_v1(
    report, checkpoint, prefix_ids, context_raw, population_raw,
    source_request, receipt_ref, *,
    expected_generation_sha256, expected_population_sha256,
    expected_source_request_sha256, input_id, occurrence_id,
    expected_checkpoint_sha256, expected_context_sha256,
    max_new_tokens, prefix_origin, context_origin, source_resolver,
)

validate_compact_content_generation_source_binding_v1(
    outer_report, report, checkpoint, prefix_ids, context_raw,
    population_raw, source_request, receipt_ref, *,
    expected_report_sha256, expected_generation_sha256,
    expected_population_sha256, expected_source_request_sha256,
    input_id, occurrence_id, expected_checkpoint_sha256,
    expected_context_sha256, max_new_tokens, prefix_origin,
    context_origin, source_resolver,
)

compact_source_request_sha256(source_request)
compact_source_binding_sha256(report)
```

`source_request` has exactly these fields:

```python
{
    "occurrence_id": "selected-occurrence-id",
    "input": embedding_input.to_dict(),
}
```

`input` is the existing public `EmbeddingInput` serialization, with exactly
`input_id`, `source`, `title`, `section`, `text` and `citation`. Its full typed
`SourceSpan` commits artifact SHA/size, source kind, release, document, language,
citation, identity normalization and exact UTF-8 byte start/end. The derived
`input_id` also commits the input metadata. No text-only join, shortened selector
or inferred citation substitutes for this complete identity.

The explicit `input_id` argument must equal the request's derived identity. The
receipt must contain that input once, and the entire reconstructed input must
equal the request. Different artifacts or selectors containing identical text do
not become interchangeable. Multiple population occurrences may legitimately
name the same explicit source input; they remain distinct occurrence IDs and
population rows.

`receipt_ref` is exactly `{path, bytes, sha256}`. Its path must be an absolute
canonical path without aliases; the file must be regular, single-link and within
the existing 64 MiB receipt limit. The adapter verifies exact raw bytes and file
witnesses before and after consumption. A callable resolver uses the existing
source-artifact contract: given the artifact `{sha256, bytes}`, return the exact
retained artifact bytes or an existing resolvable artifact path. Source hashes
identify supplied bytes, not official legal-source authority.

## Receipt and vector reuse

The adapter uses the existing receipt loader, `EmbeddingInput.from_dict`,
`validate_embedding_inputs`, `validate_sources` and
`legal_native_conditioning.embedding_rows`. It requires:

- The native execution profile for `thenlper/gte-small`, revision
  `17e1f347d17fe144873b1201da91788898c639cd`, with 384 float32 values.
- The exact nine pinned model/tokenizer/pooling assets. Their sorted canonical
  manifest hash is
  `def8d7e04c05560b1d0dd1fa9317be7a59a1ba8399ca725be0ac807a9a264edc`.
- The current pinned producer implementation, with source SHA
  `ce80ed6294009e04580051e6eb06a817d74a8a56f04814ad0a698e3d27dd0d41`.
- Exact source selectors, full untruncated token records and the selected
  result's existing normalized float32 bits.

The runtime asset constant is mutable Python state. Every custody fence checks
its derived manifest against the fixed hash, and the actual receipt manifest
must match independently. Matching a mutable constant alone is insufficient.

For an embedded result, the adapter unpacks the selected stored big-endian bits
without normalization, padding, truncation, conversion to another embedding
space or a new projection. It then calls the existing conditioning reuse API
with only the explicit receipt and requires identical float32 bits. That API's
text-first selection can safely refuse a different vector when identical text
appears more than once. Identical text and identical bits are acceptable after
the explicit input and complete source origin have already been verified.

The bit comparison preserves signed zero. A JSON vector digest and a float32 bit
digest are separate commitments, since their encodings differ. Shape 384 alone
does not establish input-space or trained-checkpoint compatibility.

`encoder_binding_sha256` hashes a separate versioned object containing the
conditioning-space name, model, asset manifest, producer and execution profile.
It is neither a vector digest nor the receipt SHA. The selected receipt SHA,
input ID, source span, token record, native vector bits and JSON conditioning
remain separately linked in the conditioning report.

Historical receipts with obsolete producer source identities refuse. This
version does not replace their producer hashes or introduce a compatibility
exception. Injected fixtures remain ineligible for the native lane.

## Available and unavailable results

The conditioning report uses schema `legal-compact-source-conditioning/v1` and
profile `exact-native-gte-small384-receipt-reuse/v1`. Its `status` is the selected
receipt result's status:

| Status | Conditioning | Source bytes verified | Ready source/receipt binding |
| --- | --- | --- | --- |
| `embedded` | Exact saved 384-vector | true | true |
| `token_limit_exceeded` | null | true | false |
| `missing_input` | null | false | false |

The complete original receipt input count and status counts are retained. An
oversized record retains its original full-token-count/digest evidence; the
adapter never truncates it. A missing result records a claimed unavailable
disposition, not proof of global absence. It does not require resolving that
selected missing source or manufacture successful source verification. Other
nonmissing inputs in the receipt still undergo the existing source checks.

The existing native producer validates all source inputs before loading its
model and cannot naturally produce an unavailable-source row through that
path. A serialized missing-input test is therefore an explicit negative
disposition control, not evidence that native inference produced such a row.

Binding generation refuses unavailable conditioning. It never supplies a zero
vector or filters unavailable rows out of a claimed selected population.

## Generation, context and population

The outer report uses schema
`legal-compact-content-generation-source-binding/v1`, profile
`exact-source-receipt-to-compact-generation/v1` and status
`source_receipt_bound_unqualified_generation`.

The explicit occurrence must equal the request occurrence and a unique row of
the independently pinned, unchanged population. That row's `source_sha256` must
equal SHA-256 of the exact selected source text bytes. The whole population
digest, selected row and original occurrence identity are retained; binding one
occurrence does not generate the remaining rows.

The population row's `context_sha256` is source-context identity. It is kept as
`source_context_sha256`. Compact vocabulary/ordered-role context is a different
object, retained as `compact_context_raw_sha256` and
`compact_context_sha256`. This adapter does not claim an independent source-to-
signature/role derivation or permission review for either context.

The existing public generation batch adapter performs full original-bound
numerical replay using the exact receipt vector, original checkpoint, supplied
prefix, context, generation settings and expected report digest. The wrapper
retains the complete original generation report and complete returned batch
adapter without relabeling either. `initial_prefix_ids`, selected continuation,
raw argmax observations and every numerical score trace retain their existing
meaning.

The nested batch transport still declares `encoder_sha256:null`. It therefore
retains the existing no-credit generation issue. The outer encoder binding must
not be copied into that declaration to obtain comparison credit before a
separate context/evaluation contract is reviewed. Teacher forcing, target
access, prefix assistance and all other existing exposure fields are preserved
verbatim. A BOS prefix and caller-declared no-target context do not independently
prove permission, held-out access policy or legal accuracy.

All authority flags remain false and both training/evaluation-gold masks remain
zero. `source_receipt_binding_verified:true` names a successful embedded
byte/vector join only. `source_encoder_authenticated`,
`runtime_computation_proven` and `runtime_cryptographically_attested` remain
false. A separate fresh owned native execution and saved readback can provide
finite engineering evidence of actual calls without turning those consistency
receipts into cryptographic attestation.

## Bounds, custody and replay

This coordinator reuses the qualified generator's strict bounded ordinary-JSON
copy, canonical wire encoding and fingerprint helpers under exact source pins.
It rejects subclasses, cycles, nonfinite numbers, NUL/surrogate strings,
unbounded integers and whole-input/report overflow before unrestricted
serialization. Limits are 4 MiB for the source request, 64 MiB for a receipt,
128 KiB for population bytes, 192 MiB for the complete operation input and
96 MiB for the complete output. Existing token, checkpoint, prefix and context
limits remain enforced by their original owners. Oversized data refuses rather
than being shortened.

Mutable original inputs and detached snapshots are checked throughout the
operation. Known module origins, source file bytes/witnesses, the receipt and
fixed asset manifest are checked before and after the relevant calls. Source
artifacts are verified again before return. Outputs are detached through bounded
serialization. Exceptions and interrupts propagate; a closing-check failure
cannot return partial evidence or replace an original failure with a success.

The outer validator requires an independently retained outer report hash and
regenerates the entire binding against the same original source request,
receipt, generation, checkpoint, context and population. Resealing a changed
outer report does not bypass that replay. Hash helpers provide canonical
identities, not validation or authority. A caller replacing every original
artifact and every expected pin describes a different operation; this API does
not pretend to detect that substitution without an external retained original.

Named source checks are finite file and origin custody. A fresh owned native
qualification should separately retain genuine package imports, compiled source
captures, actual encoder/decoder calls, exact input/asset receipts, complete test
outcomes and resource closeout. This module provides no fake project namespace,
model factory injection, alternate grammar, optimizer, denominator, provider
tokenizer measurement or proof of convergence.
