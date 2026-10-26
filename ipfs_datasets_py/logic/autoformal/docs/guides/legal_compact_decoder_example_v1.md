# Compact labels beside source-separated decoder examples

`ipfs_datasets_py.logic.autoformal.legal_compact_decoder_example_v1` adds a
compact-label companion to the existing
[source-separated byte example](legal_relational_decoder_target_contract_v1.md).
It keeps that complete example unchanged and projects its validated typed label
through the existing [compact content owner](legal_compact_content_v1.md).
It introduces no AST, renderer, source-join owner, provenance system, eligibility
decision, model or numerical decoding head.

This guide describes a staged contract. Installation and owned qualification
must independently establish behavior for the exact installed generation.
Authored tests, source inspection and successful historical suites do not grant
this new companion runtime qualification.

## Input and label compartments

The sole input compartment is `source_example.model_input`, exactly as supplied
by the original public source-example owner. Its closed fields remain
`source_text` and `context`. The companion does not add a second `model_input`
or copy any compact information into that original compartment.

`source_example` is the complete validated original example, including its old
byte encoding, source identity, physical source group, provenance, unresolved
alternatives, exposure declarations, embedding reference, producer pins, split
and eligibility fields. It is not a reconstructed summary of that example.
An embedding reference remains a declaration; this companion reads no embedding
payload, model weights, dataset row or external cache.

`compact_label` is the complete existing compact projection report. It contains
separate content, signature/role context and an archival identity sidecar. Its
context is **target-derived label information** in this operation. Calling that
field context does not establish permissible inference input or unexposed
information. Any later inference route must separately qualify where its
vocabulary and ordered roles came from. The archival sidecar is for reproduction
of the recorded target, never a prediction aid.

When the original example has no label, `compact_label` is null and compact
projection is not invoked. No fallback target is manufactured. Same-source
alternatives retain their original common group; the companion assigns no
training, tuning or held-out split and selects no governing interpretation.

## Public API

```python
prepare_compact_decoder_example_v1(
    source_example_report, join_report, example_request_raw, *,
    expected_source_example_sha256, expected_example_request_sha256,
    expected_join_report_sha256, join_replay_inputs, codec,
    expected_codec_sha256,
)

compact_decoder_example_sha256(report)

validate_compact_decoder_example_v1(
    report, source_example_report, join_report, example_request_raw, *,
    expected_report_sha256, expected_source_example_sha256,
    expected_example_request_sha256, expected_join_report_sha256,
    join_replay_inputs, codec, expected_codec_sha256,
)
```

The original preparation inputs are the same arguments required by
`legal_relational_decoder_example_v1`; the completed original report and its
independent hash are additional inputs. The companion calls that owner's public
`validate_relational_decoder_example_v1`, which regenerates the full original
source/typed-join/byte-codec chain. A self-consistent altered report cannot replace
the independently committed original inputs.

The report hash helper uses bounded ordinary canonical JSON and imports no
operation owner. It is an identity helper, not schema validation, authentication
or admission. The public validator checks the offered complete report hash,
runs fresh preparation from all original inputs and requires exact report
agreement. Expected commitments must originate from retained caller evidence;
rehashing an altered target does not establish its provenance or permission.

## Closed output

The report contains exactly:

| Field | Meaning |
| --- | --- |
| `schema` | `legal-compact-decoder-example/v1` |
| `profile` | `candidate-source-separated-compact-content/v1` |
| `source_example` | Complete unchanged public-validated original example |
| `source_example_sha256` | Independently expected canonical original-example hash |
| `compact_label` | Complete existing compact projection report, or null |
| `producer_pins` | Combined direct and publicly validated producer hashes |
| `authority` | All flags false |
| `training_mask` | Integer zero |
| `evaluation_gold_mask` | Integer zero |
| `limitations` | Fixed statements of the engineering and authority boundary |

For a labelled example, the projection consumes exactly the original label's
raw UTF-8 request. The companion crosschecks its raw request bytes/hash, complete
canonical request bytes/hash, typed-expression hash, original relational report
hash, original byte-codec identity and archival original commitments. Original
transport formatting and canonical request-value identity remain separate.
Both are retained by their existing owners; no identity normalization is hidden
inside this wrapper.

