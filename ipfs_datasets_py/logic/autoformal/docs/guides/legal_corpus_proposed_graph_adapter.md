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
and its independently checked original receipts. At that original cutoff, this
was prepared for a selected local delivery; primary installation, publication and
legal/Lean admission had not been established. The wire-corpus-v2 qualification
below retains its separate local source/profile scope. Existing official, parent
and relational adapters retain their
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

## Explicit wire-coordinate corpus v2 over graph v3

`prepare_coordinate_graph_corpus_v2`, `validate_coordinate_graph_corpus_v2` and `export_coordinate_graph_corpus_output_v2` extend the same proposal-adapter owner. They share one candidate/projection loop and the existing validation/export engines with v1. Their public arguments match v1; the seven-field `intake_inputs`, nine-field `output_inputs` and three commitment/hash helpers above are unchanged. There is no additional request wrapper or commitment format. V1 remains explicit graph-v2 / original-input eligibility-v3 custody; v2 requires genuine wire graph v3, eligibility v4 and wire join v3. Neither route silently upgrades or accepts the other report.

The ordinary report schema is `legal-coordinate-graph-corpus/v2`; the export receipt uses `legal-coordinate-graph-corpus-output-export/v2`. Both carry `source_compatibility_profile="original-input-wire-coordinate-graph-v3-corpus-custody/v1"`, `metadata_profile="hf-default-parquet-envelope/v1"` and the genuinely replayed `source_metadata_intake_sha256`. The graph request/report must use their v3 schemas and `original-input-wire-coordinate-source-graph-intake/v1`; the eligibility request/report must use v4 and `original-input-wire-coordinate-target-eligibility/v1`. The retained join must use v3 and `paired-coordinate-hf-wire-three-cache-join/v1`. The graph, eligibility and join retain the same source-intake commitment and fixed metadata profile. Those declarations do not authenticate a remote source, governing edition or legal interpretation.

The report keeps exactly one original graph artifact in `intake_report_raw_utf8`; that graph retains one original eligibility artifact, whose join reference retains the original coordinate carrier. Raw-byte and canonical hashes, complete physical rows/references, output routes/ordinals and original source nominations stay distinct. Missing custody or unsupported output retains its full unresolved slot. Each supplied candidate is genuinely adapted and independently validated with the unchanged proposal/source owners, retaining exact proposal bytes, ordered typed AST, CIDs and source records. Mechanically supported `typed_deontic` / `typed-deontic-rule/v1` remains the upstream `canonical_rules_v1` route; this wrapper adds no logic family, entity resolver or reviewed definition.

Wire-v2 custody retains original and detached seven/nine-field inputs, parsed requests, genuinely returned graphs, adapter and checked candidates, live reports, runtime descriptions, producer sources and callable identities through closing replay and final serialization. Physical input nominations come only from genuinely regenerated graph/eligibility/join original bytes. Outer validation checks its own original/parsed snapshots before deriving any file plan, then holds the regenerated result through its own closing guards. Normal preparation and validation each perform two public graph-v3 validations. Export performs four: full-population validation, a fresh opening replay and a closing replay around the actual existing writer.

Export keeps the existing `manifest.json`, `snapshot.json`, `nodes.parquet` and `edges.parquet` format and bounds. It additionally retains directory/four-file identities and genuine `load_graph_bundle` readback results, actual writer manifest and live receipt through closing and final receipt serialization. A late original, callback, return-object or physical-file failure raises and returns no qualified receipt. Already written artifacts remain for inspection without cleanup, repair or resource-owner takeover. Retain the full report, candidate, originals and independent pins separately; the graph bundle contains envelopes. These sequential checks are not an atomic filesystem snapshot or arbitrary concurrent-writer protection.

The [closed selected authored qualification](../../../../../docs/autoformalization/evidence/legal-ir-hf-wire-coordinate-graph-corpus-20261024.json) for **attempt 03** passed **90 cases / 270 phases across 45 selected test functions**: 46 preceding corpus controls and 44 new wire-v2 controls. All 72 preceding owning cases remain byte-for-byte preserved; 26 were unselected. The appended owning file contains 116 cases across 56 test functions, not 116 executed cases. The earlier 152-case integration contained only 46 corpus cases; the separate 101/303 graph-v3 and other upstream qualifications are reused rather than rerun or pooled. Original source READ, native compute and retained storage custody closed. Earlier attempts remain separate with zero cohort qualification credit. Attempt 01 failed during collection with zero cases. Attempt 02 collected 90 cases and recorded 80 pytest passes, 10 failures, 260 phase passes and 271 journal records; all ten export failures came from the control audit interpreting genuine descriptor-relative opens as external writes (`external_write=10`, other guards 0). Its 80 passed calls do not qualify the cohort. Both failed attempts retain their original native/source closeouts and separately supported storage release; their files remain preserved. Attempt 03 corrects only that control boundary: the actual builtin open still receives the original relative basename and `dir_fd`, with thread-local exact audit-event binding, physically owned directory checks, five preflight refusals and positive read/write/pending observations. Product source and the corrected owning test are unchanged from attempt 02. Explicit namespace parents and actual pinned leaves retain their declared scope; public package initializers and the whole installed third-party runtime remain outside that qualification.

