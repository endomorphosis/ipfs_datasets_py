# Source-bound semantic graph proposals

`legal_source_graph_proposals.py` owns independently supplied entity and
relationship proposals. Its existing `prepare_source_graph_proposals` and
`validate_source_graph_proposals` entrypoints retain their section-bridge
contract. Their output is preparatory evidence, with unresolved source,
definition, context, review and admission obligations.

## Wire-coordinate semantic proposals v1

Use `prepare_coordinate_semantic_graph_proposals_v1` and `validate_coordinate_semantic_graph_proposals_v1` for the explicit wire-coordinate profile
`original-input-wire-coordinate-authored-semantic-proposals/v1`. The request schema is `legal-coordinate-semantic-graph-proposals-request/v1`; the report schema is
`legal-coordinate-semantic-graph-proposals/v1`. Supply the complete independently pinned request bytes,
the exact graph-v3 report bytes and their independent hash, and the complete
original graph-v3 input bundle. The genuine graph owner regenerates the
wire graph-v3 / eligibility-v4 / join-v3 ancestry from the original physical
files. A report seal alone is insufficient.

Preparation takes `request_raw`, `graph_report_raw`, independent
`expected_request_sha256` and complete `graph_originals`. Validation also
takes the offered report and independent `expected_report_sha256`. Reuse
`coordinate_semantic_graph_proposals_originals_sha256` for the seven-field
originals commitment and `coordinate_semantic_graph_proposals_sha256` for
the complete report commitment.

The request's six fields are `schema`, `profile`,
`graph_report_raw_sha256`, `graph_report_sha256`, `graph_originals_sha256`
and `output_inputs`. Each output input has exactly seven fields:
`output_occurrence_ordinal`, `physical_identity_sha256`, `route`, `ordinal`,
`semantic_declarations`, `expected_scope_id` and `expected_graph_sha256`.

The request contains a complete ordered declaration slot for every upstream
output occurrence. Slot identity includes output-occurrence ordinal, physical
identity hash, route and route ordinal. Two alternatives from one physical
row remain separate slots; no alternative is selected, deduplicated or merged.
Each slot supplies explicit semantic declarations or an explicit null, its
expected scope identity and an optional expected graph hash. Missing,
reordered or duplicate slots refuse the operation.
Null declarations require both associated pins to be null; nonnull
declarations require a scope identity. For a supported upstream graph, an
invalid declaration, disagreeing scope or disagreeing supplied graph hash
refuses rather than being silently repaired. A retained declaration on an
unsupported output acquires no validated semantic graph.

Authored mention, concept and definition declarations and ordered assertion
arguments pass to the existing semantic graph builder. Source, scope, AST,
dependency and evidence references come from the validated upstream graph
request. The exact AST must round-trip. No entity meaning is inferred from
the sibling physical entity census or from cache labels. An unsupported
upstream output or a missing declaration remains explicitly unresolved.

The original wire graph-v3 and coordinate corpus-v2 profiles are unchanged.
For a supported individual proposal, the existing general
`adapt_proposed_graph_bytes` adapter can consume its exact graph bytes and
independently pinned complete graph inputs together with original source
document bytes. Coordinate corpus-v2 does not acquire a semantic side channel.

Input and output bounds refuse overflow rather than omit declarations or
evidence: 4 MiB request, 64 MiB upstream report bytes, 128 MiB aggregate
inputs/report and 256 output slots. Existing per-graph bounds remain 1 MiB,
256 entities, 512 assertions and 128 references per reference list.
Opening and closing validation retains actual upstream returns,
caller inputs and graph-builder inputs and returns. Final encoding is followed
by custody and physical-file checks. These ordered observations do not provide
an atomic multi-file snapshot or attest complete third-party loaded code.

Every graph remains a `proposed_unreviewed` proposal. All authority flags are
false and training/evaluation-gold masks are plain integer zero. This API
does not resolve source authenticity, governing edition, legal meaning,
definition applicability, context closure, human review or graph/Lean
admission. It executes no representation model or Lean toolchain.

The [selected focused qualification](../../../../../docs/autoformalization/evidence/legal-ir-wire-coordinate-semantic-proposals-20261024.json) passed **48 cases /
144 phases** across two disjoint campaigns under the original source,
compute and storage owners.
Only the selected authored fixtures and declared source execution profile
are qualified. Whole-module/package startup, real statutory interpretation,
8D/384D/768D/4096D model behavior and Lean admission remain separate.

When preparing a bounded qualification capture, inspect selected package
initializers and availability probes in addition to observed module origins.
A `find_spec` probe can require an existing source file without executing it:
pin its exact bytes and retain its unexecuted status. Preserve a refused
generation and its original cleanup evidence; correct the explicit source
list in a fresh immutable generation instead of adding a lazy import fallback.
Keep every campaign within its original resource limits. Partition larger
selections into independently admitted disjoint cohorts and record their
complete union; progress marks cannot replace terminal case, phase, source
and cleanup evidence.
