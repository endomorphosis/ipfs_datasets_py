# Relational reconstruction diagnostic contract

The new product file is `ipfs_datasets_py/logic/autoformal/legal_relational_reconstruction_v1.py`.
It compares two independently pinned **valid** authored relational reports by
replaying the existing public relational validator on both original request
byte strings. Invalid or unsupported input refuses; this paired diagnostic is
not a batch validity/abstention denominator or a statutory accuracy evaluator.

Public APIs:

```python
prepare_relational_reconstruction_comparison_v1(
    reference_report, candidate_report, *,
    reference_request_raw, candidate_request_raw,
    expected_reference_request_sha256, expected_candidate_request_sha256,
    expected_reference_report_sha256, expected_candidate_report_sha256,
)
relational_reconstruction_comparison_sha256(report)
validate_relational_reconstruction_comparison_v1(
    report, *args, expected_comparison_sha256, **kwargs,
)
```

The output's closed top-level fields are:

```text
schema, profile, status, reference, candidate, comparisons,
signature_diagnostics, role_diagnostics, feature_ledger,
reference_only_paths, candidate_only_paths,
valid_input_pair_only, invalid_inputs_refused, abstention_coverage_evaluated,
producer_pins, authority, training_mask, evaluation_gold_mask, limitations
```

Schema is `legal-relational-reconstruction-comparison/v1`; profile is
`paired-valid-authored-relational-structure-diagnostics/v1`; status is
`unreviewed_valid_relational_pair_compared`.

`comparisons` has exactly these booleans:

```text
exact_typed_expression_equal, family_profile_equal,
signature_declarations_equal, argument_roles_equal,
declared_structure_equal, lexical_alpha_structure_equal
```

Exact equality compares full original typed-expression serialization, including
expression/node/signature IDs and content digest. Declared structure removes
only the existing expression/node/signature ID fields and the expression's
derived content digest; it explicitly normalizes signature sort/predicate
declaration order and role-row order keyed by predicate name. Ordered arguments,
role values, binder names, quantifier kinds, operator direction, modal placement,
extension payload/features and schema identities remain exact. No arbitrary
metadata keys are stripped; the existing relational profile already rejects
nonempty metadata/ranges.

Lexical alpha agreement uses the existing bounded
`syntax_core.algebra.LogicExpressionAlgebra.alpha_equivalent` on complete
validated roots, gated on normalized signature/family/profile and ordered-role
agreement. It does not implement another alpha algorithm, invoke
`semantic_identity`, reorder children or infer legal equivalence. Fresh IDs
alone leave declared and alpha agreement true. A consistent bound-variable
rename changes declared agreement but preserves alpha agreement. Capture,
argument swaps, quantifier/operator changes and modal placement remain distinct.

`reference` and `candidate` each retain original request raw-byte SHA/length,
full canonical report SHA, typed-expression SHA/content digest, and separately
named diagnostic projection hashes. They do not contain a replacement AST.

`feature_ledger` covers the complete ordered union of the two authoritative
`structural_mapping` path populations: reference order, then candidate-only
paths in candidate order. Each row has exactly `typed_path`, `presence`,
`reference`, `candidate`, `declared_features_equal`, `declared_differences` and
`identity_differences`. Presence is `both`, `reference_only` or `candidate_only`;
missing-side features and equality are null. Differences list differing flat
feature names; node IDs are reported separately from declared feature changes.

Each nonnull flat feature row has exactly:

```text
kind, node_id, native_path, symbol, sort, ordered_child_paths,
binder_paths, binder_name, binding_quantifier_path, quantifier_kind,
predicate_symbol, predicate_typed_path, predicate_argument_index,
declared_argument_role, argument_roles,
modal_operator, extension_payload_schema, extension_family, extension_profile,
extension_features, extension_payload, modal_ancestry, connective_ancestry
```

Absent features are explicit null or empty lists. Binder/extension rows are
included, not inferred from `LogicNode.walk` alone. Derivation cross-checks exact
authoritative mapping order, path, kind, node ID and binder identity. Formula
children stay in declared order; `binding_quantifier_path` identifies the parent
quantifier NODE path (for example `/root`), while the binder feature's own
ledger path is `/root/binders/0` and the quantifier lists that in `binder_paths`;
argument position and declared role are explicit. Ancestry is diagnostic
metadata over the existing AST, not a new AST or independent source grounding.

Limits: request bytes at most 524,288 each; original reports at most 8 MiB each;
ordinary finite detached JSON before lazy owner import; whole output at most
4 MiB. Complete overflow refuses, with no truncated row population. Self and
trusted owner source hashes are fenced before/between/after public replays,
projection and serialization. Offered producer filenames are never read before
public replay has proved them against trusted fixed owner sources.

Every authority flag remains false and both masks are integer zero. There is
no aggregate accuracy score, model/embedding/training call, legal-equivalence
decision, semantic gold/admission, native build or Lean execution.

Suggested tests cover self pairs, ID-only changes, binder alpha renames,
predicate/role/argument swaps, implication direction, O/P/F placement,
quantifier kind/order, signature/role-row reorder, missing/unexpected paths,
full report/request pin substitution, resealed tampering, malformed/free-variable
requests, finite preflight, source fences and bounded complete output. Reuse the
real relational fixture builders by exact source path under native execution.
