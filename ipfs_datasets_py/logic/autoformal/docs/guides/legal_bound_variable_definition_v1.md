# Conditional unary definitions at exact bound-variable occurrences

`logic.autoformal.legal_bound_variable_definition_v1` prepares conditional Lean
text for one exact variable occurrence in an unchanged relational norm. It
replays a complete [`legal_norm_definition_evidence_v1`](legal_norm_definition_evidence_v1.md)
report, retains all definition alternatives, and uses the existing native
renderer. It does not apply a definition to the norm, infer category membership,
or consume an applicability declaration as permission to rewrite the norm.

For a supplied interpretation `i`, fixed time `t`, and entity valuation `r`,
the hypothesis `hDefinition : ∀ x, D x ↔ Body x` supports the instance
`D r ↔ Body r`. Deriving `Body r` additionally needs `hMembership : D r`.
The adapter generates precisely these conditional consequences. Both premises
remain explicit unverified hypotheses, including when the selected occurrence
is under an existential quantifier or a modality.

## Public preparation and replay

```python
prepared = prepare_bound_variable_definition_v1(
    original_evidence_report,
    exact_request_bytes,
    expected_companion_sha256=independent_full_evidence_hash,
    expected_request_sha256=independent_request_byte_hash,
    companion_inputs=original_evidence_inputs,
)

validate_bound_variable_definition_v1(
    prepared,
    original_evidence_report,
    exact_request_bytes,
    expected_report_sha256=independent_full_preparation_hash,
    expected_companion_sha256=independent_full_evidence_hash,
    expected_request_sha256=independent_request_byte_hash,
    companion_inputs=original_evidence_inputs,
)
```

`bound_variable_definition_sha256(record)` hashes the full canonical output.
The expected companion hash identifies the full original evidence report, not
an embedded assessment digest. The request hash identifies its original UTF-8
bytes. Expected values must come from independently retained provenance.

`companion_inputs` has exactly the original evidence owner's six fields:
`norm_preparation`, `request_raw`, `expected_norm_preparation_sha256`,
`expected_request_sha256`, `norm_inputs`, and `definitions`. The public evidence
validator replays the complete source, contextual nominations, norm mapping,
definition endpoints and any supplied original review assessments. Saved
statuses, rehashed reports or a selected graph node cannot replace that replay.

## Closed request

The request uses schema `legal-bound-variable-definition-request/v1` and profile
`conditional-unary-definition-at-bound-variable/v1`. Its exact fields are:

| Field | Required binding |
| --- | --- |
| `schema`, `profile` | The exact identifiers above. |
| `companion_sha256` | Complete original evidence hash. |
| `link_sha256`, `alternative_id` | One full original nomination link and its existing definition alternative. Choosing this link prepares an illustrative conditional, without granting governing priority. |
| `target` | The complete original variable target: typed/native paths, node identity and kind. Predicate and binder targets are refused. |
| `binding` | Complete original governing-binder context, including quantifier and typed path. |
| `binder_target` | Exact binder entry from the original relational structural mapping, including its native path and sort fields. |
| `argument` | Exact parent relation, typed predicate path, argument index and declared role. |
| `source_paths` | Complete ordered inverse source paths from the selected link. |
| `definition_term_ref`, `definition_ast_ref` | Original CID/full-hash references from that link, checked against the exact alternative. |
| `carrier_map` | The fixed explicit carrier map shown below. |
| `evaluation_context` | The fixed shared interpretation/time/valuation declaration shown below. |
| `definition_assumption` | The explicit unverified `hDefinition` declaration shown below. |
| `mode`, `membership_assumption` | One of the two closed modes described below. |

```python
carrier_map = {
    "typed_sort": "Object", "native_sort": None,
    "definition_carrier": "Entity", "lean_carrier": "Entity",
    "mapping": "same_carrier",
}
evaluation_context = {
    "interpretation": "shared_parameter",
    "time": "fixed_shared_parameter",
    "variable": "explicit_binder_valuation",
}
definition_assumption = {
    "kind": "explicit_unverified_parameter", "parameter": "hDefinition",
    "definition_ast_ref": original_link["definition_ast_ref"],
}
```

