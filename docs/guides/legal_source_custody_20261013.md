# Cache provenance and official comparison-source custody

This phase adds complete physical-row provenance observations and independently
pinned GovInfo comparison documents. It prepares source evidence for the
[span-to-section bridge](legal_span_section_bridge_20261013.md); it does not
establish producer lineage, governing source correspondence or formal correctness.
Original corpus, context, review, training and Lean acceptance remain open.

## Reconcile authored demonstrations without executing their producer

`logic.autoformal.legal_span_provenance.reconcile_span_provenance` consumes the
complete supplied raw-row list, exact cache identity, ordered independent
`expected_row_sha256s` and `expected_record_sha256s`, `start_ordinal`, and an
independently pinned demonstration catalog plus separate catalog source pins.
The existing intake owns raw-row and physical-record hashing. Every raw field,
unknown value, row ordinal and repeated presentation survives reconciliation.

`catalog_from_sources(expected_catalog_source_pins)` reads immutable local
source files as inert Python AST. Each closed source pin declares `source_id`,
absolute `path`, raw-file `source_sha256`, `function_name`,
`function_ast_sha256`, and `projection_profile`. The function hash is SHA256 of
UTF-8 `ast.dump(function, include_attributes=False)`. The supported profile is
`literal_rows_tuple_source_span_id_legal_id_source_text/v1`: exactly one direct
literal `rows` assignment containing three-string tuples/lists. The module and
function are never executed. Repeated literals and source/literal order remain
part of the catalog; omitted, fabricated or reordered catalog entries fail replay.

The compared projection is exactly `source_span_id`, `legal_id`, `source_text`.
It uses explicit flat/evidence fields or the existing paired-source projection.
There is no alias fallback, Unicode normalization, substring matching or
revision inference. Empty legal IDs remain literal diagnostic observations.
Repeated authored matches remain ambiguous; none is chosen. A match does not
prove the entire cache row came from that source, that a historical job called
the function, or that the declared model actually ran. Legacy producer, model,
sealed/admitted/formalized flags and checksums remain raw observations.

Supported profiles are schema-absent flat rows, explicit `span_export_fields/v1`,
`uscode-autoformal-span-evidence/v1`, and paired census v1/v2. Paired rows remain
unsupported formal-rule transport. Other profiles and incomplete projections
are retained with explicit classifications. The 128-row bound applies to the
independently supplied batch; `population_complete` never means whole-cache
coverage. Catalog/source/literal and finite JSON bounds fail without truncation.

`catalog_sha256` hashes the complete canonical catalog. The catalog cannot
authenticate its own source list: separate independently retained source pins
must reproduce its full source bytes, named function AST and literal population.
`validate_span_provenance(report, rows, expected_report_sha256=..., **inputs)`
checks an independent full-report digest, then regenerates every observation.

## Retain independent official comparison bytes

`legal_official_source_custody.prepare_official_document` takes raw bytes or
explicit `None`, a closed acquisition descriptor, and separately retained
`expected_descriptor_sha256`, `expected_raw_sha256`, `expected_raw_bytes`.
The descriptor binds literal legal ID, exact historical edition, package,
granule, clean official HTML URL, retrieval timestamp, content size/hash and
closed HTTP observations. These observations are separate from content hashing.
Raw bytes remain in independently pinned caller storage.

Exact supplied bytes are verified before existing `legal_statutory_context`
extraction and normalized-view generation. Missing bodies, unsupported section
identity grammar and extraction rejection remain explicit dispositions. A
verified content hash does not authenticate publisher identity, legal
currentness, or the cache producer's edition/revision. A 2024 comparison is an
independently selected comparison edition, not a reconstructed cache edition.

V2 selectors name one immutable normalized `document_text` view. Character and
UTF-8 byte ranges both address that view, never raw HTML bytes. Each occurrence
has its own position-bound identity. Paragraph intersections retain body,
source-credit and note classifications, subsection paths, note headings and
interparagraph separators as observations without inferring their legal role.

`prepare_source_occurrence_inventory` first replays the entire pinned provenance
report. It then verifies the complete independently selected document population
and examines every document with exactly the row's literal legal ID. All exact
overlapping text occurrences are retained. Zero, single and multiple matches are
distinct; a single match is still unselected. Any unavailable comparison body
makes the inventory incomplete rather than a successful zero/single result.
The report retains all physical record pins and provenance classifications,
whole extracted documents/views once, and all per-row comparison candidates.

There are at most 10 documents, 8,000,000 raw bytes per document, and 128 rows.
Occurrence and incremental complete-report byte bounds refuse overflow rather
than returning a selected or truncated population. Documents are not fetched by
these APIs. Acquisition and comparison-document selection happen independently.

## Retain pins, then replay the complete inputs

