# Span-cache intake and coordinate graph proposals

The raw-row APIs below retain their existing contract. The coordinate graph v1
sections describe the historical `73841dee` graph / `c8b9cbe4` original-input
eligibility-v2 combination. The separately reconciled `43a93776` owner uses v2 for
a narrower retained-coordinate contract and v3 for original-input replay. Those
profiles are not interchangeable. The explicit coordinate graph v2 port described
below uses eligibility v3; its separate original-owner qualification passed
43 cases and 129 phases within its original scope. The explicit wire-coordinate
graph v3 section reuses eligibility v4 and wire join v3; its local qualification
and current-public compatibility profile remain separate.

`legal_span_cache_intake.py` retains complete, independently pinned cache-row
populations and builds proposals through the existing `legal_semantic_graph`
owner. Its additive coordinate API connects genuinely replayed eligibility
outputs to independently nominated source occurrences. It does not establish
that those nominated occurrences are the retained coordinate source, select a
governing edition, resolve entities or admit a reviewed graph.

The reviewed candidate has owner SHA256
`9ef87c5426bd11cf210f0c5b9755ef30e6e101ce3508d56b5a2052251a88c48c`
(46,532 bytes) and owning-test SHA256
`e14a0ac8f6c068d79d9f97fa48618d03004aa6790b6ebff5c9417e0c29c7e754`
(37,003 bytes). These identify the candidate, not a published installation.

## Existing raw-row APIs remain unchanged

```python
row_sha256(row)
record_sha256(row, *, ordinal, cache_identity)
source_bindings_sha256(source_bindings)
make_source_binding(
    document, raw_html, *, document_revision, scope, candidate_selectors,
    context_observation=None, dependency_refs=(), evidence_refs=(),
)
prepare_span_cache_intake(
    rows, *, cache_identity, expected_row_sha256s,
    expected_record_sha256s, source_bindings,
    expected_source_bindings_sha256, start_ordinal=0,
)
validate_span_cache_intake(report, rows, **trusted_inputs)
prepare_entity_cache_graphs(cache, entity_id, rows, **trusted_inputs)
```

The legacy raw-row profile remains `legal-span-cache-source-graph-intake/v1`.
It requires independently expected ordered row/record populations, exact source
bindings and explicit cache identity. It retains malformed, unsealed, pending,
ambiguous and unsupported rows with their issues rather than keeping a useful
subset. Legacy paired transport remains observation-only; complete/admitted
flags cannot create graph meaning. The existing entity-cache wrapper remains
a separate API. The coordinate route does not invoke it or inherit entity
bindings from it.

## Additive coordinate API

```python
prepare_coordinate_source_graph_intake_v1(
    request_raw, eligibility_report_raw, eligibility_request_raw,
    join_manifest_raw, *, expected_request_sha256,
    join_originals, source_bindings,
)
coordinate_source_graph_intake_sha256(report)
validate_coordinate_source_graph_intake_v1(
    report, request_raw, eligibility_report_raw, eligibility_request_raw,
    join_manifest_raw, *, expected_request_sha256, expected_report_sha256,
    join_originals, source_bindings,
)
```

The request is duplicate-free ordinary UTF-8 JSON with exactly ten keys:

```text
schema = legal-coordinate-source-graph-intake-request/v1
graph_profile = canonical_rules_v1
eligibility_report_raw_sha256
eligibility_report_sha256
eligibility_request_sha256
join_manifest_raw_sha256
join_manifest_sha256
join_originals_sha256
source_bindings_sha256
expected_physical_ids
```

The returned schema is `legal-coordinate-source-graph-intake/v1`, with
`source_compatibility_profile=paired-coordinate-source-graph-intake/v1`.
`expected_request_sha256` independently binds exact request bytes. Preserve raw
eligibility/join byte hashes separately from their complete canonical report
hashes. Pretty-printed retained JSON need not have the same hash as canonical
JSON. The originals commitment uses the existing eligibility owner's public
`source_span_target_join_originals_sha256` recipe. A report's self-reported hash
cannot substitute for an independently retained expectation.