The compact owner remains responsible for constructor placement, modal scope,
ordered predicate arguments, lexical binder references and exact archival
reconstruction. This wrapper does not widen that owner's syntax. Current
65-character definition-owner predicates and counting/cardinality remain outside
the qualified relational profile. Short-named definition-shaped fixtures do not
establish exact intake from the statutory definition owner.

## Bounds and source custody

Public import and the report hash helper use only the standard library. Before
loading operation owners, preparation detaches bounded ordinary inputs, checks
the complete original-example, join and codec commitments, and checks the
example request's raw bytes and duplicate-free ordinary JSON.

| Complete bound | Limit |
| --- | ---: |
| Aggregate original inputs, including exact byte parameters | 128 MiB |
| Existing complete source-example or join report | 8 MiB each |
| Complete companion report | 16 MiB |
| Relational request | 524,288 bytes |
| Original example request | 16,384 bytes |
| JSON traversal | 2,000,000 items, depth 96 |
| Combined producer map | 256 paths |
| Named producer source | 4 MiB per file |

Whole values refuse on overflow; there is no truncation, implicit cap increase
or best-effort repair. Exact ordinary containers and primitives are required;
cycles, custom subclasses, nonfinite numbers, NULs, invalid Unicode, duplicate
wire keys and out-of-range integers refuse. Byte inputs remain exact bytes in
the original replay arguments. Returned reports contain ordinary JSON only and
are detached before closing fences.

The two direct existing owners are fixed to these raw source generations:

| Owner | SHA256 |
| --- | --- |
| `legal_relational_decoder_example_v1.py` | `4aed1fde35efce9cdd6579be83be6901143003e996611850f6b35f0cce3f705c` |
| `legal_compact_content_v1.py` | `de6495ed91d6842071d0892c4410dfb9243fab658eb22d19635a8db599b4b25e` |

Preparation requires the actual canonical package location, checks its own and
direct-owner bytes/physical witnesses before and after lazy import, and checks
the imported origins. Additional producer paths are read only after their
public owner has successfully validated the output that names them. These paths
must lie in the canonical package, agree on shared hashes and remain stable
through closing fences. Caller originals and detached replay inputs are
fingerprinted before and after operations, including raw byte parameters.

These named source checks are engineering custody checks. They do not prove
executed bytecode for arbitrary preloaded modules, third-party/interpreter
integrity, authenticated producer principals or a hermetic operating system.
Fresh owned qualification with checked-buffer imports supplies its separate
execution observations. Operational exceptions and interruptions propagate;
they are not relabelled rejected model predictions or abstentions.

## Remaining integration

No numerical model runs here. Compact JSON bytes, JSON lexical tokens, byte IDs,
encoder tokens, provider tokens, checkpoint output vocabulary and decode-step
budgets remain different measurements and contracts. This companion implements
no learned compact route, checkpoint migration, training eligibility or savings
claim.

Generated-output intake remains separate work in the existing batch-accounting
owner. It must retain original IDs/bytes, invalid UTF-8, incomplete framing,
missing/duplicate observations and operational failures without shrinking the
selected denominator, repairing a target or using a reference during generation.
This companion creates no new denominator owner. Reviewed meaning, permissible
context, physical/dependency splits, matched learned comparisons, source
equivalence and any convergence theorem still require their own evidence.

## Source-only example with a partial counted label v1

The same companion has an additive counted API. Its source compartment is a
complete, genuinely validated **source-only** original example. The old
example's `label` remains null. A separately supplied counted v2 correspondence
provides the new label; no relational label is relabelled as counted content.
The original v1 APIs and their four exports remain the export prefix. The new
branch leaves the original source-example, Object/Bool compact-content,
normative32, byte, 537-token, head and source-conditioning owners unchanged.

