# Complete source-correspondence review requests

`legal_source_correspondence_requests_v1` turns an independently pinned ordered
bank population into the existing source-review preparations and an explicit
physical cache-reference roster. It performs no file or network reads itself.
The existing review owner replays the supplied original join, paired-row,
producer-receipt and stored-section inputs. All source alternatives and
unresolved outcomes remain available for actual review.

The physical cache coordinates are supplied declarations. This operation does
not reopen the cache's Parquet tables or freshly authenticate their row bytes.
A caller can bind those declarations to a retained independently pinned
crosswalk as separate evidence. Original source custody and prior independently
checked source-row oracles are separate companions; they do not establish the
producer's intended character occurrence, legal edition or governing meaning.

## Public API

```python
source_correspondence_original_bank_sha256(bank, *, limits=None)

prepare_source_correspondence_requests_v1(
    request_raw, *, expected_request_sha256, original_banks, limits=None,
)

source_correspondence_requests_sha256(report, *, limits=None)

validate_source_correspondence_requests_v1(
    report, request_raw, *, expected_report_sha256,
    expected_request_sha256, original_banks, limits=None,
)
```

Wrapper contract failures raise `SourceCorrespondenceRequestsError`, a
`ValueError` subclass. Existing join/review contract failures retain their
existing exception types. Neither hashing helper validates original source
authority. The report helper only returns a bounded canonical content identity;
the public validator regenerates the entire report from the original inputs.

## Complete original banks

`original_banks` is a nonempty ordered plain list. Each bank has exactly:

```text
bank_id             nonempty bounded string, distinct across banks
join_bytes          immutable original sealed legacy-join JSON bytes
paired_row_bytes    complete ordered list of immutable logical paired-row bytes
join_inputs         exactly the five original build_legacy_source_join arguments
physical_rows       complete ordered declared physical-reference list
```

The five `join_inputs` keys are `expected_population`,
`producer_receipt_bytes`, `expected_producer_receipt_sha256`, `source_sections`
and `expected_source_sections`. Their shapes and semantics remain those of
`corpus_legacy_source_join`. Complete stored text is retained. Producer receipts
may be explicitly unavailable only when both receipt and expected hash are
`None`. The existing owner preserves missing receipts, missing sections,
unmatched text, integrity failures and ambiguous candidates; it never selects
the first or unique match. Integrity failures refuse the preparation.

Each physical-reference entry has exactly:

```json
{
  "physical_row_ordinal": 0,
  "request_ordinal": 0,
  "physical_identity": {
    "repository_id": "organization/cache",
    "revision": "<complete 40-character lowercase commit>",
    "path_in_repo": "paired_spans.parquet",
    "artifact_sha256": "<64-character lowercase SHA256>",
    "row_ordinal": 0
  }
}
```

`physical_row_ordinal` must retain contiguous complete list order; it is not a
Parquet selector. The nested `row_ordinal` is the declared physical table row.
`request_ordinal` identifies the bank's logical paired row. Every logical row
must have at least one physical reference. Multiple distinct physical rows may
map to one logical request, retaining all physical identities and multiplicity.
Identical raw paired bytes must appear only once in a bank's logical row list,
as required by the existing join owner. Do not remove their distinct physical
references. Duplicate physical identities within one bank are refused; the
same declared physical identity may recur as a separate reference across banks
only with the same exact paired-row byte hash. Conflicting byte commitments for
one declared physical identity are refused before project replay.

No file path is followed. Repository paths must be nonempty relative paths
without empty, dot, parent or backslash components. Revisions, hashes and all
counts retain explicit strict types; a Boolean is not accepted as an integer.
None of these syntax checks authenticates the coordinates.

## Independent request commitment

`request_raw` is canonical compact sorted-key Unicode UTF8 JSON, without a final
line feed. Duplicate keys, floats, invalid UTF8, nonfinite numbers and
noncanonical encodings are refused. The complete original input graph is
bounded before any receipt hashing or project replay.

