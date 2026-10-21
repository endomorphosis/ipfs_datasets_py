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

## Complete coordinate graph corpus custody

Qualification: **46 passed cases / 138 passed phases** (43 new coordinate cases
and three existing official-adapter regressions), with 232 frozen source files.
The original validation owner closed source, native and storage custody. See
`workspace/test-logs/federal-corpus-audits/legal-ir-coordinate-corpus-custody-20261021-01/qualification-summary.json`
and its independently checked original receipts. This is prepared for a selected
local delivery; primary installation, publication and legal/Lean admission are not
established. Existing official, parent and relational adapters retain their
original contracts; this cohort does not newly qualify the broader profiles.

The coordinate corpus profile requires the explicit upstream graph-intake v2
and genuine original-input eligibility v3 contracts. It does not reinterpret
historical graph v1 or retained-row eligibility v2 as that evidence, and has no
silent fallback. Its schema is `legal-coordinate-graph-corpus/v1`, with
`source_compatibility_profile=original-input-coordinate-graph-v2-corpus-custody/v1`.
Upstream graphs are still proposed `canonical_rules_v1` graphs constructed from
supported `typed_deontic` / `typed-deontic-rule/v1` outputs. Other logic families,
relational norms and reviewed definitions do not become supported by entering
this wrapper.

```python
coordinate_graph_corpus_originals_sha256(intake_inputs)
coordinate_graph_corpus_inputs_sha256(output_inputs)
coordinate_graph_corpus_sha256(report)

prepare_coordinate_graph_corpus_v1(
    intake_report_raw, *, expected_intake_raw_sha256,
    expected_intake_sha256, intake_inputs, expected_intake_inputs_sha256,
    output_inputs, expected_output_inputs_sha256,
)
validate_coordinate_graph_corpus_v1(
    report, intake_report_raw, *, expected_report_sha256,
    expected_intake_raw_sha256, expected_intake_sha256, intake_inputs,
    expected_intake_inputs_sha256, output_inputs,
    expected_output_inputs_sha256,
)
export_coordinate_graph_corpus_output_v1(
    report, output_occurrence_ordinal, output_directory, intake_report_raw,
    *, expected_report_sha256, expected_intake_raw_sha256,
    expected_intake_sha256, intake_inputs, expected_intake_inputs_sha256,
    output_inputs, expected_output_inputs_sha256,
)
```

`report` is an ordinary bounded JSON report, not an additional sealed corpus
record. Its full canonical hash omits no fields. The exact raw upstream artifact
pin `expected_intake_raw_sha256` is distinct from `expected_intake_sha256`, the
existing graph-intake owner's complete canonical identity. Independently retain
both pins, all original bytes and the two input commitments; a report's own hash
fields are not independent evidence.

### Complete upstream originals

`intake_inputs` is an ordinary closed mapping of exactly seven fields:

```text
request_raw
eligibility_report_raw
eligibility_request_raw
join_manifest_raw
expected_request_sha256
join_originals
source_bindings
```

These are the complete arguments to
`legal_span_cache_intake.validate_coordinate_source_graph_intake_v2`, excluding
the offered report and its separately supplied expected report hash. The graph
request must use `legal-coordinate-source-graph-intake-request/v2` and
`original-input-coordinate-source-graph-intake/v1`. Its eligibility request must
use `legal-source-span-target-eligibility-request/v3` and
`original-input-coordinate-target-eligibility/v1`. The upstream report must have
the corresponding graph v2 schema/profile. A valid retained-row eligibility
report remains a different contract.

The originals helper represents each of the four exact byte arguments by
SHA256 and byte length, retains the independently pinned graph request identity,
uses the existing public eligibility helper to commit the complete
`join_originals`, and commits the ordinary canonical source-binding-map bytes
by SHA256 and length. It then hashes the ordinary canonical identity mapping.
No original byte buffer is replaced by a parsed report projection. The existing
closed eight-field `join_originals` contract, complete physical population and
source-binding declarations remain required at every replay.

`source_bindings` keeps the upstream physical-identity keys and the original
document, raw-HTML base64, revision, scope and selector declarations. The wrapper
uses that original nominated document and HTML; it does not fetch another
source or generate an official edition from the cache. These declarations
retain the upstream unverified crosswalk and review status.

### Independent per-output custody

`output_inputs` is a complete ordered list of at most 128 closed slots, one per
upstream output occurrence. A zero-output upstream population requires an empty
list. Each slot has exactly these nine fields:

```text
output_occurrence_ordinal
physical_identity_sha256
route
ordinal
expected_proposal_sha256
trusted_proposal_inputs
expected_inputs_sha256
expected_raw_sha256
expected_extracted_sha256
```

The first four fields identify the exact upstream output: complete-list ordinal,
physical row identity, producer route and route-local formal-output ordinal.
Ordinals must be ordinary integers, not booleans. Repeated text, repeated graph
content and matching compiler outputs do not collapse those identities.

The last five fields are either **all `None`** or all supplied. All `None`
explicitly records unavailable corpus custody. A supported upstream graph with
missing custody remains an unresolved slot; it is not dropped. An unresolved
upstream graph requires all five fields `None`. Partial, malformed or mismatched
supplied custody is refused rather than reclassified as missing evidence.

For supplied custody, `trusted_proposal_inputs` has the existing full eight
fields: `ast`, `profile`, `source`, `scope`, `semantic_declarations`,
`dependency_refs`, `evidence_refs` and `scope_request`. It must exactly match the
genuinely replayed upstream `graph_request`, with the producer's explicit default
`semantic_declarations=None` and `scope_request=None`. No trusted input is
manufactured by copying a self-sealed candidate. New entity/assertion declarations
cannot be injected through these sidecars.

