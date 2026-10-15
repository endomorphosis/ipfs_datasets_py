# Strict typed relational norm fragment

`legal_relational_norm_v1` lowers a small, explicitly declared subset of the existing `syntax_core.ast.TypedExpression` to the existing native `deontic_fol` route. It is an adapter between existing syntax owners; it does not introduce a new general AST or translate statutory text.

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

Necessary versus sufficient conditions are explicit formulas, for example `P(action) → approval` and `approval → P(action)`. The adapter preserves their different implication direction. It does not decide which formula captures a particular law. The [authored fixtures and finite countermodels](../../../../legal-corpus-relational-norm-20261015-01/README.md) also preserve modal scope, action alternatives and ordered actor/recipient/origin/destination arguments. Their finite model semantics are declared separately from the parameterized Lean text.

Constants, functions, equality, true/false nodes, additional sorts, free variables, binder shadowing, n-ary connectives, unsupported modalities/annotations, cardinality, counting frames, purpose and anaphora are outside this profile. No native name renaming or implicit connective normalization is performed.

The request's source binding is explicitly null. The previous real-source §101 definition alternatives and §§7213/7214 scope declarations remain unchanged; they retain unresolved meaning and open context. Joining reviewed statutory roles to this fragment, adding supported richer constructs and executing statutory Lean builds require their own explicit inputs and qualification. Generated Lean text is not an actual build.

Authority flags remain false and training/evaluation masks remain zero. The adapter supplies no actual human review, signer, trust policy, graph admission, accepted lookup or governing definition-use edge. Organizer exposure and component-level training/evaluation boundaries remain part of subsequent review and release.