```json
{
  "schema": "legal-source-correspondence-request/v1",
  "profile": "complete-declared-physical-source-review-requests/v1",
  "banks": [
    {
      "bank_id": "paired-v1",
      "original_bank_sha256": "<independently expected original-bank commitment>",
      "physical_rows": 8,
      "logical_rows": 8
    }
  ]
}
```

The bank commitment recipe retains the bank's exact five-key structure and
every original value, with only these byte values replaced by descriptors:

1. Replace `join_bytes` with `{"bytes": len(raw), "sha256": SHA256(raw)}`.
2. Replace every `paired_row_bytes` element with the same descriptor.
3. Replace `join_inputs.producer_receipt_bytes` with that descriptor, or retain
   explicit `null` when unavailable.
4. Hash compact sorted-key Unicode UTF8 JSON of the complete transformed bank,
   without a final LF.

In particular, the commitment binds the full text and expected source
population, the complete receipt bytes and expected receipt hash, every logical
row's exact bytes and order, and every supplied physical selector and mapping.
Caller-supplied expected pins are required. Computing a new pin from an
untrusted changed record does not authenticate its provenance or recover an
omitted physical reference outside the declared population.

## Output and regeneration

The report contains `banks`, each with the unchanged complete existing
source-review `preparation`. It also contains ordered `physical_rows` that bind
each declared physical identity to the exact paired-row SHA256, request/subject
references, preparation-manifest SHA256, original disposition and every
candidate occurrence ID. Bundle-local section indices remain bundle-local.

Coverage reports physical references, distinct declared physical identities,
logical requests, source-section references, distinct physical source sections,
candidate references and all disposition counts separately. Shared source
sections remain present in every original bank; distinct counts do not remove
their references. Candidate coverage counts physical-reference multiplicity,
so fanout may exceed the number of logical candidate records.

Each request retains nine active source/context questions and seven deferred
semantic/proof questions. All questions remain unanswered. Every authority flag
is false; every training/evaluation-gold mask is integer zero; inference views,
selected occurrences and governing sources remain null. This is preparation
for independently supplied review, not an application of source decisions or
governing-law adoption. Identity declarations and unique text matches do not
supply that authority.

The validator checks the supplied report's independent SHA256, regenerates
every original bank through the existing owner, and compares the entire
canonical report. Resealing a dropped row, changed selector, omitted
alternative, answered question, altered mask or authority flag cannot pass
original-bound regeneration. Original caller collections, detached replay
snapshots and limits are compared at closing boundaries. The first operational
failure remains primary if a closing custody check also fails. Returned report
collections are detached from original inputs.

## Finite resource profile

`limits` is `None` or a plain dictionary of lower-only overrides:

| Key | Hard maximum |
| --- | ---: |
| `max_banks` | 16 |
| `max_physical_rows` | 256 across all banks |
| `max_original_bytes` | 64 MiB |
| `max_report_bytes` | 32 MiB |
| `max_request_bytes` | 256 KiB |
| `max_json_nodes` | 1,000,000 visited nodes |
| `max_json_depth` | 48 |
| `max_string_bytes` | 512 KiB per UTF8 string, with character precheck before allocation |

Original budget accounting charges all immutable raw bodies, strings, JSON
punctuation and repeated references as supplied work. It does not deduplicate
receipt bodies across banks. Node/depth/cycle checks precede full serialization;
each scalar string is checked against remaining byte budget before encoding.
Aliases are visited again and charged; cycles are refused. The exact complete
output encoding must fit its limit, including framing and metadata. Aggregate
output is checked after each bank and again on the final report.

Existing delegate bounds remain unchanged: at most 64 logical rows and 64
sections per bank, 1 MiB aggregate paired-row bytes, 32 MiB per receipt, 512
candidate occurrences per join, and an 8 MiB complete review preparation. No
successful output is truncated to fit a limit. These byte/work bounds are not
a proof of peak process RSS. Original/source comparisons are cooperative Python
observations, not a sandbox or authenticated atomic multi-file snapshot.