This carrier declaration deliberately interprets the norm's `Object` sort and
the unary definition's `Entity` carrier as one arbitrary Lean type. It supplies
no coercion or equivalence between distinct types. The time parameter is a
formal `Nat`, not an authenticated legal-as-of clock. It is shared by the head,
body and definition hypothesis; a different interpretation or time is refused.

For `mode="instance_only"`, `membership_assumption` must be null. For
`mode="body_with_membership"`, it must equal:

```python
membership_assumption = {
    "kind": "explicit_unverified_parameter", "parameter": "hMembership",
    "link_sha256": complete_original_link_hash,
    "definition_symbol": original_alternative["term_record"]["symbol"],
    "carrier": "Entity",
}
```

This declares a theorem premise. It is not a proof of membership, a legal fact,
an extracted witness, or an authenticated reviewer statement. Omitting or
retargeting it refuses body-mode preparation. No caller-supplied Lean code is
accepted. Canonical byte comparisons distinguish boolean and integer fields.

## Supported fragment and generated text

The selected donor must retain the existing V2 unary Boolean definition profile:
`∀ x, D x ↔ Body x`, with the exact head on the left. The body supports the
original ordered unary atoms, negation, conjunction and disjunction over that
same bound variable. Functions, constants, additional free variables, extra
quantifiers, modalities, temporal operators, changed directions, other arities
and other carriers are refused by this adapter before rendering. The broader
native renderer's capabilities do not expand this input fragment.

The adapter reuses `legal_family_routes.prepare_native_fragment` for the whole
original donor receipt and `native_family_lean_emitters.FormulaRenderer` for its
exact head/body subtrees. Source symbols such as the V2 `D` plus 64 hexadecimal
digits remain unchanged. They are quoted atom parameters, not shortened Lean
identifiers or additions to the relational grammar's 64-character signature.

The original donor binder is mapped to a fresh fixed Lean parameter named
`entity`. Source binder spelling does not become a Lean identifier. Exact
typed/native occurrence and binder paths remain in the report. A renamed source
binder requires newly replayed evidence; the adapter never treats stale pins as
valid through assumed alpha equivalence.

Every preparation carries the complete generated `lean_source`, reused
`definition_native_fragment`, exact definition/head/body native ASTs, rendering
environment and expressions, and ordered theorem names/statements. The first
theorem is `LegalBoundVariableDefinition.definition_instance`:

```lean
(hDefinition : formula_0 i t) : headAt i entity t ↔ bodyAt i entity t := by
  exact hDefinition entity
```

Only membership mode adds `LegalBoundVariableDefinition.body_instance`:

```lean
(hDefinition : formula_0 i t) (hMembership : headAt i entity t) : bodyAt i entity t := by
  exact (hDefinition entity).mp hMembership
```

The source includes the existing `PRELUDE` and `#print axioms` commands. Those
commands are generated text, not executed observations. This operation creates
no Lake project, registered build profile, compiler process or proof receipt.

## Preserved evidence and limits

`selected_link` preserves the full original selected nomination. The
`occurrence_binding` retains the original typed node, native variable, complete
parent relation, exact binder and argument role, ancestry, source rows and
original source-target/definition-subject references. These references retain
their original schemas; the adapter invents no physical source geometry.

`definition_alternatives` retains every original endpoint in order, including
its original review evidence. `nomination_inventory` retains every original
request link and full link hash in order. Rival alternatives are neither
discarded nor declared globally mutually exclusive. Full source and report
inputs remain external and are required for independent reconstruction.