`expected_physical_ids` is the complete ordered, nonempty population of unique
physical identity SHA256 values, with at most 64 entries. The genuine upstream
coordinate profile retains its one-bundle, complete-population restrictions.
The API does not sample, truncate, deduplicate repeated text or select one
compiler output from the supplied population.

`join_originals` is an ordinary mapping with exactly:

```text
request_raw
source_request_raw
source_metadata_bytes
paired_inventory_request_raw
paired_manifest_bytes
entity_info_raw
expected_request_sha256
legacy_join_inputs
```

The four raw arguments contain exact bytes. Each metadata mapping contains
1–16 ordinary entries; names are nonempty UTF-8 strings of at most 512 bytes,
and values are exact bytes. `legacy_join_inputs` is `None` or an empty ordinary
mapping. Complete original inputs remain necessary for every validation;
saved report projections, callbacks or paths alone do not supply that replay.

## Independent source nomination

For this route, `source_bindings` maps selected **physical identity hashes** to
source declarations. Legacy raw-row intake instead uses span IDs. Unknown
physical keys are rejected. Missing selected bindings remain unresolved outputs;
an empty or partial binding map cannot shrink the retained physical/output
population.

Each supplied declaration has these required fields:

```text
document
raw_html_base64
document_revision
scope
candidate_selectors
```

Optional fields are exactly `context_observation`, `dependency_refs` and
`evidence_refs`. `make_source_binding` can construct this declaration. The
independent request pin commits the complete binding-map digest.

The existing source/context owners regenerate the normalized document from
exact supplied HTML, validate the scope identity and require its integer edition
to match the nominated document. Each selector must match the complete cached
source text and its SHA256. Supplied nonempty revision and legal-ID labels must
agree. Zero exact candidates or multiple nominated candidates remain explicit
unresolved states; text equality cannot silently choose an occurrence.

This is custody of an independently nominated official-shaped source. It is
not a verified crosswalk from the coordinate report's physical source row to
that HTML acquisition or edition. Matching labels, text or hashes in different
view namespaces cannot supply a historical producer operation or governing
edition decision. Every output occurrence retains:

```text
coordinate_to_graph_source_correspondence = unverified_no_independent_crosswalk
selected_occurrence = null
source_binding_mask = 0
```

The complete report additionally retains
`current_source_release_correspondence = unverified_no_independent_crosswalk`.

The graph's nominated selector remains inside its proposed source binding;
`selected_occurrence=null` records that no historical coordinate occurrence has
been admitted as that source. Source nomination and historical source selection
are distinct claims.

## Supported formal output and preserved population

A graph is attempted only when the genuine eligibility output is mechanically
supported and its formal output has exactly the supported family/format labels:

```text
family = typed_deontic
format = typed-deontic-rule/v1
graph_profile = canonical_rules_v1
```

The existing rule parser and `CanonicalRoundTripIR` contract validate the full
payload. Its AST must equal the complete eligibility `canonical_ir`. The existing
graph owner builds the proposal and reconstructs the ordered AST again. Array
order, multiplicity and case are preserved; validation does not substitute a
sorted or deduplicated target. This profile is not an arbitrary FOL, TDFOL,
relational-norm, cognitive/event or frame-logic graph bridge.

Unsupported outputs and missing, invalid or ambiguous source nominations retain
their complete eligibility output and issues, with disposition `unresolved` and
no graph. Successful construction yields only `proposed_unreviewed_graph`.
Every output retains its original route and ordinal, physical identity,
coordinate provenance/global index, complete eligibility output, paired source,
rule assessment and source/graph declaration when available. Repeated identical
text at different physical rows remains distinct, as do two compiler routes
that emit the same AST.

A global coordinate index of `1` can address physical paired row `0`; neither
index should replace the other. Complete coordinate/raw carrier evidence stays
in the retained original join bytes and genuinely replayed eligibility report.
The graph does not reinterpret character coordinates as raw HTML offsets.

## Replay and closing custody