## Next substantive boundary

Actual typed source responses, independent registry/policy and revocation
snapshots, explicit evaluation time, evidence bodies, source/adjudication
separation and complete history remain separate inputs to existing response,
adjudication, cohort, application, history and binding owners. The current
application effect copies answer references; the current binding assessment
authenticates candidate tuples with `decision_applied=false`. Governing-source
adoption needs a separately versioned authorized applied effect.

Only after that source boundary can one complete definition, a complete norm
and a genuine distinct second statutory use be accepted with exact meaning,
scope/time, exceptions, modalities, roles, cardinality and alternatives. Typed
graph and Lean preservation, eligible partitions/training, source equivalence,
whole-task satisfaction and convergence remain later gates.
## Explicit coordinate-originals profile v2 — qualified candidate custody

The additive v2 profile connects complete, genuinely replayed coordinate
cache rows to the existing independently supplied source-review banks. The
fresh corrected v03 engineering qualification passed **59 cases / 177 setup,
call and teardown phases**: 56 new controls and three unchanged legacy
regressions, in disjoint 30-case and 29-case cohorts. The successful original
native/storage grants were released and the shared source READ closed. These
checks supply candidate custody; primary runtime installation, real-corpus
legal accuracy, model/training and Lean-build qualifications remain separate.
The v1 APIs, bank recipe and limits above retain their original contracts.

The first v02 fixture attempt passed four cases and failed 26 setup phases
before those v2 product branches ran. It supplies no credit to the fresh
59-case qualification. The corrected fixture changes one fictional source-path
literal; the product's `b81e0031` source generation remains unchanged. Original
failure, cleanup and storage records remain separate evidence, without inferring
a later storage release from that failed terminal record.

The qualification uses 223 frozen runtime files and retains the original
15-file native-parent capsule with the `dc6ae4f1` inner validation plugin as its
external test harness. The proposed isolated Git delivery compares 222 source
postimages and excludes only that plugin, preserving the inherited `cef7fd00`
Git plugin. It is not a 223-file committed-runtime or partial native-owner port.
A filesystem relocation does not create a fresh native qualification.

See the [actual qualification](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-coordinate-source-correspondence-20261021-01/qualification-summary.json),
[independent actual review](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-coordinate-source-correspondence-20261021-01/independent-actual-qualification-review-v01.json)
and [portable delivery evidence](../../../../../docs/autoformalization/evidence/legal-ir-coordinate-source-correspondence-20261021.json).
Git landing and its original WRITE/readback receipt remain separate from the
qualification.

V2 requires `legal-coordinate-source-graph-intake/v2` with profile
`original-input-coordinate-source-graph-intake/v1`. That graph owner genuinely
replays `legal-source-span-target-eligibility/v3` under its original-input
profile. Published graph v1 consumes original-input eligibility v2 with mandatory
`join_originals`. Published main exposes retained rows through separately named
retained-v1 APIs; the selected qualification's retained-row-v2 terminology is
historical. Graph v2 requires explicit original-input eligibility v3. These
contracts cannot be substituted by changing schema labels or function names. This bridge reuses the qualified graph and source-review owners; it
adds a row/request association, with every alternative still unselected.

### APIs and original inputs

```python
prepare_source_correspondence_requests_v2(
    request_raw, graph_report_raw, source_request_raw, *,
    expected_request_sha256, graph_originals, original_banks, limits=None,
)

source_correspondence_requests_v2_sha256(report, *, limits=None)

validate_source_correspondence_requests_v2(
    report, request_raw, graph_report_raw, source_request_raw, *,
    expected_report_sha256, expected_request_sha256,
    graph_originals, original_banks, limits=None,
)
```

`graph_report_raw` is the exact retained UTF8 graph-v2 report bytes. Its raw
artifact SHA256 and complete ordinary canonical report SHA256 are separate
request commitments. `graph_originals` has exactly the seven original public
graph replay arguments:

