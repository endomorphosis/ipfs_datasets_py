# Existing legal proposal to candidate corpus graph

`logic/autoformal/corpus_proposed_graph_adapter.py` supplies an additive custody
bridge from the existing `legal_semantic_graph` owner to the candidate corpus
graph/exchange contracts. It keeps the original semantic identities, declarations,
ambiguity, ordered AST, and evidence/dependency references intact. It does not
replace either graph owner or infer legal entities, legal-role relationships,
source authenticity, independent review, definitions or admission.

## Accepted inputs and independent commitments

`adapt_proposed_graph_bytes` accepts one exact UTF8 JSON serialization of a
`legal-semantic-proposed-graph/v1` proposal. The caller separately supplies:

- `expected_proposal_sha256`, binding the exact original proposal file bytes.
- `trusted_proposal_inputs`, with exactly `ast`, `profile`, `source`, `scope`,
  `semantic_declarations`, `dependency_refs`, `evidence_refs`, and `scope_request`.
- `expected_inputs_sha256`, binding `canonical_dag_json_bytes(trusted_proposal_inputs)`.
- The full extracted official-shaped `document`, its exact `raw_html` bytes,
  and independently expected raw/extracted SHA256 values.

Original proposal inputs must come from the upstream custody boundary rather
than being copied from an untrusted proposal merely to make validation pass.
These commitments establish integrity relative to those supplied expectations;
they do not authenticate a government source or the caller's legal interpretation.

The adapter delegates complete AST/source/scope/declaration validation to
`legal_semantic_graph.validate_graph`. Supported profiles remain exactly those
of that owner: `canonical_rules_v1`, `normative_scope_v1` and the explicit
`relational_norm_v1` full-request profile. Flat canonical rule
strings are not arbitrary native FOL/TDFOL ASTs. The profile does not accept a
quantified definition/norm AST by relabelling it as a canonical rule.

The official source owner regenerates the normalized document and validates the
exact v2 selector against raw HTML. The selected source must fit one paragraph.
The adapter then constructs matching `corpus_source` source-version/occurrence
records. Character and UTF8 half-open selectors always address the extracted
view; no raw-HTML offset mapping is asserted. Edition, document revision,
normalization profile and the exact selected occurrence remain distinct bindings.
Repeated identical literals retain different occurrence identities.

## Preserved records and graph mapping

The sealed `legal-corpus-proposed-graph-candidate/v1` companion retains:

| Record | Preserved content |
| --- | --- |
| `proposal_record` | Exact original proposal JSON bytes represented as a UTF8 string, raw SHA256, existing graph ID and schema |
| `ast_record` | Exact original ordered AST, its content CID, original profile and selected source-occurrence CID |
| `input_binding` | External input/proposal digests, digest recipe, original-input CID and companion record links |
| `source_version`, `source_occurrence` | Independently hash-bound raw/extracted source identities and exact selected geometry |
| `issues` | Unreviewed interpretation, unverified context/external references, and opaque semantic/definition tags where present |
| `graph` | Closed candidate transport graph with explicit local endpoints |

The transport graph uses `source_version`, `occurrence`, `interpretation`,
`expression` and `issue` nodes. Its only relationships are `HAS_SOURCE` and
`DERIVED_FROM`. An AST tree edge is not a legal-role relationship. The existing
proposal graph ID remains the interpretation node's stable ID; existing entity
and assertion IDs remain unchanged inside the full proposal. This first bridge
does not flatten those populations into invented corpus entities or semantic
assertions. The AST is available for exact reconstruction and future separately
qualified projections.

`means`, `includes`, and `deems` tags remain unreviewed declaration metadata.
`definition_semantics_encoded=false` is retained. They do not establish a
biconditional, inclusion relation, applicability, or resolved term binding.
Actual section-local definition/norm semantics have their separate existing
bridge/profile and require an explicit future integration. A definition in a
different paragraph cannot be attached to this source occurrence by a text match.

All admission, formalization, semantic, source-authenticity, external-reference
and definition-semantics flags remain false. External references are preserved
declarations; no referenced artifact is fetched or authenticated by the adapter.
The common 1 MiB/JSON-depth/node bounds apply to the aggregate companion.
Duplicated proposal text, AST and graph envelopes may reach that bound earlier
than either underlying owner limit. Oversized or unsupported inputs fail without
truncation or ignored fields. Raw HTML must be nonempty and no larger than the
existing official extraction profile's 8,000,000-byte limit.

The relational profile uses `legal-corpus-proposed-ast-custody/v2`: `ast_json`
contains canonical JSON for the complete original request, `ast_sha256` commits
those bytes, and `ast_cid` commits the same logical AST. Storing that canonical
text avoids an extra envelope nesting level while all existing byte, node and
request-depth limits still apply. The other profiles retain their original v1
`ast` field and identical record construction. Canonical AST text does not claim
to reproduce the original request file's whitespace or key order.

Use `restore_proposed_graph_ast(candidate, **independently_bound_inputs)` to
recover either representation. It first regenerates the complete candidate from
original proposal inputs and exact source bytes, then returns a detached AST.
A self-sealed companion alone cannot authorize restoration. The
[relational graph guide](legal_relational_graph_v1.md) describes the supported
grammar and the distinction between a nominated paragraph and reviewed meaning.

