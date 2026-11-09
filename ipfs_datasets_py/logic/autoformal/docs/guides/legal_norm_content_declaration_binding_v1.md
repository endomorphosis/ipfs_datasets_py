# Bind retained declarations to current norm candidates

`legal_norm_content_declaration_binding_v1` connects one exact
[unsigned content declaration](legal_norm_content_declaration_v1.md) to a
fully replayed current norm candidate. It preserves both evidence generations
and makes their obligation correspondence explicit. It does not authenticate a
declaration author, select a meaning, apply a definition or grant training
authority.

The retained §7213 declarations and fresh norm preparations have matching
source, AST and context payloads, but different correspondence and preparation
identities. Their issue and question slot IDs derive from those correspondence
generations. Equal text or AST hashes cannot make those preparation identities
interchangeable.

## Supply both complete generations

Supply six exact UTF8 JSON byte strings and independently obtained raw and
canonical pins for each:

| Pin-map key | Exact bytes |
| --- | --- |
| `declaration` | Complete unsigned declaration report. |
| `declaration_request` | Its original declaration request. |
| `retained_norm_preparation` | Complete historical norm preparation. |
| `retained_definition_evidence` | Complete historical definition-evidence report. |
| `current_preparation` | Complete current norm preparation. |
| `dependency_manifest` | The current preparation's unchanged dependency manifest. |

Every pin-map entry has exactly `raw_sha256` and `canonical_sha256`. Raw pins
identify the offered serialization; canonical pins identify its complete JSON
value. Neither is a substitute for the other. Use retained qualification and
input receipts as the independent evidence basis; hashing an altered input does
not establish that it belongs to the original generation.

`current_build_inputs` contains the complete arguments accepted by
`build_norm_review_subject_v1`: independent preparation/manifest pins, required
dependency IDs, original correspondence and its replay inputs, and complete
source-context inputs. The expected preparation hash equals its complete
canonical input pin. The builder's expected manifest hash is the manifest's
existing embedded payload digest; the pin map hashes the complete manifest,
including that digest. Public validation checks their consistency rather than
treating these two manifest hashes as equal. The companion uses the public current
[response-template builder](legal_norm_content_responses_v1.md) to replay that
generation rather than accepting a report-shaped object on its own.

```python
from ipfs_datasets_py.logic.autoformal import legal_norm_content_declaration_binding_v1 as binding

report = binding.prepare_norm_content_declaration_binding_v1(
    declaration_raw, declaration_request_raw,
    retained_norm_preparation_raw, retained_definition_evidence_raw,
    current_preparation_raw, dependency_manifest_raw,
    expected_input_pins=independent_input_pins,
    current_build_inputs=current_build_inputs,
)
report_sha256 = binding.norm_content_declaration_binding_sha256(report)
binding.validate_norm_content_declaration_binding_v1(
    report, declaration_raw, declaration_request_raw,
    retained_norm_preparation_raw, retained_definition_evidence_raw,
    current_preparation_raw, dependency_manifest_raw,
    expected_report_sha256=report_sha256,
    expected_input_pins=independent_input_pins,
    current_build_inputs=current_build_inputs,
)
```

The validator requires an independent complete-report pin and regenerates the
binding from all original inputs. The example's report digest shows the API;
downstream intake must receive the expected digest independently of an offered
report. Rehashing a modified result cannot replace regeneration.

## Exact correspondence and preserved differences

The binding compares the complete source/context/coverage and typed/native
payloads. This includes physical source records and selectors, scope
declarations, original source-input commitments, anchors, inverse source/typed
rows, binder/argument/ancestry inventories, context nominations and unresolved
issues. It uses literal equality, without alpha normalization, variable-name
matching or semantic equivalence heuristics.

Only explicit producer and derived generation fields may differ. Both values
remain identified, their internal cross-commitments are checked where the
complete corresponding evidence is supplied, and the remaining payload must
match completely. Dependency populations and categories are retained; the
current manifest is not extended with historical declaration artifacts.

Every original obligation has one ordered historical-to-current pairing.
Original context records, issue records and question names must agree exactly.
The ledger retains both slot identities and complete obligation commitments;
neither source packet is rewritten or relabelled. Missing, reordered, duplicated
or meaning-changing material cannot be repaired by dropping a row.

Historical mapping-request raw hashes and lengths remain historical declared
observations when their original bytes are not supplied. Canonicalizing a parsed
request does not reproduce an arbitrary original serialization. Current
mapping bytes are verified through the complete current-owner replay. Original
historical producers are not reexecuted. Original availability observations
remain part of their historical generation. The separate
[exact producer recovery](../../../../../../../artifacts/legal-ir-historical-producer-recovery-20261016-01/README.md)
now supplies a successor custody record for the formerly unavailable bytes;
consumers must bind that new evidence explicitly. Byte recovery does not
reconstruct the historical execution or change this binding's input identities.

## Use with signed response bodies

A caller can provide the exact validated binding bytes and complete declaration
bytes as separate supporting artifacts in the existing norm-response protocol.
Explicit evidence references inside a response body can identify both artifacts;
the signed original-domain claim must still bind that whole exact response body.
The binding does not insert references, create reviews or alter existing
subjects and signatures.

Attachment references establish which bytes a reviewer supplied. They do not
authenticate the unsigned declaration's author or imply that the reviewer
endorsed every nested proposal. Evidence references inside the declaration
remain declared and unverified; referencing its whole body does not verify those
nested evidence bodies. Existing response evidence-list and aggregate byte
bounds still apply, without flattening or truncating the declaration to fit.

The response profile continues to require definition applicability to remain
unresolved and governing-definition use to remain null, even when a retained
declaration proposes an applicable alternative. All competing definitions and
exact typed-use proposals remain retained evidence. Separate adjudication,
complete meaning-unit geometry, governing applicability and supported typed
definition application must precede semantic acceptance.

## Bounds and outcomes

Strict duplicate-free UTF8 JSON transport and inherited byte, depth and
population bounds apply. Oversized inputs are refused rather than truncated.
Input snapshots and direct/inherited producer checks surround preparation and
final serialization. Full-report digests use the existing norm canonical UTF8
recipe; raw evidence references hash exact bytes, while the current signing
subject keeps its existing review digest recipe.

The result supplies a compatibility binding, not an accepted interpretation.
Semantic, consumer, training and evaluation-gold authority remain false/zero.
Historical definition replay, actual reviews, content adjudication, graph/Lean4
admission and scientific training remain separate work. Qualification evidence
is maintained in the enclosing workspace's
[qualification record](../../../../../../../artifacts/legal-norm-content-declaration-binding-20261016-01/README.md).
All 64 focused tests and both retained §7213 preparation/regeneration replays
passed. Each actual binding retains 19 ordered obligation pairs, 13 changed
slot IDs and both original producer generations, with no actual reviews,
meaning decisions or applied definitions.