Preparation genuinely calls
`legal_source_span_target_eligibility_v1.validate_source_span_target_eligibility_v2`
on opening and closing. This replays the existing original-input coordinate join;
it is not a report-only shape check. A successful preparation therefore performs
two public eligibility validations; public graph-intake validation regenerates
the complete preparation and performs those checks again.

The report retains exact eligibility artifact bytes, exact eligibility request
bytes, exact join artifact bytes, complete physical/reference/output populations,
source-binding commitment, unresolved dispositions and the existing runtime
description. Validation requires an independent whole-report hash and complete
regeneration, including output order and graph inputs.

Closing checks inspect original and detached inputs, source-binding declarations,
admitted report snapshots, selected producer source hashes and operation callable
identities. They replay eligibility after graph work, so a changed retained table
cannot be hidden by an earlier successful graph construction. The outer validator
also fences the offered graph-intake report. Applicable closing checks are
attempted on failures, with secondary custody failures attached to the primary
exception. These are bounded ordered observations, not an atomic filesystem
snapshot, hostile-process containment or complete loaded-byte attestation.

## Bounds and authority

| Input or operation | Bound |
| --- | --- |
| Coordinate request and eligibility request | 128 KiB each |
| Exact eligibility report and join artifact | 16 MiB each |
| Complete coordinate graph report | 64 MiB |
| Original join argument bytes, aggregate | 8 MiB |
| Each of the four original raw arguments | 256 KiB |
| Source-binding map | 8 MiB |
| Selected physical population | 1–64 unique ordered identities; upstream one-bundle limits remain |
| Candidate selectors in one declaration | At most 64 |
| Supplied raw HTML in one declaration | 8,000,000 bytes |
| Existing proposed graph | Its unchanged 1 MiB, 4,096-node and depth-24 limits |

Underlying ordinary-JSON, source, eligibility, paired-intake and graph owners
retain their additional bounds. An input can meet an outer bound and still be
refused by an underlying owner; no bound is raised to make it fit.

All source-authenticity, semantic, context-closure, review, entity-binding,
training/gold, graph/proof and Lean admission decisions remain unresolved or
false. Training and evaluation masks remain integer zero. The profile consumes
neither the entity census nor scoped-definition lookup/definition-use evidence.
Its proposals do not add governing definitions, resolve denoted entities or
assert scoped legal relations from AST edges. It performs no model execution,
training, optimizer update, checkpoint loading or Lean compilation. Retained
runtime metadata makes no accuracy or supported-width claim for 8D, 384D, 768D
or 4096D autoencoders.

## Original engineering result and adoption boundary

The original `legal-ir-coordinate-graph-intake-20261021-01` engineering run
reported **25 passed cases / 75 passed setup/call/teardown phases**: 22 new
coordinate controls and three legacy regressions. JUnit suite time was
**16.619 seconds**; the outer test-result elapsed measurement was
16.69643744919449 seconds. These are separate timing measurements.

Independent adoption review **accepted reuse of the original qualification** in
`independent-qualification-adoption-review-v01.json` in the separate
`legal-ir-coordinate-graph-adoption-20261021-01` phase (29,459 bytes; SHA256
`5699eaf39afafdc3163aadb1dcf9312f06317a3e2388523d41aef44eee0cea2d`).
This is independent readback of the original result and closure, not another
test run. Canonical installation, selected Git delivery and publication remain
separate actions. The adoption phase's `qualification-summary.json` and
`docs/autoformalization/evidence/legal-ir-coordinate-graph-intake-20261021.json`
record the retained evidence and delivery boundary.

The source fixtures are authored, including independently nominated
official-shaped HTML. No real statutory source/edition crosswalk, reviewed
formalization, training accuracy or Lean build is established by these tests.

The original owning test is `test_legal_span_cache_intake.py`. Preserve original
run receipts and source generations. Further corpus custody/export should reuse
`corpus_proposed_graph_adapter`; parent/official comparison evidence should reuse
`legal_parent_source_alignment` and `corpus_parent_alignment_adapter`. Those
owners preserve candidates and unresolved correspondence; none authorizes
automatic source selection or a semantic review decision.


