# Remaining statutory norm profile gaps — 2026-10-15

This source inspection identifies the next representation work for the retained
10 USC §§7213–7214 candidates. It adds no norm AST, model output, meaning review,
training target, graph admission or Lean-build result. The retained source
examples remain unreviewed. These are implementation observations and proposed
acceptance criteria, not legal interpretations or evidence of statutory
correctness.

The [contextual definition-binding qualification](legal_ir_context_definition_binding_20261015.md)
established an evidence handoff. Its actual control connected two scope-only
nominations to a separate enlisted-member definition request. It did not
establish an officer-definition use or interpret either norm. This document
refines P1–P3 of the [existing corpus improvement plan](legal_ir_uscode_corpus_improvement_plan_20261015.md)
without changing the existing LIR backlog or scheduling another campaign.

## Existing owners and their boundaries

Paths below are relative to `ipfs_datasets_py/logic/`. These observations concern
the inspected local source, not a substituted historical experiment runtime.

| Owner and API | Reusable behavior | Boundary relevant to the retained norms |
| --- | --- | --- |
| `autoformal/legal_source_definition_norm_bridge.py`: `prepare_definition_norm`, `validate_definition_norm` | Exact source spans, preceding section-local definition, shared definition symbols, universal category guard, O/P/F, native AST regeneration and Lean text generation | Accepts only a complete leaf paragraph of the form `Each <defined category> <modal cue> <one-word unary action>.` Rejects objects, relations, conditions, exceptions, nested lists and cross-document definitions. |
| `autoformal/legal_source_definition_bridge_v2.py`: `prepare_definition_v2`, `validate_definition_v2` | Complete V2 source replay, exact scope and contributor references, declared applicability, bounded Boolean definition structure | Explicit unary definition interpretation; no assignment, transfer, approval, cardinality or purpose interpretation. |
| `autoformal/legal_source_sampling_review.py` and `legal_source_sampling_review_context.py` | Full source populations, exact review subjects, context attachments, independent input pins and unresolved/disputed declarations | Review declaration transport does not establish reviewer authority, semantic correctness, applicable definition use or training eligibility. |
| `autoformal/legal_canonical_qualified.py`: `interpretation_skeleton`, `prepare_canonical_qualified`, `reconstruct_canonical` | Seven canonical facets, explicit qualifier expressions and temporal interpretation, reversible structural mapping | Actor/object slots remain ground strings. The skeleton leaves semantic choices unset. It does not supply quantified category binding, relational event structure, cardinality or anaphora resolution. |
| `legal_ir/canonical_contracts.py`: `CanonicalRule`, `CanonicalRoundTripIR` | Stable O/P/F, actor, action, object, conditions, exceptions and temporal payload | The measured v1 bottleneck has string-valued facets. Its contract requires new semantic facets to use a new schema or remain unsupported. |
| `legal_ir/extended_contracts.py`: `DefinitionV2`, `PolicyV2`, `NormV2`, `ExtendedLegalIR` | Separate definition, policy and norm surface records; scope and qualifier retention | The module explicitly retains opaque natural-language atoms. Surface structure does not interpret those atoms as formal logic. |
| `legal_ir/logic_slice_v2.py`: `LegalLogicSliceConnector.connect_claim` | Family/profile, deontic, temporal, defeasibility, jurisdiction, priority and authority metadata | `_build_expression` uses a propositional signature and one `mk_predicate` for the claim. Slice admission does not establish a compositional source-to-norm translation. |
| `syntax_core/ast.py` | Existing typed binders, equality, Boolean connectives, quantifiers, signatures and typed-expression validation | These constructors need an explicit interpretation and source correspondence. Their existence does not establish compatible source extraction, norm semantics or a native lowering route. |
| `autoformal/legal_family_routes.py`: `prepare_native_fragment`, `route_canonical`, `capability_matrix` | Strict native parsing, exact AST print/reparse checks and deterministic Lean text for explicitly supported profiles | Independent native syntax is not a translation from the original statute. Canonical O/P/F routes only to the qualified deontic profile; broader equivalence remains unverified. |

The existing native-fragment route supports a one-carrier quantified
predicate/Boolean subset, with declared deontic or temporal operators where the
selected family permits them. Its DCEC route is restricted to ground Object
predicates and O/P/F over those predicates. It explicitly excludes multisorted
native carriers, free variables, bounded native temporal annotations and several
broader legal translations. A richer typed syntax must not be marked supported
merely because a different owner can store its nodes.

`autoformal/legal_source_definition_norm_lake.py` already supplies separate
`prepare`, `validate` and `build` operations for the existing narrow profile.
Preparing Lean source and executing `lake build legal` are separate actions.
Neither supplies independent legal meaning review. No build operation was used
for this inspection.

## Retained actual-source observations

The inspected inputs are the existing review bundles under
`lift_coding/artifacts/legal-ir-cache-source-qualification-20261015-01/source/`.
Each selected subject is unit ordinal 9. Its source occurrence is sampling record
28, its unresolved context is record 29, and the structured sample unit is record
30. A sampling record index is not a unit ordinal.

| Retained bundle | Unicode half-open occurrence | UTF-8 half-open occurrence | Exact source-span SHA256 |
| --- | --- | --- | --- |
| `official-2024-7213/review-bundle.json` | `[431,624)` | `[432,625)` | `1cffae41c1d05bc7813b2fd578e5b06f5870422221c99bc39a89803ca4644e52` |
| `official-2024-7214/review-bundle.json` | `[407,570)` | `[408,571)` | `3c8264afde92003a962dc254b3bc0192858cdfa2b5f6f1ed82cd1e1a82c1313e` |