## Validation and graph export

```python
from ipfs_datasets_py.logic.autoformal.corpus_proposed_graph_adapter import (
    adapt_proposed_graph_bytes,
    export_proposed_graph_candidate,
    validate_proposed_graph_candidate,
    restore_proposed_graph_ast,
)

candidate = adapt_proposed_graph_bytes(proposal_bytes, **independently_bound_inputs)
validate_proposed_graph_candidate(candidate, **independently_bound_inputs)
restored_ast = restore_proposed_graph_ast(candidate, **independently_bound_inputs)
manifest = export_proposed_graph_candidate(
    candidate, new_graph_directory, **independently_bound_inputs
)
```

Validation regenerates every nested record and transport edge from the exact
original proposal serialization, independent inputs and source bytes. Repaired
outer hashes cannot authorize changed AST order, source geometry, semantic
declarations, dependency references, issues or authority flags.

Export delegates to the existing [candidate graph exchange](legal_corpus_graph_exchange.md).
It exports graph envelopes only. Retain and independently hash the full companion
candidate, original proposal inputs and raw/source artifacts separately; their
payloads are not implicitly embedded in `nodes.parquet` or fetched through CIDs.
The Parquet bundle's `external_references_verified` remains false. Relational
validation performs native syntax checking and Lean text generation; it runs no
Lake build or model. No reviewed statutory corpus or publication is claimed.


## Literal parent fields without HTML

The explicit `legal-semantic-parent-literal-source/v1` binding uses the existing
[physical parent adapter](corpus_parent_occurrence_adapter.md). It consumes its
complete detached bundle, the independently expected manifest CID, an exact
source-occurrence CID and an exact role or cache-match companion CID. The binder
calls `validate_parent_occurrence_corpus` with original report bytes, both report
pins, replay inputs and lower-only limits. Every original physical input must
still be available. An inventory containing hashes without text cannot supply
this replay.

```python
from ipfs_datasets_py.logic.autoformal import legal_semantic_graph as proposed
from ipfs_datasets_py.logic.autoformal import corpus_proposed_graph_adapter as corpus

source = proposed.bind_parent_source_occurrence(parent_bundle, **parent_inputs)
scope = proposed.bind_parent_scope(
    source=source, jurisdiction="declared US-federal", instrument="unresolved",
    applicability="unresolved", definition_scope="unresolved",
)
# Build the proposal with the existing API and an explicitly authored/model AST.
# Pin its serialized bytes and independent input dictionary as above.
candidate = corpus.adapt_parent_proposed_graph_bytes(
    proposal_bytes, parent_bundle=parent_bundle, **parent_inputs, **proposal_inputs
)
corpus.validate_parent_proposed_graph_candidate(
    candidate, parent_bundle=parent_bundle, **parent_inputs, **proposal_inputs
)
```

Here `parent_inputs` contains `expected_manifest_cid`, `source_occurrence_cid`,
`companion_record_cid`, `report_bytes`, `expected_report_pins`, `replay_inputs`,
and optionally `limits`. `proposal_inputs` contains `expected_proposal_sha256`,
`trusted_proposal_inputs`, and `expected_inputs_sha256`.

The resulting `legal-corpus-parent-proposed-graph-candidate/v1` preserves the
existing source-version and occurrence records without rebuilding them through
HTML. Its `parent_source_binding` retains the parent companion, role/cache-match
companion, cache-row companion where applicable, required-unavailable context,
and complete population manifest CID. Keep the full detached parent collection
and originals separately: the graph export contains envelopes, not all evidence.
Restoration and export use the existing `restore_proposed_graph_ast` and
`export_proposed_graph_candidate` APIs; they dispatch by explicit candidate
schema and require all inputs again.

The physical repository, immutable revision, file hash, complete-row hash,
row/group ordinals and literal `text` field remain distinct from a declared legal
ID. Repeated text and identical physical rows retain separate occurrence/source
identities. Nominating an occurrence for a proposal does not select a governing
source: all original unselected flags remain unchanged and the complete
alternative population stays externally bound. Entities use existing corpus
occurrence records as their `source_selector`; containment and exact Unicode and
UTF-8 offsets must agree within the nominated source span.

The edition remains `not_declared_in_source_artifact`. The separate
`legal-semantic-parent-declared-scope/v1` names caller-declared scope against that
physical source version, without upgrading applicability or context. No HTML
view ID, paragraph number, official edition, normalization or statutory unit is
invented. The official source/scope route remains unchanged.

`build_graph` checks source binding structure and AST transport. Complete physical
replay occurs in the parent binder and corpus adapter; a resealed source packet
alone is not physical-source verification. The new route retains the existing
aggregate byte/depth/node limits and refuses oversize payloads without truncation.
No parser, training job, model inference or Lean build is introduced.

This route supplies proposed graph custody only. The official V2 definition
bridge requires its own exact whole-source contributor units, edition and scope.
Unclassified literal regions or sentence candidates cannot be relabeled as
those units. Qualified definitions, governing context, source authenticity,
review and legal correctness remain unresolved.