## Explicit coordinate graph v2 over eligibility v3

`prepare_coordinate_source_graph_intake_v2` and
`validate_coordinate_source_graph_intake_v2` extend this same implementation owner.
The public argument lists match the graph v1 APIs. The private preparation engine,
source extraction and mechanical per-output graph projection are shared; the
existing semantic graph builder and full ordered canonical AST are reused.

Graph v2 requires the closed eleven-field request below. The profile discriminator
is mandatory; neither an API, schema, graph shape nor retained field selects a
different profile automatically.

```text
schema = legal-coordinate-source-graph-intake-request/v2
source_compatibility_profile = original-input-coordinate-source-graph-intake/v1
graph_profile = canonical_rules_v1
eligibility_report_raw_sha256
eligibility_report_sha256
eligibility_request_sha256
join_manifest_raw_sha256
join_manifest_sha256
join_originals_sha256
source_bindings_sha256
expected_physical_ids
```

The exact eligibility request/report must be v3 with profile
`original-input-coordinate-target-eligibility/v1`. Independently pinned original
join arguments remain a separate required `join_originals` argument. The retained
coordinate join and its genuine public replay retain their existing v2 contract.
The new graph report has schema `legal-coordinate-source-graph-intake/v2` and the
same explicit graph compatibility profile as its request.

```python
from ipfs_datasets_py.logic.autoformal.legal_span_cache_intake import (
    prepare_coordinate_source_graph_intake_v2,
    validate_coordinate_source_graph_intake_v2,
    coordinate_source_graph_intake_sha256,
)

report = prepare_coordinate_source_graph_intake_v2(
    request_raw, eligibility_report_raw, eligibility_request_raw, join_manifest_raw,
    expected_request_sha256=request_pin,
    join_originals=original_join_inputs, source_bindings=independent_bindings,
)
validate_coordinate_source_graph_intake_v2(
    report, request_raw, eligibility_report_raw, eligibility_request_raw,
    join_manifest_raw, expected_request_sha256=request_pin,
    expected_report_sha256=coordinate_source_graph_intake_sha256(report),
    join_originals=original_join_inputs, source_bindings=independent_bindings,
)
```

The caller supplies all independent input commitments before invoking preparation.
A newly computed whole-report identity cannot replace complete regeneration or
turn a changed input into an authorized source, target or graph.

### One eligibility artifact and typed references

The graph v2 report retains `eligibility_report_raw_utf8` once at this report
layer. It does not duplicate the parsed `eligibility_report` or add a second
`join_manifest_raw_utf8` field. Its two closed references are:

| Reference | Exact fields |
| --- | --- |
| `eligibility_report_reference` | `schema=legal-coordinate-source-graph-eligibility-reference/v1`, `container=eligibility_report_raw_utf8`, `report_artifact_sha256`, `report_sha256`, `report_bytes` |
| `join_manifest_reference` | `schema=legal-coordinate-source-graph-join-reference/v1`, `container=eligibility_report_raw_utf8`, `json_pointer=/join_manifest_raw_utf8`, `join_manifest_raw_sha256`, `join_manifest_sha256`, `join_manifest_bytes` |

First decode the retained eligibility artifact as JSON. Its exact
`join_manifest_raw_utf8` string names the original join artifact; encoding that
string as UTF-8 must equal the separately supplied join bytes. The eligibility
v3 report already preserves its own typed reference to the original coordinate
carrier. The graph does not rebuild that carrier or translate its view offsets
into HTML offsets.

Artifact hashes commit exact supplied UTF-8 bytes. Canonical report hashes commit
the corresponding ordinary JSON representation. These are distinct identities;
whitespace or non-ASCII text must not make a character count stand in for a byte
count. Both references, both canonical identities and both exact artifact lengths
are checked again after closing replay. The final returned graph report is
detached from the genuine upstream report and graph callback objects.

### Replay, compatibility and authority