For both units, `meaning_target` is null, `formal_outputs` and
`semantic_assertions` are empty, and training/evaluation masks are zero. Their
context records retain `definition`, `authority`, `antecedent`,
`shared_qualifier`, `temporal_origin` and `referenced_provision` as missing
requirements, with `availability=required_unavailable` and
`dependency_verification=declaration_only`. Existing attachments do not silently
replace these original observations.

The first source contains passive assignment/transfer wording, direction and
duty restrictions, and an approval phrase. The second contains a capped plural
recipient phrase, assignment restriction, assistance purpose and a pronoun.
These are source features requiring interpretation; the following are questions
for a declared profile and subsequent review, not approved answers:

- **Agency and roles:** Who acts, who receives the action, and which office or
  organization is referred to? Passive recipients must not automatically become
  the authority performing the action.
- **Coordination and relation scope:** How do assignment versus transfer,
  direction, duties and purpose attach? Copying the whole phrase into one unary
  predicate would retain text while hiding this structure.
- **Necessary versus sufficient constraints:** The approval wording must retain
  its direction and modal scope. A necessary approval condition must not silently
  become a sufficient permission or an obligation to act after approval.
- **Cardinality:** What is counted, over which action or state, and with what
  distinctness and time scope? A label such as `at_most_three` is not an encoded
  cardinality constraint.
- **Anaphora and applicability:** What does the pronoun refer to, and which
  definitions, source version, norms and declared scope apply? Matching words or
  sharing a title-level scope does not answer these questions.

## Smallest proposed profile and acceptance

Keep the present unary and canonical v1 contracts unchanged. Add one versioned
source-bound norm interpretation profile alongside them, using existing source,
review, syntax and family owners. Its first deliverable should make missing
semantics machine-readable; it must not manufacture actual statutory answers to
achieve apparent coverage.

1. Bind the complete selected source unit, version, normalized view, raw source,
   independent sampler/context commitments and all declared dependencies.
   Record exact role spans and complete coverage, retaining uncovered or
   unsupported material rather than shortening the source to fit the profile.
2. Require explicit declarations for variable identity, sort, quantifier scope,
   actor/recipient arguments, modal scope, relation or action alternatives,
   necessary versus sufficient conditions, and any purpose or cardinality
   construct. Unresolved declarations prevent the affected formal output.
3. Distinguish candidate source correspondence, source coverage, typed AST
   validity, family-lowering support, meaning review and signed admission.
   Retain all alternatives and missing requirements. Context or related-review
   citations cannot substitute for direct review of the interpretation.
4. Qualify the smallest representable relational fragment with authored fixtures
   first. A cardinality or event construct without an implemented, checked
   lowering remains unsupported. Reuse `syntax_core.ast` and existing family
   registries rather than adding a second general AST. Do not encode richer
   structure by packing it into canonical v1 strings.
5. When independent source interpretations are available, connect them through
   the existing review and source-binding owners. Admit an actual source example
   only under the existing authority rules. Training targets and semantic graph
   edges require their separate eligibility decisions.

The engineering acceptance set should contain explicit positive fixtures plus
meaning-changing negative controls:

| Concern | Required acceptance observation |
| --- | --- |
| Necessary approval | A finite declared interpretation distinguishes approval as necessary from approval as sufficient, without manufacturing permission to act. |
| Modal scope | Permission, obligation and prohibition remain distinct; activation outside a modality is distinguished from a guard inside it. |
| Alternatives | Assignment/transfer disjunction is distinguishable from conjunction, dropped alternatives and independent permissions where those differ under the chosen semantics. |
| Roles and direction | Actor/recipient swaps and reversed direction yield different typed structures and detectable counterexamples under the authored model. |
| Numerical cap | A declared distinct-object model distinguishes three from four; count scope and time/event scope are explicit. Unsupported count semantics refuses lowering. |
| Anaphora | Missing or competing referents remain unresolved; no invented constant satisfies the compiler merely to obtain a pass. |
| Source coverage | Omitted suffixes, qualifiers, objects and relevant parent context are rejected or retained as explicit unsupported content. |
| Source identity | Same wording from another edition, section or occurrence cannot substitute for the independently bound source. |
| Review boundary | Related citations and mechanically valid syntax do not close direct interpretation review or set training/proof authority. |
| Regeneration | Resealed changes to variable binding, modal operator, arguments, count, source geometry or emitted code fail authoritative replay. |

The existing `tests/unit/logic/autoformal/test_legal_source_definition_norm_bridge.py`
already exercises modal/category preservation, suffix omission, repaired-hash
mutations, edition-scoped symbols, exhaustive two-entity interpretations and a
two-world category-scope countermodel. Reuse these patterns without describing
finite countermodel tests as unbounded proofs. Existing qualified-lowering tests
provide additional qualifier and temporal scope controls. Future Lean execution
must retain the actual toolchain, generated source, declaration coverage and
build receipts; syntax success alone cannot establish source fidelity.

This inspection used local source and retained JSON only. It ran no imports of
operation owners, tests, theorem provers, models, training, downloads or external
publication. The proposed profile and acceptance cases above remain future work.
