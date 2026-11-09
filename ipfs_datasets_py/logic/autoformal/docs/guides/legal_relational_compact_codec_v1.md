# Compact relational target transport

`ipfs_datasets_py/logic/formalization/autoencoder/legal_relational_compact_codec_v1.py`
provides a reversible, fixed serialization of the existing authored relational
request. It reuses the public
[relational byte-target owner](legal_relational_decoder_target_contract_v1.md)
and its TypedExpression and relational validation. It introduces no AST,
lowerer, alpha-equivalence comparator, semantic action language, trained model
or numerical decoding head.

The original byte-target and example owners belong to the historical source
generation `ff8a01fd04c741f892572e7f28cba777d4dfd472`. Their recovery covers
14 exact source, test and documentation files. Recovery of those bytes and
qualification of this compact successor are separate activities. At the time
of this guide's staging, compact qualification and measured replay results
remain pending. This guide makes no test-pass, compression-result or model
performance claim.

The supported request remains `legal-relational-norm-request/v1`, with
`interpretation_status="authored_unreviewed_declaration"` and
`source_binding=null`. The existing relational owner determines supported
constructors, sorts, signatures, binders, modal payloads and roles. A projection
cannot make unsupported source binding, nonempty metadata or unsupported
syntax admissible. Every field accepted by that owner is reconstructed exactly,
including explicit empty metadata.

The versioned identities are:

| Identity | Value |
| --- | --- |
| Codec schema | `legal-relational-compact-codec/v1` |
| Compact payload schema | `legal-relational-compact-payload/v1` |
| Encoding report schema | `legal-relational-compact-encoding/v1` |
| Candidate report schema | `legal-relational-compact-candidate/v1` |
| Profile | `authored-object-relational-deontic/v1` |
| Format | `fixed-json-relational-compact-utf8/v1` |
| IR family | `legal_ir` |
| Decoder task | `typed_relational_IR_reconstruction` |
| Underlying owner codec schema | `legal-relational-target-codec/v1` |

The builder publishes fixed `key_map`, `string_constants` and
`container_constants` tables. They are established before any target is
supplied. Ordinary dictionary keys use their declared one-character aliases;
other keys use a colon followed by their complete original spelling. A known
schema/interface string uses a sole `@` field containing its integer table
index. Exact fixed Bool/Object sort and tdfol family/profile dictionaries use
a sole `!` field containing their integer table index. Arrays retain their
original order and nesting. Empty dictionaries remain empty dictionaries.

The complete compact payload has exactly `schema` and `request` fields. Its
`request` contains the projected original request. Decoding rejects unknown
unescaped keys, escaped aliases for known keys, marker dictionaries with extra
fields, boolean or out-of-range marker indices, duplicate JSON keys and
noncanonical alternative projections. Expansion must project back to the same
compact JSON value, then the original public byte-target owner validates the
complete reconstructed request.

No table is derived from target IDs, names, roles, binder topology or the
expected answer. Expression, signature, node and extension IDs remain the
supplied IDs. Binder names and repeated variable occurrences remain distinct.
Signature declaration order, ordered argument roles and predicate argument
order are retained. Modal placement and connective nesting are preserved:
`P(A) implies B` and `P(A implies B)` remain different targets. No sorting of
operands, alpha-renaming, association flattening or reference-based repair is
performed.

Exact reconstruction refers to the **complete canonical request**, not the
original transport's whitespace. Canonical JSON uses UTF-8, sorted object keys,
no insignificant whitespace and unescaped non-ASCII characters, while retaining
all JSON values and array order. Original key order, indentation and equivalent
JSON escape spelling may differ. Encoding reports retain separate
`original_request`, `canonical_request` and `compact_request` byte-count/SHA256
bindings, plus canonical and compact UTF-8 text. Preserve the original raw
artifact separately when original transport reconstruction is required.

The public API is:

