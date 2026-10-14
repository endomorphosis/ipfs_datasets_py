# Exact span-to-section proposals and review requests

The new section index, span bridge and source-proposal layer connect independently
pinned cache observations to the reconstructed primary graph. They preserve
physical records and declared associations without accepting legal meaning.
Original LAC-011, LAC-024 and LAC-044 acceptance remains preparatory and partial.

## Primary index custody and lookup

`logic.autoformal.legal_primary_section_index.PrimarySectionIndex` consumes the
complete candidate JSONL and its reconstruction report under two independent
pins: `expected_candidate_sha256` and `expected_reconstruction_sha256`. The
latter is the reconstruction report's existing internal seal, retained outside
the supplied report. `reconstruction_report_sha256` separately hashes the full
report, including that seal, when a job needs a full-file-content JSON pin.

Enter the index once inside a native validation resource lease. It streams every
candidate row into temporary bounded SQLite, retains original candidate records,
checks the complete candidate hash and ordered population, and freezes its
deterministic input/census receipt. Subsequent `lookup_sections(legal_id)` calls
reuse that live index. `guard()` checks retained metadata and candidate/database
FD/path identities; the database becomes query-only. Context exit rehashes the
complete candidate and removes owned temporary storage. `index_sha256` identifies
the receipt, rather than SQLite bytes or the local cache path.

Default ceilings are 1 GiB candidate bytes, 4 MiB per JSONL line, 400,000 rows,
1,536 MiB SQLite disk storage, and 4,096 rows/16 MiB per lookup. Callers may lower
these through `limits`; exceeded bounds fail without a partial population claim.
SQLite disk capacity is distinct from the scheduler's memory reservation.

Lookup profile `literal_section_HAS_SOURCE_package_and_exact_manifest_release_point/v2`
returns every literal section candidate and original directed relationship
witness. Source packages and release points are separate target kinds. A release
point is recognized only with healthy unique transport, `node_type=release_point`,
`node_key=release_point:` followed by the independently pinned manifest value,
and a label exactly equal to that value. Other targets remain named observations
or issues. Neither label matching nor release context establishes applicability,
legal currentness, source-byte identity or governing context.

The retained real candidate contains 297,825 observations: 119,134 nodes and
178,691 edges. Its index receipt reports 59,520 section-to-package and 59,520
recognized section-to-release-point `HAS_SOURCE` witnesses. These are producer
relationships; they are not formalized definitions or reviewed legal assertions.

## Complete raw span reconciliation

`legal_span_section_bridge.reconcile_span_sections` takes raw rows, cache identity,
independent ordered row/record hashes, the live index and its expected pin,
an independently pinned identity policy, and independently pinned source bindings.
`validate_span_section_bridge` regenerates the complete result from those inputs.

Supported declared profiles are flat `span_export_fields/v1`, flat
`uscode-autoformal-span-evidence/v1`, and observation-only paired census v1/v2.
No alias fallback, legal-ID normalization, shortened revision expansion, first
match selection or label-derived identity is performed. Paired mock or
target-conditioned outputs do not become a supported formal AST.

Each explicit mapping has `record_sha256`, `source_span_id`, `source_sha256`,
`legal_id`, full `primary_revision`, full `source_revision`, `document_revision`,
`document_view_id`, `section_entry_cid` and `source_package_entry_cid`. The current
profile requires document/source revision equality. A unique section match alone
supplies none of these missing mappings or exact source occurrences. Existing
`legal_span_cache_intake` owns rule parsing and source-bound graph preparation.
V2 source selectors address the normalized document view, not raw HTML bytes.

Every output row retains the original raw row, physical ordinal, raw-row hash,
record hash, full existing intake observation, complete section lookup,
declared mapping, issues and open obligations. Repeated presentations remain
distinct. `population_complete` covers only the independently supplied batch;
it does not certify complete section or cache coverage.