The proposal byte recipe is exactly
`canonical_dag_json_bytes(genuinely_replayed_graph)`, independently pinned by
`expected_proposal_sha256`. The complete eight-field proposal input hash uses
the existing `INPUT_DIGEST_RECIPE`; it is not the AST-only hash, graph ID or
complete intake hash. `expected_raw_sha256` pins the exact original nominated
HTML bytes; `expected_extracted_sha256` pins the complete original nominated
document's UTF-8 `document_text`. Source selectors still address the normalized
extracted view rather than raw HTML offsets.

The output-input helper validates the closed slot structure and computes SHA256
over the complete ordinary canonical JSON list. It includes missing slots and
their original order. Computing a commitment cannot authorize incorrect source,
proposal or input pins; preparation checks those against genuine replay before
calling the existing adapter.

### Existing candidate construction and lossless report

Preparation genuinely validates upstream graph v2 on opening and closing,
against every original argument. For each complete supplied slot it calls the
unchanged `adapt_proposed_graph_bytes` and
`validate_proposed_graph_candidate` with independent inputs and original source
bytes. Candidate records keep the existing schemas, CIDs, ordered AST and
source-version/occurrence records. The wrapper creates no new AST codec, entity
resolver or legal-role graph projection.

The outer report retains the exact upstream intake artifact once in
`intake_report_raw_utf8`, with its raw and canonical pins. Its complete typed
eligibility/join/carrier references retain their original names and values inside
that artifact; they resolve within their original upstream containers. The
wrapper does not duplicate the full intake artifact inside individual rows or
retarget upstream coordinate pointers.

`physical_rows` and `row_references` retain the complete upstream populations.
Every `output_occurrences` slot keeps its four identity fields and the complete
original upstream row in `intake_output`, including eligibility output and
coordinate lineage. `candidate` is the existing sealed candidate or `None`.
Disposition is `candidate_corpus_custody` or `unresolved`; missing custody uses
issue `custody_inputs_not_supplied`, and unresolved upstream graphs use
`upstream_graph_unresolved`. Counts distinguish physical rows, references,
outputs, candidate outputs and unresolved outputs.

All authority remains false. Source/edition correspondence remains
`unverified_no_independent_crosswalk`, entity binding remains
`unavailable_semantic_companions_not_supplied`, selected occurrence remains
`None`, and training, evaluation and source-binding masks remain integer zero.
The original proposed graph's nominated source occurrence is custody evidence;
it is not an admitted historical coordinate occurrence or governing statute.

### One-output export and its lineage receipt

Export requires an explicit ordinary integer `output_occurrence_ordinal`. It
first validates the full report and complete output population. It rejects an
unresolved selected slot and delegates one candidate to the unchanged
`export_proposed_graph_candidate`. This is not an aggregate writer that silently
exports a usable subset.

The existing graph writer performs its own real bundle load/readback. The new
wrapper neither replaces that serializer nor adds another graph format. Its
receipt has schema `legal-coordinate-graph-corpus-output-export/v1` and binds:

- Independently expected `corpus_report_sha256`.
- The four exact selected output identity fields.
- `candidate_record_cid` and the unchanged returned `graph_manifest`.
- `graph_manifest_sha256`, SHA256 of `canonical_dag_json_bytes(graph_manifest)`.
- The exact `snapshot_cid` and `delegated_writer_readback_performed=True`.
- `full_candidate_retained_separately_required=True`, false authority and zero masks.

The graph bundle still contains envelopes rather than the full corpus companion,
raw proposal/source artifacts or replay originals. Retain the full ordinary
report, full candidate and complete original inputs separately under their
independent pins. A graph bundle or its manifest alone cannot replay custody or
authenticate external content references.

Export keeps genuine upstream custody open around the actual writer and closes
it afterward. A late callback, source-table or input mutation raises even if the
writer already created a loadable bundle. Failed written artifacts are retained;
no qualified receipt is returned and this API does not delete, repair or take
over their original resource owner.

### Bounds and closing observations

| Surface | Unchanged or lower bound |
| --- | --- |
| Ordinary outer report and complete output-input JSON list | 64 MiB each |
| Complete output-slot population | At most 128 |
| Upstream graph and eligibility request bytes | 128 KiB each |
| Eligibility and join artifact bytes | 16 MiB each |
| Original source-binding map | 8 MiB |
| Original join replay inputs | Existing 8 MiB aggregate and per-field limits |
| Each existing candidate/common sealed envelope | 1 MiB, depth 20, 25,000 JSON nodes |
| Upstream graph population and graph payload | Existing graph-v2/source/eligibility bounds |

The 64 MiB outer ceiling does not enlarge any 1 MiB candidate limit. A supplied
candidate that exceeds its existing adapter bounds fails the operation; it is
not truncated, sampled or silently omitted. Underlying HTML, normalized view,
graph, CID and exchange bounds remain in force.

Closing checks genuinely replay the upstream graph operation, compare live and
detached intake/output originals with their independent commitments, inspect
producer source hashes and operation callable identities, then recheck originals
and producers after delegated closing work. The public validator also fences
the offered report. Export additionally fences the offered and validated report
around actual writing. Secondary failures are attached without replacing a
primary `BaseException`.

These are ordered source/callback/custody observations, not an atomic filesystem
snapshot, arbitrary concurrent-writer protection or complete loaded-byte
attestation. Replaying a candidate is not current source/review/revocation
authorization. No current-edition crosswalk, legal meaning, governing definition,
every-use applicability, training/gold admission, model accuracy or Lean proof
follows from this profile. No model, new training, provider call or native Lean
execution occurred in this focused engineering qualification.