```text
request_raw
eligibility_report_raw
eligibility_request_raw
join_manifest_raw
expected_request_sha256
join_originals
source_bindings
```

Use the existing public
`corpus_proposed_graph_adapter.coordinate_graph_corpus_originals_sha256` recipe
to commit that complete original-input group. The helper supplies content
identity only; genuine public graph validation remains mandatory. Retain the
expected hash independently with the original source inputs. A freshly hashed
replacement input cannot establish that it produced an earlier report.

`source_request_raw` is the exact canonical existing v1 request, with its
independently expected SHA256. It already commits all ordered bank identities,
original-bank hashes and logical/physical counts. `original_banks` must be
**nonempty** and obey the unchanged v1 contract above. An empty list or null
source request does not create an empty review report. Missing producer receipt
bytes are represented through a real bank's explicit `None`/`None` receipt
pair; genuine preparation then retains `producer_source_unavailable`.

The existing review owner accepts exact sealed paired-v2 row bytes, but has no
coordinate-originals preparation API. Coordinate graph reports do not contain
the separately required legacy join, receipt and complete stored sections: the
coordinate join explicitly retains `legacy_candidate_join=None`. Supply those
independent bank originals. The bridge never constructs a producer receipt,
patches a historical pointer, synthesizes a source parent from graph text or
converts nominated HTML into a legacy stored-source section. A caller may
separately prepare a new bank through the existing public join owner using real
retained paired bytes and independently supplied originals; that is its own
preparation generation, with its own retained commitments.

### Closed request and complete nomination order

The new canonical request has exactly:

```text
schema = legal-source-correspondence-request/v2
profile = original-input-coordinate-graph-v2-source-review-request-custody/v1
graph_report_raw_sha256
graph_report_sha256
graph_originals_sha256
source_request_sha256
physical_review_nominations
```

Every `physical_review_nominations` slot has exactly:

```json
{
  "physical_row_ordinal": 0,
  "physical_identity_sha256": "<exact upstream physical identity SHA256>",
  "review_nominations": [
    {"bank_ordinal": 0, "bank_physical_row_ordinal": 0}
  ]
}
```

There is one slot for every upstream physical row, in that exact order. The
slot ordinal and identity must match the genuinely replayed population,
including rows with zero formal outputs. Every ordinal is a plain integer;
Boolean values are refused. Each nomination list follows strictly increasing
`(bank_ordinal, bank_physical_row_ordinal)` order. The implementation validates
that order and does not sort or deduplicate the caller's declarations.

An empty `review_nominations` list retains that physical row as
`review_inputs_unavailable`. Multiple nominations preserve competing original
bank references without selecting a governing source. Across the complete
roster, every supplied bank physical reference must appear exactly once.
Duplicate tuples, omitted bank references and unrelated extra bank rows are
refused. Empty lists for some rows are valid only when the other slots still
account for every independently supplied bank reference.

A nomination identifies the existing bank physical entry. Its logical request
ordinal, original bank pin, request/subject CIDs and hashes, and complete
preparation-manifest hash are derived from genuine v1 preparation. They are not
selected by caller-supplied report references. Distinct physical rows with equal
paired bytes can reference one logical request. The same physical identity in
different banks remains separate alternatives with independent bank/reference
identities and the same exact row bytes.

### Exact identity and whole-row comparison

After genuine graph validation, the bridge recovers each complete paired-v2
row from the original join's `derived_row_json` UTF8 bytes and verifies its
upstream row hash and reference ancestry. Each nominated bank row must match
those **entire exact bytes**, including its source, producer and formal-output
fields. Equal source text, span IDs or observation IDs cannot replace this
comparison.

The two existing identity records spell their file commitment differently:

| Coordinate graph physical identity | Existing bank physical identity |
| --- | --- |
| `repository_id` | `repository_id` |
| `revision` | `revision` |
| `path_in_repo` | `path_in_repo` |
| `file_sha256` | `artifact_sha256` |
| `row_ordinal` | `row_ordinal` |