New graph preparation invokes the current genuine public
`validate_source_span_target_eligibility_v3` on opening and closing. Its original
join replay, current callable identities and source/runtime owner commitments
remain mandatory. Graph-level closing checks run after that public replay and
also fence original inputs, independent nominations, admitted snapshots, the
selected validator, graph operations and runtime descriptor. The graph validator
regenerates the complete result and checks the caller's offered report after
replay. A primary callback error retains secondary closing-custody notes.

The historical graph v1 public names, request and report representation remain
available unchanged. They continue to require their original original-input
eligibility-v2 dependency contract. The reconciled retained-v2 API does not accept
that contract, so historical graph v1 is not newly qualified on the reconciled
stack. There is no fallback to retained validation or implicit upgrade of an old
report to graph v2. Reuse the old 25-case receipt only for its original source
combination and scope.

The new port's bounded original-owner qualification passed **43 cases and 129
setup/call/teardown phases** across 20 selected functions: 22 adapted coordinate
controls, 18 focused compatibility/reference/closing-custody controls and three
unchanged raw-row regressions. The original 37,003-byte test prefix and historical
function ASTs are preserved; unselected historical cases gain no new execution
claim.

The run pins 233 runtime files and 252 native-request source entries, with seven
separate preparation-metadata pins. Independent actual review checked every pin,
the 139-file actual module/compile union and all 329 retained sealed files
(328 payload files plus the durability receipt), totaling 4,166,691 bytes. The
original normal granted owner closed native, storage and outer source READ
custody with no live observed child/group processes or sampled RSS remaining.
No pre-child fallback ran; broader lifecycle qualifications remain separate.
The [qualification summary](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-coordinate-graph-v3-port-20261021-01/qualification-summary.json)
and its independent actual review retain the complete local receipt identities.
The [portable selected evidence summary](../../../../../docs/autoformalization/evidence/legal-ir-coordinate-graph-v3-port-20261021.json)
records their exact producer identities; referenced workspace logs are not
claimed to be remotely published.

All formal-output and physical occurrences retain order, multiplicity, exact
provenance strings and original global coordinate indices. Support stays limited
to mechanically supported `typed_deontic` / `typed-deontic-rule/v1` outputs as
`canonical_rules_v1` proposals. The separately qualified `f9253ab4` entity-census
slice is retained in the selected stack, but this graph operation consumes no
entity meanings or definition bindings. It does not establish a source/edition
crosswalk, a selected historical occurrence, a governing definition, complete
norm applicability, semantic review or Lean admission. Source-binding, training
and evaluation-gold masks remain integer zero and all authority flags false.

The new selected combination starts from reconciliation `43a93776` and reuses the
exact entity-census paths and historical graph owners before this explicit port.
It does not replace the primary cache generation or import workspace/artifact
implementations into product code. No model, vector, checkpoint, training or Lean
execution is introduced. The existing lossless corpus/graph export owners remain
the next integration boundary after this proposal-preparation slice.


## Public v2 and explicit v3 compatibility

Graph-v1 retains published original-input eligibility-v2 with mandatory originals. Graph-v2 uses explicit eligibility-v3; the new corpus-custody profile consumes graph-v2. Retained eligibility has distinct retained-v1 APIs and wire identities, and cannot substitute for either original-input route. Source/helper byte pins remain complete across helper-backed and inlined context generations; existing reports retain their original producer pins and do not gain authority from relocation.

## Explicit wire-coordinate graph v3 over eligibility v4

`prepare_coordinate_source_graph_intake_v3` and `validate_coordinate_source_graph_intake_v3` extend this same owner and share its unchanged ordered projection loop. Their positional and keyword arguments match graph v2. The closed twelve-field request uses `legal-coordinate-source-graph-intake-request/v3`; the report uses `legal-coordinate-source-graph-intake/v3`. Both carry `source_compatibility_profile="original-input-wire-coordinate-source-graph-intake/v1"` and `metadata_profile="hf-default-parquet-envelope/v1"`. The request fixes `graph_profile="canonical_rules_v1"`; the report retains that declaration under its `request`. The request preserves graph-v2 independent pins and the complete physical-ID population and adds only `metadata_profile` to that field set. No schema or alias selects a different route.