```python
prepare_counted_compact_decoder_example_v1(
    source_example_report, counted_join_report, *,
    expected_source_example_sha256, expected_counted_join_sha256,
    source_example_inputs, counted_join_inputs,
    codec, expected_codec_sha256,
)

validate_counted_compact_decoder_example_v1(
    report, source_example_report, counted_join_report, *,
    expected_report_sha256,
    expected_source_example_sha256, expected_counted_join_sha256,
    source_example_inputs, counted_join_inputs,
    codec, expected_codec_sha256,
)
```

Use the existing `compact_decoder_example_sha256(report)` for complete bounded
report identity. As before, hashing alone supplies no provenance or authority.

`source_example_inputs` is the complete original seven-field preparation call
for `legal_relational_decoder_example_v1`, by name:

| Field | Original commitment |
| --- | --- |
| `join_report` | Complete original v1 source-only join |
| `example_request_raw` | Exact original example-request bytes |
| `expected_example_request_sha256` | Independent raw example-request hash |
| `expected_join_report_sha256` | Independent whole original join hash |
| `join_replay_inputs` | Complete original nine-field v1 preparation inputs |
| `codec` | Original fixed relational byte codec, retained even with no label |
| `expected_codec_sha256` | Independent original byte-codec hash |

The four relational values in that original v1 replay must all be null:
`relational_report`, `relational_request_raw`,
`expected_relational_report_sha256` and
`expected_relational_request_sha256`. Its typed candidate must remain null;
its provenance ledger and introduced typed assumptions must remain empty as
the existing source-only profile requires. The original source-only status, model input,
physical group, source identity, provenance, exposure, embedding declaration,
unassigned split and zero masks remain unchanged.

`counted_join_inputs` is the existing counted join v2's complete original nine
inputs, by name: `scope_report`, `counted_report`, `join_request_raw`,
`expected_join_request_sha256`, `expected_scope_report_sha256`,
`expected_counted_report_sha256`, `scope_replay_inputs`, `counted_request_raw`
and `expected_counted_request_sha256`. The original counted request/report and
join report each keep their independent commitments.

These two chains must commit **the same entire scope report and physical-source
custody**, and their complete `scope_replay_inputs` must be exactly identical.
This includes original sampling report, acquisition descriptor, HTML bytes,
selected unit, raw scope request/declaration, hashes, byte counts and any
explicit limit fields. Equal plaintext, citation, a source-text hash or an
apparently equivalent selector cannot replace those full comparisons.

