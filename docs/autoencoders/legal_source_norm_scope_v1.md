# Sampled source to normative scope transport

`legal_source_norm_scope_v1` binds a caller-authored, incomplete scope declaration to one exact whole sampled statutory paragraph. It reuses the existing official V2 view, sampler, source records, normative scope validator and frozen scope bridge. It introduces no new logic AST.

This is the first source/coverage deliverable from the existing [statutory norm-gap specification](../../../../legal-corpus-norm-scope-20261015-01/retained-norm-gap-specification.md), retained byte-for-byte from the separate local workstream. That specification is local evidence, not part of this repository's distribution. The profile does not implement its later relational, cardinality, modal-scope or lowering stages.

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

The [retained actual examples](../../../../legal-corpus-norm-scope-20261015-01/README.md) use the exact prior 2024 §§7213/7214 intakes and complete source-only use proposals. Their scope declarations are caller-authored, and the organizer/team has seen them. They are not blind targets, learned decoder outputs, accepted meanings or independent holdout examples. Reusing the §101 definition candidates and related nominations does not resolve the two norm interpretations.
