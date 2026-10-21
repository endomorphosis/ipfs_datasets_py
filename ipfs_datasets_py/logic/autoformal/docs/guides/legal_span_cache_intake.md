# Span-cache intake and coordinate graph proposals

`legal_span_cache_intake.py` retains complete, independently pinned cache-row
populations and builds proposals through the existing `legal_semantic_graph`
owner. Its additive coordinate API connects genuinely replayed eligibility
outputs to independently nominated source occurrences. It does not establish
that those nominated occurrences are the retained coordinate source, select a
governing edition, resolve entities or admit a reviewed graph.

The original 25-case / 75-phase graph qualification used owner SHA256
`9ef87c5426bd11cf210f0c5b9755ef30e6e101ce3508d56b5a2052251a88c48c`
(46,532 bytes) and owning-test SHA256
`e14a0ac8f6c068d79d9f97fa48618d03004aa6790b6ebff5c9417e0c29c7e754`
(37,003 bytes). These historical pins identify that original source generation;
they do not identify or qualify a changed main-integration source by themselves.

## Main-integration source generation

The main integration removes the obsolete `context._context_obligations` owner
alias so the existing coordinate graph profile can resolve its owner closure
against the delivered main modules. This compatibility change preserves the
original API and proposal scope; it is not another graph implementation or a
source/edition/meaning qualification.

The separate [main-integration qualification](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-coordinate-main-publication-20261021-01/qualification-summary.json)
records the changed source generation, exact source pins, selected cohorts and
original resource cleanup. This main integration qualifies its changed source
generation through **47 cases / 141 passed phases**, as recorded in that
independently pinned receipt. This is focused compatibility engineering
evidence. The [verified datasets-main publication](../../../../../docs/autoformalization/evidence/legal-ir-coordinate-main-publication-20261021.json)
records qualified source-bearing commit `1fe22386109cd2c282034a4cc9f0b66b6c4f98f5`. Later documentation-only
commits do not change or requalify that source generation.
The original 25/75 result below remains separate historical evidence.

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
