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


## Explicit wire-coordinate source-review requests v3

The existing owner now exposes `prepare_source_correspondence_requests_v3`,
`validate_source_correspondence_requests_v3` and
`source_correspondence_requests_v3_sha256`. V1 and v2 retain their contracts.
Prepare and validate retain the v2 arguments; the report remains an ordinary
dictionary, including after a JSON serialize/parse roundtrip. Native byte-report
acceptance is not added.

Use request schema `legal-source-correspondence-request/v3`, report schema
`legal-source-correspondence-requests/v3` and
`profile="original-input-wire-coordinate-graph-v3-source-review-request-custody/v1"`.
The route genuinely replays wire graph v3, eligibility v4 and wire join v3 with
source intake v2 and `metadata_profile="hf-default-parquet-envelope/v1"`.
Supply every original request/raw report, the independently pinned complete
seven-field `graph_originals` group and the nonempty independent unchanged v1
review banks. Nomination text cannot manufacture a bank or original source.
Full wire metadata retains finite floats without coercion; legacy v1/v2 scalar
grammars remain unchanged.

The existing corpus owner supplies the unchanged originals commitment and
physical-file-plan helper; this route neither consumes nor generates a corpus-v2
report or exports a graph bundle. Opening/closing original replay and final
input, parsed-request, live-return, callable and physical-file fences preserve
every source/output alternative and unanswered review question. They are
sequential custody observations, not an atomic snapshot or arbitrary runtime
attestation. Existing lower-only bounds still refuse complete overflow.

The [historical local qualification](../../../../../docs/autoformalization/evidence/legal-ir-hf-wire-coordinate-source-correspondence-20261024.json)
passed **103 cases / 309 phases**: 59 preceding controls and 44 wire controls in
selected attempt 02. Its earlier failed attempt, source generation, original
capture and closeouts remain separate. The [focused public dependency check](../../../../../docs/autoformalization/evidence/legal-ir-hf-wire-coordinate-source-correspondence-public-integration-20261024.json)
passed **three existing cases / nine phases** on public `943e85c2` plus the exact
qualified source `8fccd02c` and test `830ba4a4` overlays. It covers the object
roundtrip, complete unsupported-output population and late retained-table
refusal; the historical 103-case cohort was not rerun or pooled.

The public check preserves all other 236 source/fixture leaves, including public
span cache `e35f5333` and validation helper `cef7fd00`, and requires all seven
public review owners. Its 238-file provenance and 256-pin limit retain 14
explicit unexecuted context exclusions, 15 separate private native/resource
owners and 17 support inputs. Fourteen namespace parents remain unexecuted;
ten genuine initializer routes retain only their observed scope. The original
private orchestration plugin (`dc6ae4f1`), controls and run-specific captures
remain local evidence and are not bundled by this publication. There is no
whole-package, tooling or model-width qualification. Descriptor bridge usage
and graph export were zero; no earlier campaign events are pooled.

All source/edition/as-of choices, intended occurrences, substantive meaning,
definition applicability and reviewed authority remain unresolved. Requests
remain unsigned, selections null and training/gold masks integer zero. No model,
encoder, training, source-law-table processing, convergence or Lean operation ran;
these fixtures confer no graph/corpus or Lean admission.
