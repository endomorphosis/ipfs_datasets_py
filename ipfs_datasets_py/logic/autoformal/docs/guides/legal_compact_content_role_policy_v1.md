# Closed semantic-structure priority policy

`legal_compact_content_role_policy_v1` is a pure projection of offered compact
LegalIR annotations into training weights. Its companion training owner must
first validate the entire original scope-conditional basis checkpoint and
recompute its original grammar inventories. A hash or the original schema name
alone does not establish that upstream validation happened.

The public interface is:

```python
policy(weighting="baseline")  # "baseline" or "semantic_priority"
policy_sha256(policy)
prepare_inventory(
    basis_checkpoint,
    row_index,
    expected_basis_checkpoint_sha256=...,
    expected_policy_sha256=...,
    policy=policy,
)
```

Both policies keep scope-conditional cross entropy, the original allowed token
sets and denominator67. The `semantic_priority` policy has the descriptive name
**semantic-structure-priority**; it does not equalize semantic-role groups.

| Offered position class | Count per supported row | Baseline weight | Priority weight |
| --- | ---: | ---: | ---: |
| Scope singleton |39|1|1|
| Quantifier constructor |2|4|9/2|
| Modal constructor |1|4|9/2|
| O/P/F modal letter |1|4|9/2|
| Ordered variable reference |2|4|9/2|
| Predicate constructor |1|4|1|

The seven nontrivial positions retain total weight28: `6 × 9/2 + 1`.
The39 singleton positions retain total weight39, making the complete sum67.
Every actual weight is exactly representable in float32. Singleton conditional
losses and gradients remain identically zero; retaining their weights in the
denominator preserves the existing normalization rather than making them
meaningful learning decisions. Binder declaration IDs and the sole predicate
reference are such singleton semantic slots in these fixtures.

Classification uses the existing baseline annotation role, lexical constructor
and tree path, checked against canonical target bytes and codec token IDs. It
does not branch on row IDs or absolute position numbers. The profile is closed
to the existing two-binder, one-modal, binary-predicate geometry with39
singletons and seven choices; unsupported roles, altered masses, newly
singleton baseline choices or incomplete inventories are refused. A consistent
new offered target could still be semantically wrong. This pure module neither
reruns the original grammar nor proves source/target correspondence.

`prepare_inventory` returns a new detached report containing the complete
position table, original annotation path, selection reason, float and rational
weight, allowed IDs, flat `position_weights` and `scope_allowed_token_ids`,
target/label IDs, exact role counts and sums. It binds the original basis,
policy, baseline inventory, scope inventory, context, target and codec hashes.
Its `authority` fields are false and training/evaluation masks are zero. It
constructs no model or optimizer and changes no checkpoint.

The new policy must receive a new policy and checkpoint identity. It must not be
written over an old scope checkpoint or presented to an old consumer by
relabeling its schema. Training and checkpoint validation belong to the
companion owner; this module does not own an alternative optimizer or grammar.

The prior exposed conditional rollout first diverged by choosing a predicate
where the second quantifier was available. It then had only variable0 available
for both arguments, so the repeated argument followed from that earlier prefix.
The target prefixes do offer the second quantifier, modal and both ordered
variables. This motivates an exposed development hypothesis, not an observed
improvement. Reducing predicate-constructor weight4 to1 could delay predicate
selection or increase unnecessary nesting. Better teacher-forced performance
also need not improve free generation after an earlier prefix error.

The independent `run_tests(module)` suite uses manually authored lexical/path
fixtures and checks exact baseline/priority vectors, rational and float32 sums,
unchanged masks, detached outputs, false authority, both modal rows and malformed
or rehashed commitments, roles, paths, target IDs, masks and masses. Its fixtures
are deliberately not numerical checkpoints; native direct qualification must
supply the real old validated basis. Static source review or these pure tests
alone cannot establish training, reconstruction, statutory meaning, source
encoding, heldout generalization, 768D/4096D behavior or Lean qualification.