Source/edition correspondence, selected governing occurrences, legal meaning, context closure, entity/definition applicability, review, learning/gold and graph/Lean admission remain unresolved. All authority stays false; source-binding/training/gold masks stay plain integer 0 and selected occurrences stay null. Source-correspondence consumers retain their prior graph-v2 / eligibility-v3 profile until their own explicit adoption. Census and current-public dependency adoption remain separate. Eligibility declarations allow dimensions 0 or 384, but these fixtures exercised only 0. Zero is not the 8D lane. No 8D/384D/768D/4096D model, encoder, vector, training, convergence or Lean operation ran, and numerical/Lean owners are unchanged.

## Focused current-public dependency qualification

The [separate current-public dependency check](../../../../../docs/autoformalization/evidence/legal-ir-hf-wire-coordinate-graph-corpus-public-integration-20261024.json) passed **three existing cases / nine phases** on public base `e37f0117843ebd1ed8c559da12a959cabec51537` with the exact qualified corpus source and owning test. It covers genuine preparation/validation, actual writer and four-file bundle readback, and a closing-drift refusal that retains four unqualified files. The historical **90 cases / 270 phases** and earlier failed attempts remain separate and were not repeated or pooled.

The frozen profile retains 225 source/fixture files: 223 current-public files and only two corpus source/test overlays. Public `span_cache` (`e35f…`) and validation-helper (`cef7…`) bytes are preserved. Seven missing private context owners remain absent and import-denied; three excluded review seed modules are separately denied. Three public native-tooling files remain unexecuted context. The private pytest plugin and original native/resource owners remain qualification orchestration. Fourteen namespace parent bodies stay unexecuted and ten genuine initializer routes retain their actual frozen origins; 135 loaded origins and 125 checked import/compile entries do not establish whole-package qualification.

The descriptor-relative observer recorded 70 contexts, 62 successful reads, eight writes including two pending writes, five refusal controls and zero context errors, while preserving the actual relative basename/`dir_fd` calls. Original source READ, compute and storage custody closed; independent saved-result review accepted the result using original opaque file seals and stat-only payload readback. These sequential custody checks do not establish an atomic filesystem snapshot or arbitrary concurrent-writer protection.

These fixtures exercised metadata dimension 0 only. The inherited 0/384 eligibility declarations establish no encoder/decoder width compatibility, model quality, training or convergence. Census and source-correspondence consumers retain their older contracts. Source/edition/meaning, entity and governing-definition applicability and graph/Lean admission remain open; training and gold masks remain zero.


## Independent focused compatibility follow-up

The [separate ten-case qualification](../../../../../docs/autoformalization/evidence/legal-ir-hf-wire-coordinate-graph-corpus-focused-compatibility-20261024.json) reuses the same existing corpus owner and owning test. It adds no source implementation or tests and does not alter the historical 90/270 record or the peer's three-case/nine-phase public dependency result above. Its ten existing cases cover genuine v2 preparation/object validation and full-population writer/readback; complete unsupported-slot retention; recommitted reordered outputs; late physical-table drift; a primary error with genuine closing failure; postwriter physical-bundle drift; original inputs through final receipt serialization; wire-v3 refusal by old-v1; and one genuine old-v1 positive regression. All ten setup/call/teardown triples passed.

The actual qualification remains bound to base `e37f0117843ebd1ed8c559da12a959cabec51537` and its frozen generation. Peer publication `9368a8422fdc8ba676be6e65f9e48abd23eaa9f6` already supplies the identical source/test; the [source-equality receipt](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-programme-review-20261022-05/wire-corpus-public-port-v01/peer-publication-source-equality-v02.json) verified all 229 qualified inputs byte-for-byte, including public cache/helper bytes. No duplicate source port, source relocation qualification or test rerun was performed. This follow-up retains 229 frozen source/fixture files / 7,765,073 bytes and 256 request pins; those counts differ from the peer's independently scoped 225-file profile and must not be pooled.