```python
build_relational_compact_codec_v1()
relational_compact_codec_sha256(codec)

encode_relational_compact_target_v1(
    request_raw, *, expected_request_sha256, codec, expected_codec_sha256
)
relational_compact_encoding_sha256(report)
validate_relational_compact_encoding_v1(
    report, request_raw, *, expected_encoding_sha256,
    expected_request_sha256, codec, expected_codec_sha256
)

decode_relational_compact_candidate_v1(
    generated_ids, *, codec, expected_codec_sha256
)
```

Independent expected hashes should come from retained caller commitments.
The encoding hash checks a closed report; complete original-input validation
also regenerates the encoding through the underlying owner and requires an
exact report match. Rehashing altered report fields cannot substitute for that
replay. Public import and fixed-codec construction use standard-library code;
the original operation owner loads lazily after input preflight. The compact
source is checked for change, and the original owner's existing source checks
remain in force. The original codec must be the actual sibling package owner;
a staged standalone file mixed with unrelated package imports is refused.

The vocabulary remains a fixed 259-entry **byte vocabulary**: PAD=0, BOS=1,
EOS=2, and byte values 0–255 represented by IDs 3–258. An encoded compact target
contains BOS, one ID per compact UTF-8 byte, and EOS. Its length is therefore
`compact_request["bytes"] + 2`; the original byte target uses
`canonical_request["bytes"] + 2`. These are directly comparable serialized
byte-sequence lengths. They are not encoder-token counts, provider-token
counts, checkpoint output budgets or a measured training/inference speedup.

| Complete bound | Limit |
| --- | --- |
| Original request, canonical request or compact payload bytes | 524,288 each |
| Offered generated sequence | 524,290 IDs |
| Fixed codec JSON | 32,768 bytes |
| Encoding/candidate report JSON | 8,388,608 bytes |
| Ordinary JSON traversal budget | 100,000 items, including dictionary keys |
| JSON depth | 96 |
| Report traversal allowance | Ordinary budget plus 524,290 sequence items |

Reconstruction also checks a bounded expansion before final canonical-byte
validation. The underlying relational and byte-target owners retain their own
bounds. These limits are integrity caps, not evidence that any retained model
can generate that many IDs. The actual input producer, tokenizer, checkpoint,
target format and complete output budget must be qualified independently.
Do not raise caps or silently truncate a target to make a model appear
compatible.

Generated intake accepts only the offered ID list and independently committed
codec. It accepts no reference request, expected AST, target lookup or identity
map. Reports retain the offered `generated_ids` and framing observations.
Where a valid byte frame can be interpreted, reports also retain the exact
generated bytes as hexadecimal, their byte count and SHA256, and UTF-8 text
when decodable. Noncanonical transport whitespace is retained in that original
generated-transport record; successful reconstruction has a separate canonical
request hash.

| Result | Status/reason behavior |
| --- | --- |
| Empty output | `incomplete` / `missing_bos_and_eos` |
| Byte frame without terminal EOS | `incomplete` / `missing_eos` |
| Invalid token/frame arrangement | `rejected` / `invalid_frame` |
| Complete frame with invalid UTF-8 | `rejected` / `invalid_utf8` |
| Invalid compact JSON | `rejected` / `compact_json_rejected` |
| Invalid payload/alias/marker/projection | `rejected` / `compact_projection_rejected` |
| Reconstructed request refused by the original owner | `rejected` / `typed_request_rejected` |
| Complete reconstructed request accepted by the original owner | `valid_candidate`, reason null |

Whole-input overflow and malformed API contracts raise a `ValueError`-family
refusal instead of returning a truncated candidate. Unexpected exceptions that
escape the original owner's API and interruptions propagate; they are not
inferred model outcomes. Callers
must retain those events separately and preserve the complete selected
population. Keep incomplete, rejected, invalid UTF-8, overflow, cancellation
and infrastructure failures visible in their original categories. Do not
replace them with empty valid requests, omit them from a denominator or relabel
them as abstention. Extending the existing byte-preserving inference/accounting
bridge remains separate work; this codec creates no new denominator owner.