The source-only example is regenerated by the existing public
`validate_relational_decoder_example_v1`; the counted proposal is regenerated
by `validate_source_typed_norm_join_v2`. The counted label comes from the
existing [counted owner](legal_counted_frame_v1.md#counted-content-and-lexical-round-trip-v1),
using its original request and whole counted-report commitment. Its canonical
identity projection and fixed lexical encoding are then cross-checked against
the independently replayed counted correspondence. Complete original raw and
canonical request/expression commitments and all 49 original node IDs are
checked independently of the projection's own declarations. The actual encoded
IDs must also pass the existing public counted-token decoder; its complete
prediction, counts, canonical content and vocabulary segmentation must agree
with the encoding. There is no alternate
source parser, new AST, expanded grammar or native route here.

The top-level `codec` is the separate counted28 codec. It is deliberately
different from `source_example_inputs.codec`, the original relational byte
codec. The whole qualified counted-codec identity is fixed before operation
owners load. Wrong, altered and legacy codec aliases refuse; a shared alphabet,
vector dimension or vocabulary size supplies no checkpoint compatibility.

### Closed counted output and model boundary

The output has schema `legal-counted-compact-decoder-example/v1`, profile
`source-only-example-with-partial-counted-label/v1`, task
`typed_counted_frame_IR_reconstruction` and status
`unreviewed_counted_companion_prepared`. Its closed fields are:

| Field | Compartment |
| --- | --- |
| `source_example`, `source_example_sha256` | Complete unchanged original source-only example and independent hash |
| `counted_correspondence`, `counted_correspondence_sha256` | Complete independently replayed partial counted v2 proposal and hash |
| `compact_label` | Existing counted content/context/identity projection |
| `compact_encoding`, `codec_sha256` | Existing counted-only lexical encoding and independent codec hash |
| `input_pins` | Full replay-bundle commitments and original request/report/source-group hashes |
| `producer_pins` | Combined trusted actual producer closure |
| `schema`, `profile`, `status`, `ir_family_id`, `task_id` | Explicit counted companion identity |
| `authority`, `training_mask`, `evaluation_gold_mask`, `limitations` | False authority, integer-zero masks and explicit boundaries |

There is no second or top-level `model_input` field. The sole input compartment
is the original `source_example.model_input={source_text, context}`. Counted
signature/role context, original counted request, frame, equality, assumptions,
IDs, sidecar, target tokens and correspondence remain outside it. The source
example's original relational task declaration remains part of its unchanged
source-only archive; the outer counted task does not make that envelope a
counted numerical runtime or an eligible training row.

The counted context remains target-derived label information. Fixed content
and canonical identity restoration are finite engineering properties. They do
not establish source-only context permission, semantic correctness, a blind
split, a complete statutory norm, reviewed applicability, governing definitions,
signed admission, training/gold eligibility, convergence or Lean authority.
All 55 node/binder provenance rows and all original/introduced issues stay in
the complete counted correspondence.

### Producer custody and source conditioning

The additive loader pins the current companion, existing original-example
owner, counted join and counted owner independently of the unchanged v1
loader. It discovers actual scope, source-example and counted producer maps
before offered producer keys can select files to read. Offered maps must match
those trusted maps. Direct and complete producer witnesses, original and
detached inputs and offered validation reports are fenced around public
dependency replay and final serialization. The existing 128 MiB whole-input,
8 MiB original-example, 16 MiB report and 256-producer bounds remain unchanged;
overflow refuses without truncation.

The companion consumes no embedding payload or native receipt and invokes no
source resolver, encoder, numerical head or training owner. Reuse the separately
qualified native384 source-conditioning preparations as their own evidence.
Their explicit `EmbeddingInput`/`SourceSpan` and text/vector commitments are
different from this example's canonical two-field source/context hash and
normalized official-view identity. Matching text or width cannot establish a
crosswalk, and 284/242-byte heading inputs are not the selected 163-character
paragraph packet. No earlier source-conditioning operation needs to be rerun
to qualify this companion.

This operation changes the companion's own producer generation. Historical
275-case and current-main 275-case qualifications remain attached to their
original source bytes; they are not reissued as this counted profile. The
separate counted170 qualification and the two source-conditioning preparations
remain reused evidence with their original scope. A focused new companion
qualification must retain its original inputs, failures and closeouts. Named
source/input checks do not attest executed bytecode, atomic concurrency or a
hermetic interpreter.

## Retained counted companion qualification and public source review

The [original counted companion/spec receipt](../../../../../docs/autoformalization/evidence/legal-ir-counted-decoder-example-20261022.json) records 249 cases on its frozen source generation: 99 companion controls (59 original and 40 new), 149 inventory controls, and one retained-source observer. No phase total is asserted. Original source/native/storage closeouts retain their recorded scope. Its source-only example, 55 provenance rows and separate 293-ID counted label remain unreviewed; target-derived context stays outside model input.

The historical inventory cases, including 52 head-spec controls, remain context for that receipt. This four-file source port publishes no numerical-inventory API and does not requalify the whole 249-case public tree. The separate public source review covers the named 29-producer counted boundary.

The [158-case correspondence receipt](../../../../../docs/autoformalization/evidence/legal-ir-counted-source-correspondence-20261021.json), prior companion populations and the 249-case campaign remain separate. The [public source reconciliation](../../../../../docs/autoformalization/evidence/legal-ir-counted-public-source-reconciliation-20261024.json) records source/fixture/initializer comparisons and unexecuted focused controls; it grants no new execution or accuracy result. This delivery supplies no model run, learned reconstruction quality, compatible native conditioning, independently permitted inference context, legal meaning, graph/Lean admission or training/evaluation eligibility. Masks remain zero.
