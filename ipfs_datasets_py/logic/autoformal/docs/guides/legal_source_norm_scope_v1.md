# Sampled source to normative scope transport

`legal_source_norm_scope_v1` binds a caller-authored, incomplete scope declaration to one exact whole sampled statutory paragraph. It reuses the existing official V2 view, sampler, source records, normative scope validator and frozen scope bridge. It introduces no new logic AST.

This is the first source/coverage deliverable described in the [statutory norm-gap specification](../../../../../docs/autoencoders/legal_ir_statutory_norm_profile_gaps_20261015.md). The owner was adopted from a retained isolated implementation; the [integration report](../../../../../docs/autoencoders/legal_ir_norm_integration_20261015.md) distinguishes its historical qualification from the active checkout. This source-scope profile does not implement the later relational, cardinality, modal-scope or lowering stages.

```python
from ipfs_datasets_py.logic.autoformal.legal_source_norm_scope_v1 import (
    prepare_sampled_norm_scope_v1,
    validate_sampled_norm_scope_v1,
)

proposal = prepare_sampled_norm_scope_v1(
    sampling_report,
    raw_html,
    scope_request_raw,
    scope_declaration_raw,
    expected_sampling_report_sha256=independent_sampling_sha256,
    selected_unit_ref=exact_sampled_unit_reference,
    expected_scope_request_sha256=independent_request_bytes_sha256,
    expected_scope_declaration_sha256=independent_declaration_bytes_sha256,
    descriptor=original_acquisition_descriptor,
    expected_descriptor_sha256=independent_descriptor_sha256,
    expected_raw_sha256=independent_raw_sha256,
    expected_raw_bytes=independent_raw_size,
)
```

Independent expected hashes come from the retained input manifest. Computing new hashes for substituted inputs does not establish the identity of an earlier proposal. Validation regenerates the complete result from the originally pinned inputs. A unit ordinal is not an index into the sampler's record array; selection requires the exact sealed unit reference.

`validate_sampled_norm_scope_v1` takes the proposal followed by the same preparation inputs, plus `expected_report_sha256`. `sampled_norm_scope_report_sha256` computes the full canonical output digest for retention in an independent manifest. The internal `report_sha256` is a separate payload seal and excludes its own field.

The bridge checks original request/declaration transport bytes before operation imports, replays the full sampling population, and resolves the selected source version, occurrence and context through their sealed references. The caller's `source_text` must equal the entire selected paragraph. Every source-origin anchor is mapped from local Unicode code points to exact document characters and UTF8 bytes using the original normalized view. Raw HTML offsets are a different coordinate system.

This first profile preserves the sampler's original required-unavailable context observation. The scope request has empty `required_unavailable` context, partial or unassessed semantic coverage, and explicit unresolved meaning records. Coverage segments must account for every source character, including unsupported material and suffixes. Complete literal accounting is a custody/geometry check; it does not establish complete meaning or an exhaustive dependency inventory. Separate contextual nominations remain available evidence and are not applied or adjudicated by this bridge.

The legacy `actor` and `object` fields carry caller-proposed lexical slot attachments. In a passive clause, placing the grammatical subject in that slot does not identify the agent performing the action. A four-slot lexical declaration is not a compositional interpretation of the law. Necessary versus sufficient approval, action coordination, direction, counting frame, purpose, pronoun referent, plural identity and applicability stay explicit unresolved issues wherever required by the caller's interpretation.

The returned scope validation, lossless family-extension bridge and flat-compatibility assessment retain their existing owners. Both legacy flat routes remain unavailable for this profile's open context and incomplete semantics. There is no formal norm AST, lowered IR, native code, accepted lookup or governing definition-use edge. All authority flags remain false and training/evaluation masks remain zero. The bridge does not discover every possible missing semantic issue, authenticate reviews or admit a target.

The [retained actual examples and replay](../../../../../docs/autoencoders/legal_ir_norm_integration_20261015.md) use the exact prior 2024 §§7213/7214 intakes and complete source-only use proposals. Their scope declarations are caller-authored, and the organizer/team has seen them. They are not blind targets, learned decoder outputs, accepted meanings or independent holdout examples. Reusing the §101 definition candidates and related nominations does not resolve the two norm interpretations.


## Original parent literal-occurrence profile

The additional `prepare_parent_norm_scope_v1` API retains the same kind of
unreviewed lexical declaration over one exact original parent-text occurrence.
It uses the existing `legal_semantic_graph.bind_parent_source_occurrence` and
complete `corpus_parent_occurrence_adapter` replay. The original sampled-HTML
APIs and profile above remain separate and keep their existing behavior.

The explicit output schema is `legal-parent-norm-scope-proposal/v1`; its profile
is `whole-selected-parent-literal-occurrence-unreviewed-lexical-scope/v1`.
“Whole selected occurrence” means the full literal text of the selected sealed
occurrence. That occurrence may be a fragment or an unclassified region. It
does not establish a whole paragraph, complete provision, whole law or
governing source body.

```python
from ipfs_datasets_py.logic.autoformal.legal_source_norm_scope_v1 import (
    prepare_parent_norm_scope_v1,
    validate_parent_norm_scope_v1,
    parent_norm_scope_report_sha256,
)

proposal = prepare_parent_norm_scope_v1(
    original_parent_bundle,
    scope_request_raw,
    scope_declaration_raw,
    expected_manifest_cid=independent_parent_manifest_cid,
    source_occurrence_cid=exact_original_occurrence_cid,
    companion_record_cid=exact_original_role_or_cache_match_cid,
    report_bytes=original_report_bytes,
    expected_report_pins=independent_original_report_pins,
    replay_inputs=complete_original_parent_replay_inputs,
    expected_scope_request_sha256=independent_request_raw_sha256,
    expected_scope_declaration_sha256=independent_declaration_raw_sha256,
)
```