| Graph route | Required original-input eligibility | Required coordinate join |
| --- | --- | --- |
| Graph v1 | Public eligibility v2 | Join v2 |
| Graph v2 | Explicit eligibility v3 | Join v2 |
| Wire graph v3 | Eligibility v4, `original-input-wire-coordinate-target-eligibility/v1` | Wire join v3, `paired-coordinate-hf-wire-three-cache-join/v1` |

V3 genuinely validates eligibility v4 at opening and closing against the independently pinned artifact and complete original arguments. That operation replays wire join v3, intake v2 and the existing paired payload/coordinate owners. The graph retains exactly one original eligibility artifact; the typed join reference follows `/join_manifest_raw_utf8`, which retains the original coordinate carrier. Raw and canonical identities, every physical row/reference, output route, ordinal and provenance remain distinct. Original/captured/parsed inputs, actual upstream returns, live graph/build-request objects, runtime descriptions, producer/callable identities, physical files and detached reports remain checked through closing replay and final serialization. Outer validation checks its own input snapshots before deriving file nominations solely from genuinely regenerated original bytes. These are sequential custody checks, not an atomic filesystem snapshot.

The [closed selected authored qualification](../../../../../docs/autoformalization/evidence/legal-ir-hf-wire-coordinate-graph-intake-20261024.json) passed **101 cases / 303 phases across 51 selected functions**: 65 previously selected graph-intake controls and 36 wire-v3 controls. All 97 preceding owning cases remain byte-for-byte preserved; 32 were unselected in this run. The full appended owning file has 133 cases across 67 test functions, not 133 executed cases. Upstream intake, join and eligibility qualifications were reused separately rather than repeated or pooled. Original compute, retained storage and source READ custody closed. Public package initializers and the complete installed third-party runtime remain outside the declared namespace qualification.

Mechanically supported `typed_deontic` / `typed-deontic-rule/v1` outputs become unreviewed `canonical_rules_v1` proposals only when an independent source nomination is accepted. Missing or ambiguous nominations and unsupported outputs remain lossless and unresolved. Independently nominated authored HTML does not establish a source/edition crosswalk or two reviewed statutory uses. Selected occurrences stay null, entity/definition binding stays unavailable, all authority stays false and learning/gold/source-binding masks stay plain integer 0. The inherited eligibility declarations allow 0 or 384 latent dimensions; these graph fixtures exercised only dimension 0. No model width, encoder, embedding, training, convergence or Lean operation ran. Corpus custody/export and entity census retain their older profiles and require their own explicit wire adoption.

## Focused current-public dependency qualification

The [separate current-public dependency check](../../../../../docs/autoformalization/evidence/legal-ir-hf-wire-coordinate-graph-public-integration-20261024.json) passed **three existing cases / nine phases** on public base `bc5f60c576477abcb5667448ee84585d0e387e14` with the exact qualified graph source and owning test. It covers one genuine complete roundtrip, lossless unsupported targets and closing physical-table drift refusal; the historical **101 cases / 303 phases** remain separate and were not repeated or pooled.

The frozen profile retains 224 source/fixture files: 222 current-public files and only two graph source/test overlays. Public `span_cache` (`e35f…`) and the public validation helper (`cef7…`) are preserved. Nine private context owners remain absent and import-denied; three public native-tooling files remain unexecuted context. The unchanged private pytest plugin and original native/resource owners remain qualification orchestration. Fourteen namespace parent bodies stay unexecuted and ten declared genuine initializer routes retain their actual frozen origins; 132 loaded origins and 123 checked import/compile entries do not establish whole-package qualification. Original source READ, compute and retained storage custody closed and independent saved-result review accepted the result.

These authored fixtures exercised metadata dimension 0 only. The inherited 0/384 eligibility declarations establish no encoder/decoder width compatibility, model quality, training or convergence. Census-v2, corpus-v1 and source-correspondence-v2 keep their older contracts. Source/edition/meaning, entity and governing-definition applicability and graph/Lean admission remain open; training and gold masks remain zero.