`original_norm` records the original preparation, correspondence, typed/native
AST hashes and scope. Its unchanged claim is guarded by complete original and
detached input commitments. The original norm AST is not rewritten: no guarded
binder, restricted quantifier, conjunction, relation replacement or inference
through a modal context is performed. An existential occurrence does not provide
a witness; a universal occurrence does not provide membership.

The raw/canonical request limit is 128 KiB. The adapter retains the existing
evidence snapshot budget of 128 MiB, 4,000,000 values, depth 96 and a 32-MiB
individual byte body limit. The complete output is bounded by the existing
8-MiB report limit. Aggregate report-plus-input snapshots may refuse a population
that fits its separate upstream operations. Overflow refuses without dropping
alternatives or source evidence. Actual operation producers and complete inputs
are pinned before replay and checked through final serialization; no producer
path supplied by an incoming report is opened as authority.

Every authority flag remains false. `norm_interpretation_ready` remains false;
selected interpretation and governing use remain null; training/evaluation
masks remain integer zero. The original review clocks stay historical. This
preparation supplies no new reviewer, signature, applicability decision,
accepted `USES_DEFINITION` edge, law interpretation or learning target.

Authored fixture checks and finite witnesses can test structure, conditional
truth and rejection behavior. They do not establish legal fidelity, a native
kernel result, or successful application to actual statutes.

## Published bound-norm profile reused in primary, 2026-10-24

