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

## Public source integration and the retained serialization correction (2026-10-24)

The selected binding owner/test are the existing later `7fd416b6…` / `63783a8a…` generation. They are not byte-exact copies of the original `494a2c55…` / `b1843f56…` 64-case generation. The unchanged unsigned dependency and its test remain byte-exact to their separate original 144-case generation.

One existing source line additionally records `/correspondence/input_pins/mapping_request_raw_bytes` as a declared raw-generation field, beside the raw SHA already handled that way. Equivalent parsed JSON can have different exact serializations, hashes and lengths. Both historical and current values remain explicit in their generation records and committed in the difference ledger. Historical raw bytes remain unverified; current supplied mapping bytes still undergo independent raw-pin checks and complete norm/correspondence replay, which derives the current length from those bytes. Parsed mapping content and every unmarked source/context/AST/coverage/dependency field still require literal equality, with all ordered obligations retained. No bound or freshness fence is relaxed.

Three later existing cases cover one equivalent-serialization/ledger positive and two refusals that exchange the complete manifest custody hash with its embedded payload digest. The [fresh accepted integration](../../../../../docs/autoformalization/evidence/legal-ir-norm-content-declaration-binding-public-integration-20261024.json) passed those three cases, twelve original binding controls and six unsigned-declaration controls: 21 cases / 63 phases in total. It does not rerun or pool the original 144/64 cohorts or actual A/B replays. The separately recovered original 67-case qualification of the exact later pair predates this integration and is not rerun or pooled here. The original unsigned qualification retains its documented source/storage/durability scope; the original binding qualification retains its own legacy three-lease and A/B accounting.

The combined fresh profile required four ordinary pytest-module origins and 23 physical execution paths. Dynamic norm/response helpers have checked physical compile/exec evidence without canonical helper-module origin claims. It retained 119 source compile/exec filenames, 114 module entries / 112 physical origins, within 177 source files / 4,540,250 bytes and 203 request pins. The public 1,489-byte pytest helper was checked and executed. Six initializer bypasses were declared; only `logic/__init__.py` was observed and five were unused. Genuine cryptography 49.0.0 Ed25519 API bindings matched Profile G in the selected fixture-signature tests; the worker added no signature operations. Independent operation counts, third-party binary/cached-bytecode, code-object, initial worker-loader and whole-package/environment equivalence remain unqualified.

Original compute/storage and source READs closed, retaining ten regular files / 2,957,288 bytes. The 16.610-second worker and 106.988-second owned interval are nested, not additive. This is current-public engineering evidence, with no actual reviewer, legal-as-of decision, authenticated declaration author, applied interpretation, governing applicability, source/span/entity join, training gain or graph/Lean admission. Applicability remains a separate profile; all four-width prerequisites and semantic/learning/gold masks remain unchanged.

## Recovered serialization-successor history

An indexed-history audit recovered the prior completed 67-case serialization-successor qualification and two A/B binding replays for the exact later `7fd416b6…` / `63783a8a…` pair. Raw source/test, JUnit and saved source/resource/disk evidence match. This predates the fresh21/63 integration and is not reexecuted or pooled with it, original144/64, original applicability65 or fresh20/60. The immutable21 portable keeps its original observation cutoff; current catalog notes/scope now correct that cutoff's incomplete background and the binding component links the [applicability evidence containing this recovered history](../../../../../docs/autoformalization/evidence/legal-ir-norm-definition-applicability-public-integration-20261024.json).

Successful source/native/disk releases remain distinct from two failed claims totaling40,000,000 bytes retained at their original cutoff. No current ledger or recovery assertion is made. Each A/B replay shares one §7213 source paragraph and retains19 obligation pairs,13 changed slot IDs and82 generation differences; it supplies no second statutory use or actual review. The actual retained historical/current mapping lengths did not differ: different raw lengths were covered by the separate engineering fixture. No governing definition or applied meaning follows.