Every corresponding value must agree exactly. This is an explicit field-name
comparison; the differently keyed original records retain their own hash
recipes. Their identity SHA256 values are not interchangeable. Official HTML
and stored-text candidate offsets likewise remain separate coordinate systems;
no edition or source-view crosswalk follows from this row match.

### Report custody, replay and authority

The new report retains the exact `graph_report_raw_utf8` once and the complete
unchanged v1 `source_preparation` once. Full upstream `physical_rows` and
`row_references` remain available. `physical_review_bindings` accounts for every
physical slot and its complete nomination/request population.
`output_occurrence_bindings` preserves every output's global occurrence
ordinal, physical identity, route and within-route ordinal, including duplicate
looking, unsupported and unresolved outputs. Rows with no outputs remain in
the physical ledger. Each output inherits all request alternatives from its
physical row and has a typed hash-bound pointer into the one retained graph
carrier; a source-context review request does not become a formal-output review.

All source review questions, stored sections, candidate occurrences, original
dispositions and dependency preparations survive unchanged. The v1 preparation
is genuinely generated through its public owner. Closing invokes its genuine
public validator, then performs fresh full public graph replay. Final guards
compare original and detached inputs, the offered/opened reports, source-owner
hashes, exact callable identities, the actual question producer and review
wording. Strict closed false-authority shapes are checked independently of the
mutable legacy flag dictionaries. A primary `BaseException` remains primary
when another closing check fails; secondary failures are retained as notes.

The root and every new physical/output binding retain null selected
occurrences and governing sources, with strict integer-zero training and
evaluation-gold masks. Binding source masks stay integer zero; governing
definition-use remains null. Existing authority flags remain false. Genuine
upstream reexecution is a custody observation under supplied independent pins;
it does not authenticate a remote revision, source epoch, official edition,
statutory meaning or governing application. These guards are cooperative
sequential observations, not an atomic multi-file snapshot or an attestation
against arbitrary hostile runtime changes.

The public v2 validator requires the independently expected full report hash,
then regenerates all of these associations from complete originals. The new
hash helper uses its separate bounded v2 profile. The existing v1 hash helper
keeps its 32 MiB ceiling. Retaining reports and references does not publish or
replace the source files, producer receipts, original graph input group or
original banks; all are required again for complete replay.

### Combined bounds and next semantic gates

V2 has a separate **64 MiB complete report cap** and one **64 MiB aggregate
original-input budget**. Repeated raw bodies and object references count on
each supplied traversal. The retained graph and source preparation must fit
with framing, escapes, metadata and every reference; their individual
allowances are not added together. A valid upstream graph can therefore be
unsupported in this combined profile. Overflow refuses the entire population
without truncation, omission or automatic limit changes.

The designated graph carrier has its own bounded string allowance. Character
count and remaining whole-report budget are checked before UTF8 or JSON
encoding; actual UTF8 and escaped-byte accounting still apply. Other ordinary
original strings keep the at-most-512 KiB ceiling, even where an upstream
source/binding owner accepts larger strings. The 256 KiB outer request,
lower-only limits, million-node and depth-48 ordinary profiles remain bounded.
The upstream graph's complete route/output population is retained; the separate
corpus export profile's 128-output cap is not substituted here.

Existing v1 limits remain unchanged: 32 MiB complete report, 8 MiB per complete
legacy review preparation, at most 16 banks, 256 bank physical references,
64 logical rows and sections per bank, 1 MiB aggregate paired bytes and a
separately bounded optional producer receipt. Existing corpus record/CID
limits are not enlarged. Combined byte/work limits do not establish peak RSS;
actual qualification must use the existing native/resource owners and finite
admitted requests.

The next substantive inputs remain independently supplied source/edition and
legal-as-of decisions, exact operative definition/norm/two-use physical rows,
complete norm grammar including unsupported cardinality, actual reviewer trust
and evidence, and per-use meaning/applicability decisions. Source-context
signatures do not authorize the new association, norm interpretation or
definition application. Reuse `legal_source_typed_norm_join_v1`,
`legal_norm_scope_correspondence_v1`, `legal_norm_definition_evidence_v1`,
`corpus_norm_definition_adapter` and the existing applicability/application
owners after those inputs exist. No model accuracy, accepted training target,
complete statutory norm or `lake build legal` result is supplied by this
bridge.

