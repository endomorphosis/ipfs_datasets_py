# Explicit role-weighted conditional training

`legal_compact_content_role_training_v1` is an opt-in direct training owner for
`legal-compact-role-training-checkpoint/v1`. It changes the position weights
used by the differentiable conditional objective. It does not modify an old
checkpoint's policy label or rewrite any existing owner.

The initial population is the existing two exposed authored rows, with a 384D
conditioning vector, a fixed 537-token vocabulary and the same GRU, optimizer,
learning rate, gradient clipping, source grammar and scope masks. It is a bounded
development profile, not a source encoder or a statutory training corpus.

## Immutable basis and new state

Creation requires the exact independently committed zero-step
`scope_conditional` checkpoint and its original policy hash. The original scope
owner validates that basis, including its donor, population, typed inventories,
source pins, empty Adam state and runtime. The new checkpoint retains the entire
basis unchanged under `basis_checkpoint`.

Current model tensors, named Adam moments, progress, initial and immediate-parent
hashes belong to the new outer schema. They are validated independently through
the unchanged head, optimizer-state and actual-state primitives. Later role
weights are never presented to an old public inspector as a scope checkpoint.
The basis supplies initialization and immutable training data; it is not a claim
that its original objective produced the new current state.

The checkpoint also contains `objective_policy`, its independent SHA-256,
`role_inventories` and their aggregate hash. Every validation recomputes the old
basis inventories and then the new role annotations/weights. A rehashed altered
basis, role mask, weight or policy must still satisfy those independent checks.

The source tree remains pinned. The new owner composes the qualified fast
fingerprint custody context with its own source and loaded-origin checks. Both
caller and captured values remain checked, including closing paths. It does not
rebind another module's functions or constants.

## Two policies with the same denominator

Both arms retain `objective_kind="scope_conditional"` and normalize by the
complete position-weight sum of 67. The public pure role-policy owner defines
the exact presets:

- `baseline`: 39 singleton positions have weight 1; seven nontrivial choices
  each have weight 4.
- `semantic_priority`: singletons still have weight 1. Six nontrivial positions
  for binder/modal constructors, the modal letter and variable references each
  have exactly representable weight 4.5. The remaining predicate constructor has
  weight 1. Nontrivial weight is still 28 and total weight is still 67.

These are weights over the original teacher-forced token positions and masks.
They are not a new parser or a check of logical equivalence. Position roles and
ordered tree paths come from the existing public decision inventory. The
underlying relational reconstruction diagnostics remain the separate evaluation
of binder, modal and ordered-argument structure.

A singleton conditional position has zero loss and zero logits gradient,
regardless of its weight. In the retained rows, binder-declaration tokens and
predicate-reference tokens are singleton positions. This policy cannot create
learning signals for those choices. Upweighting selected nontrivial positions
reduces the predicate-constructor emphasis and may make predicate construction
worse. Both favorable and adverse outcomes must be retained. Training loss or
role weighting alone does not establish semantic reconstruction accuracy.

## Public direct API

```python
checkpoint = role_training.create(
    basis_checkpoint,
    expected_basis_checkpoint_sha256=basis_sha256,
    expected_basis_policy_sha256=basis_policy_sha256,
    weighting="baseline",  # or "semantic_priority"
)
options = {
    "expected_checkpoint_sha256": role_training.checkpoint_sha256(checkpoint),
    "expected_policy_sha256": checkpoint["objective_policy_sha256"],
}
inspection = role_training.inspect(checkpoint, **options)
row = role_training.training_row(checkpoint, **options)
model, optimizer = role_training.restore(checkpoint, **options)
# The admitted caller owns forward/backward/clip/Adam and finite work accounting.
loss, observation = role_training.objective(checkpoint, logits, **options)
# After one separately observed and performed actual update:
successor = role_training.pack(model, optimizer, checkpoint, progress, **options)
```

`checkpoint_sha256` computes a bounded canonical identity; it does not qualify a
checkpoint. `inspect` and `training_row` validate the whole new schema without
constructing a model or optimizer. `restore` uses the original numerical factory
and restores all named Adam moments. `objective` consumes finite differentiable
CPU float32 scores of shape `[1, 46, 537]`; it performs no forward, backward or
optimizer update. Even masked-out scores must be finite.

`training_row` exposes the original conditioning/target order, scope masks,
role-position weights, role labels, inventory hashes and policy commitment. The
objective observation reports selected and full-vocabulary diagnostics,
per-position losses and exact position weights. Full-vocabulary diagnostics do
not change the conditional optimization denominator.

`pack` validates the actual named tensor/Adam state through the original owner,
requires a one-step progress increment and records the immediate parent hash.
The independent admitted caller must retain actual forward/backward/clip/Adam
observations; a stored step counter is not proof of the operation's execution.
Fresh policy initialization uses the exact basis weights and fresh Adam. There
is no random reinitialization and no inheritance of historical donor moments.

Serialize new checkpoint artifacts as canonical compact JSON when they must be
read through the unchanged 4 MiB per-input native boundary. Retaining the intact
basis increases pretty-printed size; increasing that boundary or trimming basis
provenance is not part of this implementation. No original checkpoint artifact
is reformatted or overwritten.

## Qualification and consumers

Initial numerical qualification should use each new policy for step 0 to 1 to 2
and a fresh restore of saved step 1 followed by repeated step 2. Across the two
policies this is six actual updates and four model/Adam restores. Record the
actual full logits, same-backward logits gradients, complete pre/post-clipping
parameter gradients, state, named moments and immediate-parent lineage.

The new-schema baseline should reproduce the old conditional baseline's
numerical state while retaining a distinct checkpoint identity. Semantic-priority
updates should be checked against their independently computed weighted
objective and gradient, not forced to equal the baseline. Saved-resume equality
is required within each policy.

The existing public scope prepared consumer and inference consumer intentionally
accept their original checkpoint schema. They must reject this new schema until
a separately versioned adapter is implemented and independently qualified. This
module does not copy the prepared trainer, add a model cache, invoke generation,
or automatically enroll a longer learning run. Existing model factories, Adam
validators and fast custody are reused directly.

All semantic, legal, graph, Lean and production authority flags remain false.
No 768D or 4096D behavior, source autoencoding, unseen-law performance or Lean
compilation improvement follows from this bounded implementation. Public law
span/entity aggregation and larger-width training remain separate work.
