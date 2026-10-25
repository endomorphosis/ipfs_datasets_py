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


## Downstream complete-norm project profile

The existing [Lake owner](legal_corpus_definition_use_lake_v2.md#complete-relational-norm-with-a-conditional-bound-definition-version-1)
now implements `prepare_bound_norm_definition_corpus_v1` with matching validate,
load/write and full-preparation hash APIs. Supply this complete report, its
independent full hash, and the exact original five bound-owner replay inputs.
This is a downstream profile; the conditional report and its APIs stay unchanged.

Its nine-file/six-module project packages the byte-exact complete quantified/
modal norm alongside the original definition and conditional instance using one
shared `Interpretation`. There are two theorem obligations in instance mode and
three in membership mode. `hDefinition` and any `hMembership` remain explicit;
the added norm-preservation theorem proves only a definitional alias identity.
No norm-driven membership, governing predicate bridge or source-meaning theorem
is supplied. The [native owner](legal_corpus_definition_use_native_v2.md#bound-norm-definition-native-profile-version-1)
has a separate replay/build/receipt profile; preparation itself executes no Lean.

All alternatives, nominations, exact binder/role bindings and original source
references survive. The norm's source binding remains null. Authored typed-use
fixtures sharing one physical anchor do not establish distinct statutory uses.
The selected retained 2024 Title 10 pilot still needs independent legal-as-of,
meaning, governing-definition and every-use applicability decisions before
source-bound statutory composition or learning/corpus admission.


## Explicit parent-literal conditional instances

The same existing owner exposes `prepare_parent_bound_variable_definition_v1`
and `validate_parent_bound_variable_definition_v1`. Use the unchanged
`bound_variable_definition_sha256` helper for the complete report commitment.
The request schema is `legal-parent-bound-variable-definition-request/v1`, the
report schema is `legal-parent-bound-variable-definition-report/v1`, and the
profile is `conditional-parent-unary-definition-at-bound-variable/v1`.
The existing HTML APIs retain their original schemas and default behavior.

```python
prepared = prepare_parent_bound_variable_definition_v1(
    companion, request_raw,
    expected_companion_sha256=independent_companion_hash,
    expected_request_sha256=independent_raw_request_hash,
    companion_inputs=complete_original_companion_inputs,
)
validate_parent_bound_variable_definition_v1(
    prepared, companion, request_raw,
    expected_report_sha256=independent_complete_report_hash,
    expected_companion_sha256=independent_companion_hash,
    expected_request_sha256=independent_raw_request_hash,
    companion_inputs=complete_original_companion_inputs,
)
```

Supply the complete original parent nomination companion and all six original
preparation arguments: `norm_preparation`, `request_raw`,
`expected_norm_preparation_sha256`, `expected_request_sha256`, `norm_inputs`
and `definitions`. The outer request has its own independent raw-byte pin;
it does not replace the nomination request retained inside `companion_inputs`.
Both opening and closing public nomination validation replay the complete norm
and every supplied definition alternative. The original parent/cache/provenance
files, occurrence selectors, definition candidates and raw native donor receipt
remain required; a report hash, saved success flag or selected endpoint alone
cannot replace them.

The closed request uses the same exact occurrence, binder, ordered argument,
role, inverse source paths, whole definition references and explicit carrier/
interpretation/time declarations documented above, under the distinct parent
schema/profile. The selected donor remains the existing unary Boolean
`forall x, D x iff Body x` profile. The whole original parent donor native
receipt is regenerated before its exact head and body subtrees are rendered.
Every definition alternative and nominated occurrence remains in the report.
Two typed uses of one physical anchor do not establish two statutory uses.

`instance_only` assumes explicit unverified `hDefinition` and generates the
instance `D entity iff Body entity` at the supplied shared interpretation and
fixed formal `Nat` time. `body_with_membership` additionally requires the exact
explicit unverified `hMembership` for the same head, entity, interpretation and
time. Neither mode extracts a witness, establishes membership or converts a
civil legal-as-of date into formal time.

Original/detached inputs, parsed requests and native donor records, genuine
upstream/native/rendering returns, producer sources, renderer class/methods/
helpers, policy/bounds and all original physical norm/definition file witnesses
remain checked through closing replay and final direct serialization. The
parent snapshot retains its 1,500,000-node and 128-MiB aggregate input profile,
128-KiB request and 8-MiB report bounds. Complete overflow refuses; alternatives
and evidence are not truncated. These are input bounds, not process quotas.

Preparation returns complete generated `lean_source`, exact native subtrees,
rendering and named conditional statements. Retain the full report and text
with their original replay inputs; generated `#print axioms` commands are text.
This API supplies no Lake project, compiler process, native build receipt or
registered execution profile. Any qualification's saved text artifacts need
separate actual artifact readback; a test assertion alone is not a kernel result.

The unchanged relational `source_binding` remains null and `source_bound` false.
The whole companion retains both original physical source populations and their
unresolved contexts. Governing use and selected interpretation remain null;
all authority flags stay false, the norm AST is unchanged, and semantic,
consumer, training and evaluation-gold masks remain integer zero. Conditional
text does not establish source meaning, definition applicability, substitution,
a semantic graph edge, corpus admission or a learning target.

The [separate conditional qualification](../../../../../docs/autoformalization/evidence/legal-ir-parent-bound-variable-definition-20261025.json) passed **29 cases / 87 phases / 16 selectors**: 27 new controls and two selected legacy positives, on source `c3dc3df3...` and owning test `1d394670...`, including the renderer callback correction. Both concrete mode reports, original request bytes and generated Lean texts were independently inspected. Instance mode retains one hDefinition conditional; body mode retains that conditional plus the explicit hMembership consequence. The generated text was not compiled or kernel checked. Original compute/storage/source custody closed, retaining47 files/6,080,076 bytes. The earlier v01 source-mismatch refusal dispatched no native job and retains zero qualification credit.

Keep this campaign separate from the prior parent nomination **29/87/14** qualification (`f83919d1...`/`625610be...`, `test_parent_nomination_*` case identities). It qualifies selected authored controls, not entire owning modules or full-package startup; the14 scoped namespaces/eight bypassed initializers retain their declared limits. Governing applicability, source meaning, two distinct physical statutory uses and later parent Lake composition remain separate. Existing8D,384D,768D and Leanstral4096D lanes/checkpoints are unchanged.