## Current-main compatibility integration

The [current-main integration receipt](../../../../../docs/autoformalization/evidence/legal-ir-coordinate-source-correspondence-main-integration-20261021.json) records59 authored cases /177 phases on the current223-file dependency closure, using the current native owners and strict pytest plugin. Both original native/storage/source-READ owners closed. This is a separate source generation from the original external-plugin capsule above; neither qualification supplies statutory source/edition/meaning decisions or reconstruction accuracy. Public original-v2, retained-v1 and explicit original-v3 APIs remain separate.

## Earlier coordinate-v2 primary integration

The [closed focused qualification](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-coordinate-correspondence-primary-integration-20261022-01/qualification-summary-01.json) passed **59 authored cases / 177 phases** (56 coordinate-v2 and three unchanged legacy-bank cases) against the current primary generation. The public source/test extensions preserve all 53 original definitions. Genuine graph-v2/eligibility-v3 replay, independent nonempty legacy banks, complete physical/output coverage and closing fences compose without source-pin edits. The selected and current-main historical 59-case receipts above remain separate. Original native, storage and source READ custody closed. Requests remain unsigned and source-review questions unanswered; selections remain null and learning/gold masks zero. Source/edition correspondence, intended producer occurrence, reviewed meaning and governing-source adoption remain pending. This adds no model, training, convergence proof or Lean admission. Historical qualifications retain their original producer and authority scopes.


## Explicit wire-coordinate source-review request custody v3

`prepare_source_correspondence_requests_v3`, `validate_source_correspondence_requests_v3` and `source_correspondence_requests_v3_sha256` extend this same owner. Prepare and validate have the same positional and keyword arguments as v2; the report input remains an ordinary dictionary. A JSON serialize/parse roundtrip is supported through that dictionary contract; native byte-report acceptance is not added. V1 and v2 keep their existing contracts. The exact 24,051-byte v1 prefix, 34 original function bodies, existing authority/limit/field declarations and the row/binding engines are preserved. Only the v2 public prepare/validate bodies delegate to the shared orchestration.

| Request route | Original graph dependency | Independent source banks |
| --- | --- | --- |
| Declared v1 | No coordinate graph argument | Complete existing v1 banks |
| Coordinate v2 | Graph v2 / original-input eligibility v3 | Same independently supplied v1 banks |
| Wire v3 | Wire graph v3 / eligibility v4 / wire join v3 | Same independently supplied v1 banks |

The request uses `legal-source-correspondence-request/v3`, the report uses `legal-source-correspondence-requests/v3`, and both use `profile="original-input-wire-coordinate-graph-v3-source-review-request-custody/v1"`. `profile` remains the owner field; no compatibility alias is introduced. The canonical request still has exactly seven fields: `schema`, `profile`, `graph_report_raw_sha256`, `graph_report_sha256`, `graph_originals_sha256`, `source_request_sha256` and `physical_review_nominations`. The report adds only `metadata_profile="hf-default-parquet-envelope/v1"` and `source_metadata_intake_sha256` from the genuinely regenerated graph. Graph, eligibility and join must preserve that same source-intake commitment and fixed HF metadata profile. A schema change or resealed hash cannot replace genuine graph-v3/eligibility-v4/join-v3 replay.

Retain the same complete seven-field `graph_originals` group and its existing corpus-originals hash recipe. The corpus module supplies that unchanged commitment and its genuine-only physical file-plan helper; this route does not require or generate a corpus-v2 report, construct candidates, export bundles or impose the corpus export profile's 128-output cap. `original_banks` remains nonempty, and `source_request_raw` remains the independently committed canonical v1 request. No bank, producer receipt, stored source section, governing edition or source-request renderer is synthesized from graph text or nominated HTML. A real missing receipt retains its genuine `producer_source_unavailable` disposition.

