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
of that owner: `canonical_rules_v1` and `normative_scope_v1`. Flat canonical rule
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

## Validation and graph export

```python
from ipfs_datasets_py.logic.autoformal.corpus_proposed_graph_adapter import (
    adapt_proposed_graph_bytes,
    export_proposed_graph_candidate,
    validate_proposed_graph_candidate,
)

candidate = adapt_proposed_graph_bytes(proposal_bytes, **independently_bound_inputs)
validate_proposed_graph_candidate(candidate, **independently_bound_inputs)
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
The Parquet bundle's `external_references_verified` remains false. No complete
Lean release, compiler execution, model execution, reviewed statutory corpus or
publication is claimed.