Every returned encoding/candidate report keeps all authority flags false,
including `provider_tokens_measured`, and both `training_mask` and
`evaluation_gold_mask` equal to integer zero. A valid candidate establishes
supported serialization and owner validation only. It supplies no reviewed
meaning, statutory source fidelity, governing use, graph admission, training
eligibility, backend execution or Lean proof authority. Source/context-only
model input, labels, exposure, physical-source grouping and external provenance
remain with the existing example and eligibility owners.

The compact format and the original
`canonical-relational-request-utf8/v1` format are separate decoder contracts.
Sharing the 259 byte IDs does not make their target sequences, learned grammar
or checkpoints interchangeable. A checkpoint qualified for the original byte
profile is not thereby qualified for compact output. Any later reuse must
declare the exact task/profile/schema/format/codec and input producer, retain
an explicit parameter and vocabulary compatibility ledger, and qualify its
complete output behavior. This transport implementation performs no fitting
or checkpoint migration.

## Qualified transport and remaining integration

The October 17, 2026 current-source qualification passed **487 tests** across
seven complete selected files, including 50 compact-codec cases. No cases were
skipped or deselected. The existing native runner admitted one CPU slot,
2,048 MiB memory, two process slots and 128 MiB storage. It completed, retained
its evidence and reported source/native/storage release. These are cooperative
limits and monitored process-group usage, not kernel sandbox guarantees.

The separately identified retained replay reconstructed both original §7213
hypotheses exactly, including their different permission/implication scope.
A and B remain two hypotheses for one physical statutory occurrence. The replay
fed encoded retained targets into candidate intake; it did not generate model
predictions or establish statutory meaning.

| Retained hypothesis | Original serialized bytes | Canonical bytes | Compact bytes | Original byte IDs with BOS/EOS | Compact byte IDs with BOS/EOS |
| --- | ---: | ---: | ---: | ---: | ---: |
| A | 16,684 | 7,254 | 2,450 | 7,256 | 2,452 |
| B | 16,864 | 7,254 | 2,450 | 7,256 | 2,452 |

The measured reduction is **66.2073% of framed byte IDs relative to the existing
canonical byte codec**. Whitespace removal from the original pretty-printed
requests is excluded from that comparison. The compact targets still exceed
both 512- and 1,024-ID budgets; no decoder budget was changed. Actual model
or provider tokenizer counts, model accuracy and speedup remain unmeasured.
Both eligibility masks stay zero. Unary definition bodies retain their separate
profile and were not projected by this codec.

Exact retained request SHA256 values:

- A: `4fbdc25cf494a5ab00f0ceff2c7ef6a0f1ba7998969a4e8b9ccee5f0eb299f89`
- B: `210fb6e56f4e10be42e35ea6fb8b48c32168c7de105c806a1563d7138c7eaa33`

The native request is
`91fb31cb6a0999053dea5a11b7f1a6b461bcb44ec5372462b07d9218f98677d8`;
its qualification receipt is
`e037cca297825e084597cd1f89d401566d3762e91765ad644fe1c803dac5e927`;
the retained transport result is
`c6bb96387247aa2bdba1956569545804e0691d9d19c7b817cecfadf0684f7042`.
The local workspace package is
`artifacts/legal-ir-relational-owner-recovery-20261017T151703Z/README.md`.
It preserves earlier unsuccessful validation attempts and source provenance;
repeated test runs are not additional independent cases.

Next, add an explicit compact-label companion to the existing source-separated
example owner, and extend the existing batch observation boundary to retain
invalid bytes, IDs and framing without changing its population accounting.
The original example owner accepts its original byte-codec contract only;
passing this compact codec into it unchanged is unsupported. Qualify a complete
structural-token or composition profile and its actual decoder compatibility
before attempting targets beyond an inherited output budget. Source review,
applicability, definition composition, exposure/splits and semantic eligibility
remain separate gates.