```python
import json
from pathlib import Path
from ipfs_datasets_py.logic.autoformal.legal_primary_section_index import PrimarySectionIndex
from ipfs_datasets_py.logic.autoformal import legal_span_section_bridge as bridge_api
from ipfs_datasets_py.logic.autoformal import legal_source_graph_proposals as proposals

# Pins come from an independently retained trusted job receipt.
pins = json.loads(Path("trusted-job-pins.json").read_text())
reconstruction = json.loads(Path("primary-reconstruction.json").read_text())
rows = json.loads(Path("raw-span-rows.json").read_text())
inputs = json.loads(Path("span-bridge-inputs.json").read_text())
with PrimarySectionIndex("primary-candidate.jsonl", reconstruction_report=reconstruction,
        expected_candidate_sha256=pins["candidate_sha256"],
        expected_reconstruction_sha256=pins["reconstruction_sha256"]) as index:
    bridge_inputs = dict(inputs, section_index=index)
    bridge = bridge_api.reconcile_span_sections(rows, **bridge_inputs)
    bridge_api.validate_span_section_bridge(bridge, rows, **bridge_inputs)
    sidecars = json.loads(Path("proposal-row-inputs.json").read_text())
    trusted = dict(expected_bridge_sha256=pins["bridge_sha256"],
        bridge_inputs=bridge_inputs, row_inputs=sidecars,
        expected_row_inputs_sha256=pins["proposal_inputs_sha256"],
        expected_record_sha256s=inputs["expected_record_sha256s"])
    report = proposals.prepare_source_graph_proposals(bridge, rows, **trusted)
    proposals.validate_source_graph_proposals(report, bridge, rows, **trusted)
```

`span-bridge-inputs.json` supplies the reconciliation keyword inputs listed
above, excluding the live index. Its index, mapping, population and source
binding pins must come from independent custody rather than incoming self-seals.

## Explicit proposals and custody-complete review requests

One complete ordered sidecar is required for every physical record. Its exact
fields are `record_sha256`, `semantic_declarations`, `expected_scope_id`,
`expected_graph_sha256`, `context_packet`, `expected_context_sha256`,
`context_dependency_requests`, `dependency_manifest`, `expected_manifest_sha256`,
`required_dependency_ids`, `observed_artifact_sha256s`, `observed_pins`.
Use explicit null gaps rather than dropping unresolved records. The independent
`proposal_inputs_sha256` binds the entire sidecar population. Any supplied graph
pin is enforced before retaining a graph, even when review inputs are missing.

Existing `legal_semantic_graph` validates explicit mention/concept/definition/
assertion declarations and ordered AST transport. No lexical extraction,
surface-label merge, automatic definition equivalence or global entity merge
occurs. `means`, `includes` and `deems` remain distinct unreviewed tags.

`required_primary_artifacts` returns exact section/package records, every
recognized release-point record, all their typed relationship witnesses, and
the explicit source mapping as a hashed artifact. A review request requires all
of them in the complete independently expected forward dependency closure.
Existing dependency invalidation identifies stale/missing current inputs and
blocks requests; cycles remain named unresolved prerequisites. Existing `legal_graph_review` constructs
the exact subject after source/context custody replay. Request presence never
means a review was authenticated or an interpretation accepted.

All six v2 context slots remain open: definitions, authority, antecedents, shared
qualifiers, temporal origin and referenced provisions. Available content and
locators do not attach governing meaning. Missing or invalid custody remains
explicit; proposed entities and primary anchors cannot close these obligations.

## Observed limits and next work

The retained selected inputs are eight paired diagnostic rows and twelve rows
from `span-evidence.parquet`, at pinned Hub revision
`765176c6db79ba65c1697c21dead43666350b730`. Eighteen of the twenty presentations
have a unique literal section candidate; this is not eighteen distinct sections.
All twenty remain unresolved: full source revisions and independent per-record
source mappings are missing, and the eight paired rows also lack supported
formal transport. The files are nonrepresentative samples of the whole cache.

Primary source-package IDs, corpus source IDs, release metadata and producer
checksums are separate from official raw-HTML hashes. The current declarations
do not authenticate primary-to-official correspondence. No accepted graph view,
authenticated legal review, Lean admission or training eligibility is established.

Focused checks passed: 52 index cases, 27 bridge cases, 24 proposal cases and
10 retained actor-boundary cases, totaling 113. Native campaign qualification
and independent post-merge replay are still pending at this guide's preparation.

Next, acquire and pin original official source bytes; establish versioned exact
revision/view correspondence; inventory supported flat rows without sampling
away failures; attach independently reviewed governing definitions, exceptions
and cross-section context; then obtain authenticated legal/formal review.
Accepted views, doctrine composition and namespaced Lean modules remain later
gates. Preserve the existing caches and primary candidate while qualifying those
new associations through the supervisor's bounded jobs and independent replay.
