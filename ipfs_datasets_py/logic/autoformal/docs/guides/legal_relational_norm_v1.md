# Strict typed relational norm fragment

`legal_relational_norm_v1` lowers a small, explicitly declared subset of the existing `syntax_core.ast.TypedExpression` to the existing native `deontic_fol` route. It is an adapter between existing syntax owners; it does not introduce a new general AST or translate statutory text. The same owner has the separate explicit mixed-sort profile below.

The first profile accepts exactly one `Object` carrier with bound variables, predicates with explicit ordered arguments, binary `and`/`or`/`implies`/`iff`, unary negation, one binder per `forall`/`exists`, and the existing `legacy.deontic/v1` O/P/F extension. Typed family/profile are `tdfol`/`tdfol_default`. An ordered per-predicate role ledger must match the declared arity. Actor/recipient/approver/direction labels are caller declarations, not semantic type distinctions or inferred legal roles.

The request is closed JSON:

```python
request = {
    "schema": "legal-relational-norm-request/v1",
    "interpretation_status": "authored_unreviewed_declaration",
    "expression": typed_expression.to_dict(),
    "argument_roles": [
        {"symbol": "Assign", "roles": ["actor", "recipient", "origin", "destination"]},
        # Every predicate declaration requires one exact ordered role list.
    ],
    "source_binding": None,
}
```

Use `prepare_relational_norm_v1(request_raw, expected_request_sha256=...)`, retain the full output digest from `relational_norm_report_sha256`, and replay with `validate_relational_norm_v1(report, request_raw, expected_request_sha256=..., expected_report_sha256=...)`. Independent expected hashes must come from the original retained manifest. New hashes for changed input cannot authenticate an earlier request.

The public module imports operation owners lazily after bounded, duplicate-free finite JSON and its independent byte commitment are checked. The received typed expression must reproduce exactly through the shared owner, including its content identity. The bridge independently checks lexical binders, sort/arity, modal extension fields, ordered roles and supported structure. All declared predicates must be used. Unknown fields, silent defaulting, free variables and unsupported annotations cannot disappear during reconstruction.

Each supported typed node has a retained structural correspondence to the generated native AST. The existing native route performs strict original/printed parsing and checks exact AST parity before generating Lean text. This is syntax and declared-structure qualification. The modal interpretation remains parameterized; no deontic axiom, source fidelity, legal truth or proof authority is conferred.

Necessary versus sufficient conditions are explicit formulas, for example `P(action) → approval` and `approval → P(action)`. The adapter preserves their different implication direction. It does not decide which formula captures a particular law. The [integration qualification](../../../../../docs/autoencoders/legal_ir_norm_integration_20261015.md) identifies the retained authored fixtures and finite countermodels for modal scope, action alternatives and ordered actor/recipient/origin/destination arguments. Their finite model semantics are declared separately from the parameterized Lean text.

The active adapter checks its producer commitments both before work and after complete report serialization. A temporary-file mutation test covers a producer change during native lowering; historical isolated reports keep their original producer identities.

Constants, functions, equality, true/false nodes, additional sorts, free variables, binder shadowing, n-ary connectives, unsupported modalities/annotations, cardinality, counting frames, purpose and anaphora are outside this profile. No native name renaming or implicit connective normalization is performed.

The request's source binding is explicitly null. The previous real-source §101 definition alternatives and §§7213/7214 scope declarations remain unchanged; they retain unresolved meaning and open context. Joining reviewed statutory roles to this fragment, adding supported richer constructs and executing statutory Lean builds require their own explicit inputs and qualification. Generated Lean text is not an actual build.

Authority flags remain false and training/evaluation masks remain zero. The adapter supplies no actual human review, signer, trust policy, graph admission, accepted lookup or governing definition-use edge. Organizer exposure and component-level training/evaluation boundaries remain part of subsequent review and release.

## Explicit mixed-sort relational profile

The existing owner adds `prepare_mixed_relational_norm_v1`,
`validate_mixed_relational_norm_v1` and
`mixed_relational_norm_report_sha256`. This profile accepts atomic `Object`,
`EventFrame` and `TimeFrame` sorts alongside `Bool`, bound variables, declared
predicates, Boolean structure, same-sort builtin equality, quantifiers and the
closed `legacy.deontic/v1` O/P/F extension. The original Object-only profile and
its native parser route retain their own contract.

Use schema `legal-mixed-relational-norm-request/v1`, profile
`authored-many-sorted-relational-deontic/v1` and the exact six request fields:
`schema`, `profile`, `interpretation_status`, `expression`, `argument_roles` and
`source_binding`. Status is `authored_unreviewed_declaration`; source binding is
null. Supply the complete existing `TypedExpression` and every ordered role list.
Retain the independent raw-request hash and complete report hash for replay:

```python
report = prepare_mixed_relational_norm_v1(
    original_request_raw, expected_request_sha256=independent_request_hash)
validate_mixed_relational_norm_v1(
    report, original_request_raw,
    expected_request_sha256=independent_request_hash,
    expected_report_sha256=independent_complete_report_hash)
```

The bridge reuses the typed kernel and the shared
`logic.formalization.autoencoder.native_family_lean_emitters.SortedFormulaRenderer`
through `sorted_relational_document`. The explicit
`sorted-relational-renderer-ast/v1` record is a renderer input, not a native
TDFOL AST or parser receipt. The shared owner retains its original `PRELUDE` and
Boolean/modal branches. Predicate arguments enter
`Sum Unit (Sum Object (Sum EventFrame TimeFrame))`; quantifiers and Lean equality
operate directly on their original source carriers. The Unit tag realizes unused
prelude fields without requiring an inhabited source sort. O/P/F remain distinct,
unconstrained interpretation parameters. Ambient `Nat` trace time remains separate
from authored `TimeFrame`; no civil-time interpretation or modal axiom is added.

Both retained §7214 hypotheses keep their complete 98 core nodes, separate modal
payload, 12 binders, 14 predicate occurrences, six equalities and ten ordered
predicate-role declarations: 111 mapping rows, not 111 AST nodes. Their exact
47-node cap core and different permission placement survive in separate reports.
Role labels remain caller declarations; a changed valid ordering or modal scope
is a different unreviewed proposal. Neither alternative is selected or exhaustive.

The [mixed-profile observation](../../../../../docs/autoformalization/evidence/legal-ir-mixed-sort-relational-lowering-20261026.json) records two independently accepted scopes: 21 pure cases / 63 phases / nine selectors (20 new cases and one legacy case), and one separate native case / three phases / one selector. The native case ran one bounded version probe and one Lean 4.34.1 compilation of both definitions plus identity and empty-carrier witnesses. Fourteen unused-variable warnings remain. Both scopes use the frozen `f53da571` dependency/data generation with three exact overlays; the later `81396996` delivery has a separate source-only compatibility review and no combined-generation runtime qualification. Counts are not pooled with earlier graph, counting or native cohorts.

The preparation report retains null source/meaning/governing bindings, false
authority and four integer-zero masks. No native TDFOL or corpus dispatch profile,
source correspondence, definition applicability, learned decoder, training/gold
target or semantic graph admission is registered. The separate successful compiler
check establishes well-typed declarations and its explicit witnesses. It does not
prove general preservation or statutory truth. Parent source correspondence,
conditional corpus integration and substantive review remain separate work.