The existing Lake/native owners now expose the published bound-norm sibling profile; use the [Lake preparation](legal_corpus_definition_use_lake_v2.md#published-bound-norm-profile-reused-in-primary-2026-10-24) and [native adapter](legal_corpus_definition_use_native_v2.md#published-bound-norm-profile-reused-in-primary-2026-10-24) APIs rather than another conditional renderer.

This opt-in engineering profile packages the complete unchanged relational norm
beside the original bound-variable definition conditional. It retains all
definition alternatives and exact selected occurrence/binder/argument references.
The nine-file, six-module project shares one Entity carrier, Interpretation and
fixed Nat time. Instance mode assumes hDefinition; body mode additionally assumes
hMembership. The preservation theorem is a definitional alias identity, not a
proof of norm truth, membership or statutory meaning. No definition is substituted
into the norm. Original relational source_binding remains null and source_bound
false; selected interpretation/governing use remain null, masks zero, authority false.

This bound-norm v1 evidence pipeline requires complete original raw-HTML,
acquisition/sampler/context, request and official-V2 definition endpoint replay.
Separate existing ports already provide `exact-decoded-parent-field-candidate-records/v1`
custody and literal-parent unary Boolean definition candidates, adapters, review
and conditional native projects. Reuse those ports; they are not composed into
bound-norm v1's strict official-V2/raw-HTML norm correspondence. The selected
full-norm scope/correspondence composition with those parent ports needs its own
explicit compatibility qualification. Governing edition, reviewed source-to-typed
meaning, physical span/entity correspondence, per-use applicability and two
genuinely distinct statutory uses remain pending. Two typed uses of one fictional
physical anchor do not meet the two-use requirement.

Preparer, renderer and input commitments include actual producer paths/generations.
Prepare fresh original-input outputs after moving to the canonical path or
changing a producer; never relabel the historical worktree/frozen preparations
or native receipts as current canonical outputs.

The [fresh primary qualification](../../../../../docs/autoformalization/evidence/legal-ir-bound-norm-corpus-primary-integration-20261024.json) passed 42 authored cases / 126 phases from 17 unchanged selectors against current peer dependencies. Compiler responses in these controls are synthetic. The published original source closure separately passed two actual Lean4.34.1 cases / six phases; that historical observation is not current-dependency native qualification. Only the selected pure-v02 run supplies this fresh 42-case result. The earlier pure-v01 guard failure observed 28 passed and 14 failed calls, retains zero cohort qualification credit and is never combined with v02. Its original retained 128 MiB terminal and separate supported storage closeout are bound in the integration evidence; preserved-file counts/bytes come from genuine postwrite receipts. No model, training, new Lean build, default adoption or full-package qualification is claimed. The two explicitly bypassed integration/reasoning initializers remain unqualified; genuine other initializers retain only this selected-control scope. These 42 controls do not qualify either entire owning test module. The old native-v01 fixture failure retains its original 192 MiB retained-storage receipt, with no administrative release proved here. The numbered=False native-fixture repair and successful native-v02 remain separately attributed.


## Explicit parent-literal conditional consumer

The same existing owner adds `prepare_parent_bound_variable_definition_v1` and
`validate_parent_bound_variable_definition_v1`; the unchanged
`bound_variable_definition_sha256` hashes the full canonical output. The separate
request schema is `legal-parent-bound-variable-definition-request/v1`, report
schema `legal-parent-bound-variable-definition-report/v1`, and profile
`conditional-parent-unary-definition-at-bound-variable/v1`. The original HTML
entry points keep their schemas, signatures, 4,000,000-node resource profile and
existing qualification scope.

Supply the complete parent nomination `companion`, original `request_raw`,
independent `expected_companion_sha256` and `expected_request_sha256`, and the
nomination owner's six original `companion_inputs`: `norm_preparation`,
`request_raw`, `expected_norm_preparation_sha256`, `expected_request_sha256`,
`norm_inputs` and `definitions`. Validation additionally requires the complete
conditional record and its independently retained `expected_report_sha256`.
The same closed 18 request fields, fixed Object-to-Entity carrier declaration,
shared interpretation, fixed formal Nat time and explicit binder valuation
apply under the new parent domain. An exact variable occurrence, binder,
ordered argument role, source paths and whole donor term/AST references are
required; predicate targets or repaired hashes cannot retarget them.

`instance_only` generates `headAt i entity t ↔ bodyAt i entity t` under the
explicit unverified `hDefinition : formula_0 i t`, and requires null membership.
`body_with_membership` additionally declares the exact occurrence-bound
`hMembership : headAt i entity t` before generating `bodyAt i entity t`. Neither
mode proves membership, extracts a witness from an existential norm or changes
the supplied norm's quantifiers, relations, conditions or modal placement. The
parent donor must retain `declared-literal-parent-unary-predicate-definition/v1`;
it is not relabeled as the V2 HTML profile.

Each operation genuinely validates the whole parent nomination at opening and
closing, with all original norm/definition physical replay. The full checked
`companion` is retained once; ordered `definition_alternative_refs` bind every
retained alternative without duplicating its complete candidate. The exact
selected link, full nomination inventory, binder/native variable and predicate,
source rows and ancestry remain. `original_norm` retains actual original
preparation/correspondence/typed/native hashes and source identity, with
`source_binding=null` and `source_bound=false`; no synthetic scope ID is added.
Both endpoint context populations remain separate and unavailable.

The four shared helpers use explicit parent options with legacy False/None
defaults. Their legacy default bodies were statically compared; the other 12
original function bodies, including the original public APIs and
`_render_conditionals`, are unchanged. The parent route uses that renderer,
retaining actual parsed donor/native-route/rendering returns through closing
checks. Caller/detached/parsed inputs, physical files, producers, callback
policies and exact final encoded bytes remain guarded after the second genuine
serialization check. No parallel renderer, product writer or persistence API
is introduced.

The parent input budget is 128 MiB and 1,500,000 aggregate nodes, with a 128 KiB
request and 8 MiB output. Existing individual endpoint/depth/body limits apply;
complete overflow refuses without truncation. The original HTML route retains
its separate 4,000,000-node profile. These finite input budgets do not assert
kernel memory containment.

The [focused qualification](../../../../../docs/autoformalization/evidence/legal-ir-parent-bound-variable-definition-20261025.json) passed **29 cases / 87 phases
from 16 selectors**: 27 new parent controls and two selected genuine legacy
positives. The other 30 owning-module cases and prior29 nomination cases remain
outside this selection. Both positive modes saved exact returned reports,
generated source and request bytes in owned test directories; the independent
audit read those complete examples directly and checked their canonical hashes
and explicit premises. These are authored prepared-source examples, not a new
product writer or accepted corpus. `kernel_checked=false` and
`lean_compilation_verified=false` remain exact; no Lean process ran. Original
compute/storage/source-READ custody closed. Declared namespace, checked-source,
unexecuted-initializer and sampled process scopes do not qualify full package
startup, statutory meaning or mathematical/model convergence.

Authority stays false, selected interpretation and governing use stay null, and
all four semantic/consumer/training/evaluation masks stay integer zero. Source
edition/meaning, governing definition applicability, reviewed composition, Lake
packaging, native Lean execution, graph/corpus admission and model convergence
retain separate gates. The [upstream nomination companion](legal_norm_definition_evidence_v1.md#explicit-parent-literal-nomination-companion)
keeps its earlier 29/87 custody-only scope and in-memory product-report history.


## Retained standalone Lean observation

The separate [native observation](../../../../../docs/autoformalization/evidence/legal-ir-parent-bound-variable-definition-native-20261025.json) passed **three native checks using five enrolled
toolchain/compiler commands**: the Lake and Lean version probes followed by
three standalone compiler invocations under Lean 4.34.1. These are native checks,
not an additional pytest case/phase cohort or a compatible production build
profile. The existing `BoundedToolRunner` compiled the two exact retained UTF8
source files under their explicit parameters:

| Retained mode | Conditional declarations observed without axioms | Compiled artifact |
| --- | --- | --- |
| `instance_only` | `LegalBoundVariableDefinition.definition_instance` | 115,776 bytes, SHA256 `1efcfa115635f298ce447cc1a0acb3c213319ffad83716de3db2492b41a5ab04` |
| `body_with_membership` | The same `definition_instance`, plus `LegalBoundVariableDefinition.body_instance` | 118,904 bytes, SHA256 `d9efcd61a1bfab1b7b1571853d93a4607134f9f26606608ec1ca7ea87d8a92e6` |

There are three exact empty-axiom observations across those two successful
compilations, covering two distinct theorem names. `hDefinition` remains an
explicit unverified parameter; only membership mode additionally requires
`hMembership` for the same head, entity, interpretation and time. Empty axiom
output does not verify those supplied legal assumptions.

The negative check appends an invalid body proof to the complete unchanged
membership-mode source. Lean rejected `exact hEquiv` because its type was
`headAt i entity t ↔ bodyAt i entity t`, while the goal was `bodyAt i entity t`.
Its return code was 1, the complete diagnostic capture was 326 bytes, and no
compiled artifact was observed. This qualifies rejection of that specific
invalid proof term; it is not a formal universal non-entailment result. Earlier
axiom-print lines in the failed file do not qualify it as a compiled module.

The original prepared reports, their exact hashes and the separate 29/87/16
pure qualification remain unchanged. In those historical preparation reports,
`kernel_checked=false` and `lean_compilation_verified=false` remain exact. The
new compiler observations, raw artifacts, logs and independent result review
are bound in the separate native evidence; no preparation report is relabeled.

The worker compiled/executed one complete checked process source; seventeen
outer custody ancestry sources retain their separate scope. No package
initializer execution or full package startup is qualified. All five observed
tool lifecycles and the original native/storage/source-READ custody closed.
The original closeout records 26 artifact seals and 27 retained files totaling 421,808 bytes. The selected
storage reservation was released and original artifacts are durable. The
first native-v01 intake filename collision refused before worker/resource
dispatch and retains zero jobs or qualification credit.

Fresh parent/source replay, production-native profile adoption, Lake packaging,
source edition and legal meaning, governing definition applicability, verified
membership, norm rewriting, graph/corpus admission and model convergence remain
separate gates. Original authority stays false, selected interpretation and
governing use stay null, and all four semantic/consumer/training/evaluation
masks stay integer zero.
