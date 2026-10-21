# Candidate graphs for exact definition-evidence nominations

`logic.autoformal.corpus_norm_definition_adapter` projects a completely replayed
[`legal_norm_definition_evidence_v1`](legal_norm_definition_evidence_v1.md) report
into the existing corpus graph format. It preserves the declared alternatives
and exact typed occurrences through sealed custody companions. It performs no
AST transformation, predicate aliasing, source-role inference or selection of a
governing definition.

## Complete replay before graph construction

```python
candidate = build_norm_definition_graph_v1(
    original_evidence_report,
    expected_report_sha256=independent_full_report_hash,
    **original_evidence_inputs,
)
candidate_hash = norm_definition_graph_sha256(candidate)

validate_norm_definition_graph_v1(
    candidate,
    original_evidence_report,
    expected_graph_sha256=independent_full_candidate_hash,
    expected_report_sha256=independent_full_report_hash,
    **original_evidence_inputs,
)
```

`original_evidence_inputs` contains the unchanged arguments to
`prepare_norm_definition_evidence_v1`: `norm_preparation`, `request_raw`,
`expected_norm_preparation_sha256`, `expected_request_sha256`, `norm_inputs`
and `definitions`. Positional arguments accepted by that original operation
also remain usable. The upstream validator replays the complete norm/source
correspondence, contextual definition endpoints and any supplied original
definition-review assessments. A saved status or a new local hash is not a
substitute for those original inputs and their independent commitments.

`expected_report_sha256` identifies the complete canonical upstream report.
`expected_graph_sha256` identifies the complete canonical adapter candidate,
including all companions and the graph. It is not the nested graph snapshot's
CID or hash. `norm_definition_graph_sha256` computes that complete bounded
candidate hash. Original raw-file hashes, canonical report hashes and record
CIDs retain their separate meanings. Independent expected values must come
from retained provenance, not from an untrusted incoming replacement.

Validation first checks the candidate envelope and independent full hash. A
deterministic projection precheck detects altered companions or graph geometry
against the committed report before costly source replay. Success still requires
the complete upstream validation and exact regeneration. Repairing an outer CID
or graph hash cannot substitute for that original evidence.

## Companions and identity

The candidate uses schema `legal-corpus-norm-definition-graph/v1` and profile
`exact-term-definition-nomination-custody/v1`. All companions use the existing
sealed corpus-record contract.

| Field | Retained information |
| --- | --- |
| `report_record` | Original report schema/profile, full report hash, raw nomination-request hash and original counts. The full report remains external. |
| `norm_record` | Original preparation/correspondence, scope and typed/native AST hashes; complete hashes of source context, unresolved issues, source-context slots and norm obligations. |
| `definition_records` | Every alternative in original endpoint order, with its ordinal/identity, full endpoint commitment, candidate pins, original source/scope/definition/term/AST references and ordered physical source-occurrence references. Original review status, assessment hash and recorded evaluation time remain historical observations. |
| `use_records` | Each distinct exact typed path in first-link order, with the complete typed target/node/row, binder and modal/connective ancestry, predicate argument position/declared role, ordered inverse source paths and complete original source rows. |
| `source_records` | First-seen exact original norm-target and required-definition-subject references, distinguished by reference kind. Their original reference fields and complete hashes are preserved. |
| `nomination_records` | Every original link in order, with its complete request link and link hash, exact use/alternative/source companion CIDs, original nomination/support records and original term/AST references. |

Two uses with the same variable spelling remain distinct when their typed paths
or binders differ. Repeated links to a use must agree on its complete occurrence
evidence. Physical source identity and typed-expression occurrence identity are
different: a source row may support several typed occurrences, and several
alternatives may remain nominated for one occurrence.

Definition alternatives are not declared globally mutually exclusive. The
projection preserves each link's exact use/alternative pair and does not impose
an alternative group across unrelated uses. Graph node and edge envelopes have
the existing canonical CID order; companion arrays preserve their declared or
first-seen order explicitly.

Source companions are opaque provenance assertions. They are graph
`interpretation` nodes, not newly invented `corpus_source` occurrences. A source
subject reference is not silently relabeled as an occurrence record or given
new character/byte coordinates. Typed uses are `expression` nodes. All other
companion nodes are `interpretation` nodes; no new legal entity or norm assertion
is inferred.

Only `DERIVED_FROM`, `CITES` and `HAS_SOURCE` custody edges are emitted. All graph
endpoints refer to local graph-node CIDs, and edge evidence names retained sealed
companions. A nomination cites its explicit definition alternative and both
opaque source references. No `USES_DEFINITION`, `DENOTES`, `DEFINES` or semantic
role edge is supplied. Graph connectivity does not prove applicability or meaning.

## Bounds, producers and mutation checks

Public import loads the corpus record/graph primitives and does not load the
norm, source, native parser, review or model operation owners. At explicit use,
the adapter reuses the existing evidence hash, aggregate snapshot and pure
preflight contracts before loading operation owners. Original and detached full
inputs are checked before replay, after replay and after graph serialization.
The adapter, corpus primitives and actual upstream producer closure are pinned
and checked across the operation. Caller-supplied producer paths are not opened
as authoritative source locations.

The existing evidence snapshot budget applies to the report plus complete
replay arguments: 128 MiB aggregate input, 4,000,000 traversed values, depth 96
and a 32-MiB maximum individual byte body. Original endpoint limits still apply.
The upstream report retains its existing 8-MiB bound. Each companion and the
complete sealed projection obey the unchanged corpus limits: 1 MiB, JSON depth
20 and 25,000 nodes. Existing graph limits are 4,096 nodes and 8,192 edges.
Overflow refuses the complete operation without dropping alternatives, links,
source rows or obligations. These bounds can make an otherwise valid upstream
report too large to project. The combined report-plus-input snapshot can also
exceed the aggregate budget even when each fits its upstream operation
separately. The adapter does not promise to project every valid upstream report,
and these bounds are not process-memory reservations.

The full upstream report and replay inputs remain external. Their references
are sufficient to check custody when supplied, but are not a retrieval service
or a complete self-contained source archive.

## Export and review boundaries

```python
manifest = export_norm_definition_graph_v1(
    candidate,
    new_bundle_directory,
    original_evidence_report,
    expected_graph_sha256=independent_full_candidate_hash,
    expected_report_sha256=independent_full_report_hash,
    **original_evidence_inputs,
)
```

Export performs complete validation before calling the existing
[`corpus_graph_exchange`](legal_corpus_graph_exchange.md). The Parquet bundle
contains graph envelopes. Retain the full candidate companions, original
evidence report and all independent replay inputs separately. Loading a bundle
does not retrieve referenced payloads or establish source semantics.

Every authority flag remains false; training/evaluation masks remain integer
zero, and selected interpretation and governing definition use remain null.
The original review assessments are replayed at their original supplied times.
This is not a fresh current-time authority assessment, and their signatures do
not cover this new graph projection. No signer, policy, review decision or new
acceptance mechanism is created.

Upstream replay may parse native formulas and generate Lean text. This adapter
executes no model, training, solver, Lean build, publication or accepted-state
mutation. Engineering fixtures qualify custody and rejection behavior only;
actual governing definition application and independently reviewed statutory
composition remain separate requirements.