The closed input set consists of `parent_bundle`, `scope_request_raw`,
`scope_declaration_raw`, `expected_manifest_cid`, `source_occurrence_cid`,
`companion_record_cid`, `report_bytes`, `expected_report_pins`, `replay_inputs`,
`expected_scope_request_sha256` and `expected_scope_declaration_sha256`, plus
optional `limits`. The three independently retained CID selections must agree
with the complete replayed population. Equal spelling, physical row ordinals
or an occurrence's position in an array cannot replace those identities.

`report_bytes` contains exactly `parent_text_views`, `cache_parent_occurrences`
and `parent_sentence_candidates`, each as its original complete immutable
bytes. Each entry in `expected_report_pins` has exactly `raw_sha256` and
`canonical_sha256`. `replay_inputs` remains the parent adapter's complete closed
original replay: `provenance_reports`, `lineage_report`,
`expected_lineage_report_sha256`, `lineage_inputs`, `parent_text_views_inputs`,
`expected_record_sha256s` and `expected_provenance_report_sha256s`. Physical
file and row witnesses are required; a supplied binding or a producer-pin map
cannot substitute for original replay.

The declaration's `source_text` must equal the selected occurrence's
`span_text` exactly. Identity normalization remains `identity/v1`: the API does
not trim text, normalize combining characters, reconstruct HTML or reinterpret
cache offsets. Existing canonical scope validation, complete literal coverage,
partial or unassessed semantics, unresolved issues and the unchanged scope
bridge remain mandatory.

Every `anchor_mappings` row has `declaration_path`, `local_anchor` and
`parent_selector`. The last has schema `legal-parent-norm-scope-anchor/v1` and
retains `source_version_cid` and `source_occurrence_cid`. Local half-open Unicode
code-point offsets become absolute source-field coordinates as follows:

```text
char_start = selected.start_char + local.start
char_end = selected.start_char + local.end
utf8_byte_start = selected.start_utf8 + len(selected.span_text[:local.start].encode("utf-8"))
utf8_byte_end = selected.start_utf8 + len(selected.span_text[:local.end].encode("utf-8"))
```

The parent selector retains exact anchor text, its UTF8 SHA256,
`extracted-unicode-codepoints-and-utf8-half-open/v1` coordinates and the identity
normalization profile. A parent anchor is not an HTML V2 document selector.
The report preserves the complete genuine `parent_source_binding`, including
physical parent identity, companion, source version, occurrence and context.
Repeated equal text in different physical rows or literal positions remains
distinct.

Preflight detaches bounded ordinary JSON, checks independent raw hashes and
refuses extra fields before operation dependencies load. Limits are:

| Input or output | Maximum |
| --- | ---: |
| Each lexical request/declaration raw JSON | 64 KiB |
| Each of the three original reports | 8 MiB |
| Complete parent bundle | 16 MiB |
| Physical replay JSON | 16 MiB |
| Aggregate parent scope inputs | 64 MiB |
| Complete parent scope output | 1 MiB |

The optional parent limits retain the existing lower-only defaults:
`max_report_bytes=8388608`, `max_replay_bytes=16777216`,
`max_total_input_bytes=33554432`, `max_records=8192` and
`max_collection_bytes=16777216`. Existing parent-owner limits still apply
inside the larger aggregate scope-input bound. Unknown, raised, boolean and
nonpositive limits are refused; oversized content is refused without
truncation.

Preparation performs genuine original parent replay at opening and closing.
It checks original and detached inputs, returned bindings, trusted source pins
and the complete serialized result on both success and failure paths. A
primary error remains primary if closing custody checks also fail. Parent pin
state is independent of the HTML route's pin state.

`parent_norm_scope_report_sha256` returns the full canonical report hash,
including the report's internal payload seal. Retain that full hash in an
independent manifest. `validate_parent_norm_scope_v1` takes the report followed
by the same preparation inputs and `expected_report_sha256`; it regenerates
from complete originals and returns a transport-only validation summary. A
resealed edited output still has to equal exact regeneration. Sampled-HTML and
parent reports are not interchangeable.

The edition remains `not_declared_in_source_artifact`. Original context remains
`required_unavailable`, with definition, authority, antecedent,
shared qualifier, temporal origin and referenced provision requirements open.
These six requirements are not an exhaustive legal dependency inventory. All
authority flags remain false and training/evaluation masks remain integer zero.
There is no formal norm AST, lowered IR, selected interpretation, graph
admission, learned target or meaning review. No model, training, solver or Lean
process is executed.

The [saved qualification audit](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-programme-review-20261022-05/parent-norm-scope-20261024-root-932c992e/execution-v03/independent-saved-result-audit-v01.json)
accepts the combined two-module cohort: 185 cases and 555 passing phases,
including 149 existing compatibility cases and 36 parent-profile cases. Both
guides refer to this same cohort. The exact qualification profile is
`parent-norm-scope-public-port-pure-controls/v2`, with namespace profile
`parent-norm-scope-scoped-unit-namespaces/v2`.

This is qualification of source custody, geometry, declared syntax and refusal
behavior. The two processor package initializers are pinned and explicitly
bypassed alongside the existing namespace bypasses; the required genuine
`uscode_release_schema.py` leaf was observed executing. Full package startup,
bypassed initializer execution and third-party cached bytecode are outside the
qualification. Original native, source READ and storage cleanup completed.
The two earlier failed attempts remain failed, with separate storage closeouts;
they are not added to the successful cohort or counted as laws.

No legal-fidelity or learned accuracy gain is claimed. Meaning review, governing
edition/context decisions, complete law semantics, training targets and gold
admission remain unavailable; all authority flags and masks described above
retain their false/zero values.
