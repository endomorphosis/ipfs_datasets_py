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

For the original HTML/contextual profile, the existing evidence snapshot
budget applies to the report plus complete replay arguments: 128 MiB aggregate input, 4,000,000 traversed values, depth 96
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


## Explicit parent-literal nomination projection

The same owner provides `build_parent_norm_definition_graph_v1`,
`validate_parent_norm_definition_graph_v1` and
`export_parent_norm_definition_graph_v1` for the complete
[parent nomination report](legal_norm_definition_evidence_v1.md#explicit-parent-literal-nomination-companion).
Use the examples above with these explicit parent function names and the unchanged
arguments to `prepare_parent_norm_definition_evidence_v1`. Keep the independent
full-report and full-candidate hashes; `norm_definition_graph_sha256` serves both
profiles. The original HTML/contextual APIs retain their separate contract.

The parent candidate uses schema `legal-corpus-parent-norm-definition-graph/v1`
and profile `parent-literal-term-definition-nomination-custody/v1`. Genuine
opening and closing upstream replay retains the whole original norm and every
definition preparation/candidate externally. Sealed companions reference their
complete source bindings, ordered source occurrences, original parent contexts,
unavailable requirements and typed-use evidence. Context JSON hashes identify
those complete records; they are not hashes of newly extracted source bytes.
Every alternative, exact typed use and nomination remains unselected. Equal
spelling supplies no entity merge or governing-definition decision.

The route reuses the existing graph builders and Parquet exchange. Export
completes genuine upstream validation before bundle transport; physical-original
validation does not extend through the later writer. It emits only
`DERIVED_FROM`, `CITES` and `HAS_SOURCE` custody edges with closed local endpoints.
Retain the full candidate, upstream report and independently pinned replay inputs
beside the four-file graph bundle. The bundle does not contain or retrieve those
complete inputs. All authority flags stay false; selected interpretation and
governing definition use remain null; semantic, consumer, training and evaluation
gold masks remain integer zero.

The parent aggregate snapshot allows 1,500,000 traversed values, retaining the
128-MiB input, depth-96 and 32-MiB individual-byte-body limits. Existing corpus
record/graph bounds remain unchanged. Overflow refuses without truncation.
This explicit parent route supplies no mixed-sort/equality/modal lowering for
the retained §7214 alternatives and no reviewed statutory applicability.

The [accepted parent graph observation](../../../../../docs/autoformalization/evidence/legal-ir-parent-norm-definition-graph-20261025.json) passed **15 cases / 45 phases / 11 selectors**
(14 new cases and one legacy case) on the pinned `a9c8fbfd…` public snapshot
with two candidate overlays. The saved candidate has 55 nodes / 160 custody edges, two
alternatives, three exact typed uses, six nominations and 42 opaque source
references. Both alternatives retain nine source-occurrence and nine context
population members each; those totals do not count distinct statutory uses.
The norm retains six unavailable context requirements. The selected export/load
test performed a genuine Parquet roundtrip; the saved reader checked bytes and
framing without decoding Parquet again. Original compute/storage and both source
READs closed. This is a finite fixture result, separate from the original
81-case, 33-case and 29-case nomination observations. The later `fc3d8bbd…`
base changes one previously executed dependency and has separate source-only
compatibility review; identity is conditional on both old/new input bounds.
The added per-AST4096 limit may introduce unmeasured refusals. The combined
delivery generation was not executed or requalified. No model, training or Lean build ran; full-package behavior and
statutory meaning remain unqualified.


## Source publication and qualification generations

This graph-only source delivery retains the original adapter buffer. Its owning
test module preserves the original 25-case prefix and adds one case sharing the
same original companion with conditional complete-norm preparations. The branch
selector was independently published in PR1367; its source, guide and task
actions are reused. This graph delivery adds no second selector implementation.

The original `artifacts/legal-norm-definition-graph-20261017-01` qualification
passed 81 authored cases: 25 adapter, 20 graph and 36 exchange, with one
package-startup case deliberately deselected and no skipped selected cases.
Source/resource leases closed and child exit was observed. The original
512-MiB sampled scratch limit was not a named-root aggregate storage reservation.
Enrolled adapter/test equality was checked after launch; ordinary root package
startup, complete instantiated input archival and legal meaning were unqualified.

The separate [portable current-public integration record](../../../../../docs/autoformalization/evidence/legal-ir-graph-companion-integration-20261024.json) records **33 cases / 99 phases**:
26 adapter cases including the new shared-companion check, two existing
endpoint/genuine Parquet controls and five selector compatibility controls.
The retained candidate contains two alternatives, two typed uses, four ordered
nominations, 13 graph nodes and 24 custody edges. Both typed uses share one
fictional physical source target. No `USES_DEFINITION`, semantic entity,
governing-use edge or actual membership is inferred. The original complete norm
and conditional definition/membership premises remain unchanged. Statutory
source joins and meaning/applicability decisions remain null, with zero masks.

Two owning-test exports performed genuine Parquet write/load checks. The later
saved reader checked their durable bytes, framing and bookkeeping without
re-decoding Parquet rows or rerunning tests. The cohort used the genuine public
pytest helper, plain-source compilation and 149 checked compile/exec-filename
observations. Six initializer bypasses were declared and pinned; only
`logic/__init__.py` was observed bypassed, and the other five were uninstantiated.
Neither code-object identity, third-party cached bytecode nor whole-package or
environment behavior is attested. Original compute/storage and source READs
closed with 20 retained files / 3,962,353 bytes. No new model, training or Lean
execution occurred. The original 81-case graph, 30-case selector and 41-case core
qualifications remain separate and are not added to this cohort.

The first attempt remains a collection failure with zero tests. Its seven
regular files / 190,089 bytes remain unchanged after the original recovery owner
released its 128-MiB storage promise. That closeout does not qualify the failure
or alter the older retained native-v01 192-MiB reservation. Reuse the retained
2024 Title 10 dossier and exact producer-lineage gate in the
[handoff](../HANDOFF.md#selected-pilot-and-replay-input-follow-up); do not repeat
the exhausted paired rosters, progress lookup or census. Legal-as-of,
meaning and every-use applicability remain independent decisions. The published
selector's compatible persistent consumer remains separate work; numerical
baseline accuracy stays 0/4 typed or exact ID/AST matches.