The actual archive records 139 checked compile buffers/execution filenames, 140 module entries and 138 physical origins. The one required owning test module, twelve critical source paths and genuine public 1,489-byte pytest helper were observed. Nine initializer bodies were declared for namespace-creation bypass, with eight routes instantiated. All seven product bypass bodies stayed uncompiled/unexecuted: six product namespace routes were observed and bridge was unused. Pytest collection separately executed the predeclared repository path bootstrap and two inert test-parent bodies: five exact aliases share three physical initializer bodies. The two test-parent bodies have both earlier namespace-creation bypass records and later physical execution evidence. Ten ordinary product initializer bodies executed normally; three of five declared fileless namespaces were instantiated. These route, alias and physical-body counts are distinct. Actual source payload comparison and execution filenames do not attest code-object identity, cached/binary equivalence or whole public-package/third-party startup.

Genuine graph-bundle export and readback retain the historical descriptor-relative I/O boundary: original basenames, flags, modes and directory descriptors, positive read/write/pending observations and five refusal preflights. Those five guards are not additional pytest cases. The successful `wire-corpus-focused-v03` attempt retains 103 files / 9,249,778 bytes with original compute, selected storage, artifact durability and source READ closeout. The installed Arrow/NumPy observations apply to these authored fixture exports; no existing law-table scan, remote loader or source encoder ran.

Earlier current preparation/control refusals have no worker qualification credit. The admitted current v02 worker stopped at default pytest FD-capture startup on `/dev/null`, before collection: three files / 7,776 bytes remain, zero cases/phases are credited, compute and source READs closed, and its original 128-MiB storage claim is retained at the recorded cutoff without a durability assertion. Successful v03 restores the historical `-s` and `no:logging` startup flags, without widening the I/O allowlist or changing product/test bytes. The first saved-result reader subsequently rejected the three already pinned collection initializer bodies; the corrected metadata-only audit accounts for exactly five aliases without another test run. These current failures, historical original01/02 failures, historical90/270 success and peer3/9 success remain separate. Successful v03 cleanup does not close failed v02's retained storage or establish global cleanup.

All selected source/edition and physical joins, complete statutory norm/definition/two-use reviews, entity meaning, governing applicability, learning/gold and graph/corpus/Lean admission gates remain unchanged. The fixtures exercise metadata dimension zero, which is not the 8D lane; all 8D/384D/768D/4096D producer/checkpoint/target/context gates stay separate. No model, encoder, training, convergence, numerical reconstruction or Lean execution occurred.


## Retained section7346 b(2) parent-only candidate observation

The [actual retained observation](../../../../../docs/autoformalization/evidence/legal-ir-source7346-b2-parent-candidate-20261025.json) uses the existing source-occurrence and `segment` role from the 837-record parent collection. Its character[405,732)/UTF8[406,735) range contains the exact lexical anchor [645,660)/[648,663). The binder accepts that original role companion without a paired-cache match; `cache_row_record` remains null. No source/span/cache identity is synthesized. Two genuine public binder entries and explicit literal geometry were observed under the original owned operation; no pytest cohort was run. This observation retains its captured private source generation. Its separate static comparison at public10a3ec1b finds40/42 matching product blobs and two known differences in `legal_span_section_bridge.py` and `span_cache.py`; both public dependencies remain unchanged. At that retained-private observation's cutoff, public-snapshot execution compatibility was unmeasured; its saved-artifact review did not requalify canonical or public runtime. No product port or retest ran. The disjoint c candidate and its separate scope/correspondence qualification remain prior evidence. The source region and sentence roles remain unclassified/unselected, all six context requirements remain unavailable, and no complete typed use, governing source/edition/meaning, definition applicability, training/gold, graph or Lean admission follows. Future consumers must replay all original inputs through the existing owners; this observation is not a reusable substitute for their validation.


## Retained section7346 b(2) public product snapshot integration

The [actual public-snapshot integration](../../../../../docs/autoformalization/evidence/legal-ir-source7346-b2-parent-public-integration-20261025.json) reuses the existing b(2) source occurrence and role. Public product snapshot `f8a73cd849cc7202c08b50f469083d40649eb27d` executes at real `source-public-f8-v01/frozen` mirror paths with public mirror producer hashes; original private `970d590e…` native/orchestration custody remains a separate plane. The owned observation records one explicit parent build, one explicit validation and two binder entries. All837 original ordered record bytes/CIDs match, all16 paired rows remain present, and the cache-row companion remains null. Thirteen parent producer pins identify the public mirror, with a newly bound parent-manifest identity. Actual scientific package origins remain inside the public mirror; private-package execution is zero. No current whole-T deployment or private-orchestration product profile is thereby qualified. Earlier private/c results are not repeated or pooled. Existing source/span/cache identities, unclassified roles, six unavailable context requirements and zero masks remain unchanged. This supplies no typed statutory use, governing source/edition/meaning, definition applicability, model training/quality or graph/Lean corpus admission. Future consumers must still replay their original inputs through the existing owners.