The wire-only row decoder uses the existing strict ordinary JSON parser on the already genuinely validated original join. It preserves finite metadata values such as `bm25_b=0.75` and `bm25_k1=1.2` under the established 16 MiB / 100,000-node / depth-32 full-join bounds, rejecting duplicate keys and nonfinite numbers. It holds that actual parsed join and a private projection containing every ordered `derived_row_json` and `row_sha256`, then delegates the original whole-row, hash/reference and physical-order checks to unchanged `_v2_rows`. The legacy integer-only `_Budget` and row parser see that required row projection rather than unrelated wire metadata. Caller lower row/string/JSON limits and the complete original-byte budget remain in force; v1/v2 keep their original full-join scalar grammar and limits. No float is stripped or coerced in the full original metadata/raw carrier, and no public report or request field is added. The actual ordinary parser and its delegates join the wire-only callable witnesses.

The unchanged row/binding engines preserve every physical slot, output occurrence, route and ordinal. Each supplied bank physical reference is consumed exactly once in declared nomination order; alternatives remain alternatives. Complete paired-row bytes must match, including producer and source fields. The existing `file_sha256` to `artifact_sha256` field-name comparison does not change either identity/hash recipe. Equal text or logical IDs cannot merge physical rows or establish intended producer occurrence, source-view correspondence or governing-law identity. Uncovered rows, unsupported outputs and missing per-row review inputs remain explicit. The report retains one exact graph carrier and one unchanged v1 preparation, with every source request, subject, candidate occurrence, original stored section and unresolved question.

V3 holds original and detached request/bank/graph inputs, parsed requests, limits, review wording, source/callable identities, runtime descriptions and physical file witnesses through closing and final serialization. It retains actual opening and closing graph returns, the actual v1 source preparation and the actual closing v1 validation return. Outer validation checks its own snapshots before physical nominations are derived from the genuinely regenerated graph carrier. Normal preparation and validation each make two public graph-v3 validations; validation adds no redundant full graph replay. Source preparation and its genuine closing public v1 validator remain mandatory. Late failures preserve the primary exception and attach actual closing failures as notes. These are cooperative sequential observations, not an atomic multi-file snapshot or arbitrary hostile runtime attestation.

The [closed selected authored qualification](../../../../../docs/autoformalization/evidence/legal-ir-hf-wire-coordinate-source-correspondence-20261024.json) passed **103 cases / 309 phases across 42 selected test functions** in selected attempt 02: 59 preceding correspondence controls and 44 wire-v3 controls. The 59 regression cases were selected again against this source generation. All 136 preceding owning cases remain byte-for-byte preserved; 77 were unselected. The full appended owning file has 180 cases across 57 test functions, not 180 executed cases. Historical 59-case correspondence receipts retain their original source and scope. The separate 101-case graph-v3 and 90-case corpus-v2 qualifications were reused as upstream evidence rather than rerun or pooled. Original native compute, retained storage and source READ custody closed. Failed attempt 01 remains separate: 103 collected cases produced 76 pytest passes, 27 failures, 282 phase passes and 310 journal records, with all six operation guards zero. Its source `19da78fb` rejected genuine finite HF metadata during row extraction; that entire cohort has zero qualification credit. Its original receipts, source/test/control generation, native files and separate supported storage closeout remain preserved. Those 76 passed calls are not pooled with the selected retry.

This validation used 238 canonical project inputs, three frozen sibling test files, nine canonical helper inputs and five canonical metadata fixtures, with 250 total native source pins under the unchanged 256-pin maximum. The five fixtures are already in the canonical project population. Test namespaces search frozen then canonical paths; the three frozen siblings preserve their `__file__.with_name` relationships. Actually imported canonical helpers have exact recorded origins; all nine raw helper inputs are retained separately, including any not imported. That is input capture, not attestation of pytest assertion-rewritten codeobjects or the whole installed runtime. The descriptor-relative bundle guard was unused: actual contexts, events, reads, writes and pending writes were zero; five preflight refusals are recorded separately. No export was qualified and no prior corpus campaign's positive descriptor events were pooled.