All catalog/report digests use finite canonical UTF-8 JSON with sorted keys,
compact separators and `ensure_ascii=False`. They differ from a pretty-printed
JSON file's byte hash. Full-report helpers include the report's internal seal:
`provenance_report_sha256`, `document_report_sha256`, and
`source_occurrence_inventory_sha256`. Expected report pins must come from an
independently retained receipt, not from the incoming report being checked.

```python
import json
from pathlib import Path
from ipfs_datasets_py.logic.autoformal import legal_span_provenance as provenance
from ipfs_datasets_py.logic.autoformal import legal_official_source_custody as custody

# These files and pins are retained independently by the bounded job owner.
pins = json.loads(Path("trusted-baseline-pins.json").read_text())
rows = json.loads(Path("raw-cache-rows.json").read_text())
inputs = json.loads(Path("trusted-provenance-inputs.json").read_text())
report = provenance.reconcile_span_provenance(rows, **inputs)
provenance.validate_span_provenance(report, rows,
    expected_report_sha256=pins["provenance_report_sha256"], **inputs)

documents = json.loads(Path("trusted-document-inputs.json").read_text())
for document in documents:
    path = document.pop("raw_path")
    document["raw_bytes"] = Path(path).read_bytes() if path is not None else None
inventory_inputs = dict(provenance_inputs=inputs,
    expected_provenance_report_sha256=pins["provenance_report_sha256"],
    document_inputs=documents,
    expected_document_population_sha256=pins["document_population_sha256"])
inventory = custody.prepare_source_occurrence_inventory(report, rows, **inventory_inputs)
custody.validate_source_occurrence_inventory(inventory, report, rows,
    expected_report_sha256=pins["source_inventory_report_sha256"], **inventory_inputs)
```

The provenance input file contains all reconciliation keyword arguments,
including the complete catalog and its separate source pins. Each document
input contains `descriptor`, `expected_descriptor_sha256`, `expected_raw_sha256`,
`expected_raw_bytes`, and an acquisition-owned `raw_path` replaced with bytes
before calling the closed API. `document_population_sha256` commits every
descriptor, external content pin and supplied/missing-body state. Validation
regenerates full extraction and all occurrences, rather than accepting self-seals.

## Evidence status and next implementation

The phase-seven preparation retained all 20 physical presentations: eight paired
diagnostic rows and twelve evidence rows. Eight evidence projections exactly
match the pinned authored literals; the other twelve presentations do not.
These eight matches establish only the three-field comparison, not historical
producer attribution or a real model invocation.

Ten selected 2024 GovInfo HTML comparisons were acquired. Official link requests
first supplied PDF redirects; their exact observed package/granule identities
were retained and the corresponding official HTML representations acquired.
`official-comparison-acquisitions-v02.json` records this custody. The original
HTML-only refusals in `official-comparison-acquisitions.json` remain preserved.
No producer edition correspondence is inferred from this acquisition path.

The document baseline has eight extracted comparisons, one unsupported identity
(`usc:us:16:410oo-2`, outside the current v1 section grammar), and one extraction
rejection (`usc:us:26:141`, "codified body cannot resume after note headings").
Both failed documents retain verified raw content and explicit open status.
Structural headings and footnote interleaving require a separately qualified
versioned view; the current v1 failure must remain part of the evidence.

| Physical input | Exact comparison inventory | Total occurrences |
| --- | --- | --- |
| Eight paired rows | Five single unselected, two multiple unselected, one zero | 20 across seven rows |
| Twelve evidence rows | Eight missing comparisons, two zero, two incomplete due to unsupported/rejected documents | 0 |

The eight missing evidence comparisons were not acquired in the independently
selected document population. Zero exact matches do not prove legal absence or
justify approximate matching. All 20 records have no selected occurrence and
no governing source binding; all authority flags remain false.

Retained baselines are `span-provenance-baseline.json`,
`official-document-custody-baseline.json` and
`source-occurrence-inventory-baseline.json`, with complete input pins in
`source-population-inputs.json`. Separate paired/evidence baselines preserve each
source population. They live under
`artifacts/legal-autoformalization-source-custody-20261013-01` in the workspace.

Focused checks passed: 60 provenance cases, 41 official-custody cases and six
cross-owner integration cases, totaling 107, plus 41 supervisor control cases.
Native campaign qualification and independent post-merge replay are pending at
this guide's preparation. The later completion receipt is authoritative for
qualification status; passing preparatory tests does not accept legal content.

Next, qualify complete real-row provenance and comparison inventories, retain
producer job/checkpoint evidence, and establish independently reviewed exact
edition/revision and occurrence correspondence. Extend unsupported source-view
profiles additively with explicit coordinate contracts. Only then prepare
per-record source mappings for the existing section/proposal/dependency APIs.
Governing definitions, authority, antecedents, shared qualifiers, temporal origin
and referenced provisions remain open context obligations. Authenticated legal
and formal review, accepted graph views, training eligibility and namespaced
Lean kernel admission require their own later gates.