All 26 correspondence authority flags remain false. Nine active and seven deferred review questions remain unanswered; selected occurrences, governing sources and governing definition-use stay null; source-binding/training/gold masks stay plain integer zero. This source-context request does not review its new association, formal outputs, complete norm, definition applicability or distinct statutory uses. Independent legal source/edition/as-of decisions, source-response trust and authorized applied effects remain separate. The separately qualified wire census-v3 companion (64 cases / 192 phases) and current-public corpus check (three cases / nine phases) retain their own scopes. The separately qualified current-public source-correspondence check below has its own three-case scope; training/gold and graph/Lean admission remain open. Inherited dimensions 0/384 are metadata declarations; these fixtures exercised only 0, which disables the latent path and is not the 8D lane. No 8D/384D/768D/4096D model, embedding, encoder, training, convergence, DB or Lean operation ran. Numerical and Lean owners are unchanged. The existing 64 MiB original/report, 16-bank, 256-physical reference, 256 KiB request, million-node/depth-48 and ordinary 512 KiB string limits remain lower-only. Complete unsupported inputs are refused without truncation or sampling.


## Focused current-public dependency check

The [selected current-public dependency qualification](../../../../../docs/autoformalization/evidence/legal-ir-hf-wire-coordinate-source-correspondence-public-integration-20261024.json) passed three existing wire-v3 cases / nine phases: the object roundtrip, complete unsupported-output review population and late retained-table refusal. It freezes public commit `943e85c247cfc31cdb990518c6ae3bfedf210ceb` with exactly the qualified correspondence source `8fccd02c` and owning test `830ba4a4` overlaid. All other 236 source/fixture files come from that public commit, including public span cache `e35f5333` and validation helper `cef7fd00`. These public dependencies are preserved; no private cache/helper fallback is substituted. The prior e37f corpus and bc5f graph snapshots remain historical provenance. The local 103-case/309-phase result is retained unchanged and is neither rerun nor pooled into this three-case result.

All seven review product owners are genuinely required and present byte-exact in this public generation: legacy review, source questions/packets, both parent adapters and graph dependency/review owners. Their earlier corpus-only exclusions do not apply here. The owning coordinate fixture and nine public helper files drive these selected wire cases. Two legacy sibling test files remain in the full 238-file provenance population; the selected cases do not use their `with_name` fixture chain. Actual imports and physical origins retain their own saved observations.

The original 256-pin maximum is preserved: 238 frozen files retain full manifest commitments; 14 explicit flat context exclusions leave 224 flat frozen pins, alongside 15 unchanged private native/resource owners and 17 run-support inputs. The exclusions are six unexecuted synthetic initializer files, three denied public native/tooling files and five numerical context modules. Those five bodies were absent from the original local 132-product source capture; they remain frozen as provenance and are explicitly import-denied. Required review owners are never pruned. Fourteen declared namespace parents remain unexecuted, while ten genuine initializer routes retain their observed scope; this is no whole-package startup qualification. Private original native/resource owners and orchestration plugin remain separate from the public runtime tree.

Original native compute, storage and source READ custody closed, and an independently pinned saved-only review accepted the exact three cases and nine phases. The descriptor bridge remained unused: actual contexts, events, reads, writes, pending writes and errors were zero, with five separate preflight refusals. No graph bundle export or prior campaign event pooling occurred. These dimension-zero authored fixtures retain all unanswered questions, alternatives, false authority and zero masks. They perform no source/edition/meaning review, law-cache processing, model width, training, convergence or Lean work. The earlier local record and its `public_dependency_adoption_performed=false` cutoff remain historical; this result has a separate `current_public_wire_coordinate_v3` catalog record. The separately qualified census64/192, public corpus3/9 and graph3/9 scopes remain separate.
