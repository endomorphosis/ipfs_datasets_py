# Prepared training for the explicit scope checkpoint

`legal_compact_content_scope_prepared_training_v1.prepare` is an additive,
opt-in consumer of `legal-compact-scope-training-checkpoint/v1`. Its owner is
`legal_compact_content_scope_training_v1` at SHA256
`fb86141cd0b69fe74e43cc9460d557e890c90c07178bf9e1a62d15098552c208`.
It consumes the intact new checkpoint; it does not convert it to an older
checkpoint schema, alter its implementation identity, or modify another owner.

This is still the closed, two-authored-row, 384-dimensional conditioning profile
with the original 537-token output vocabulary and original a98 donor. It does
not qualify statutory reconstruction, held-out accuracy, a source encoder,
768D/4096D latents, graph admission, Lean admission, or native execution.

## API and ownership

```python
session = prepared.prepare(
    checkpoint,
    expected_checkpoint_sha256=checkpoint_sha256,
    expected_policy_sha256=checkpoint["objective_policy_sha256"],
    max_steps=2,
)
try:
    first = session.advance(steps=1)
    saved_checkpoint = session.checkpoint()
    second = session.advance(steps=1)
    status = session.inspect()
finally:
    closed = session.close()
```

The caller must already have native admission, an enrolled finite work roster,
independent observation hooks and an authorized output location. The API does
not acquire a lease, choose a work budget, write files, publish a checkpoint,
load a hidden model, or invoke inference. The example shows the API surface,
not a qualification result or permission to execute it.

`max_steps` is a plain integer from 1 through 2048, also limited by the
checkpoint's remaining original update budget. Each `advance` accepts one
through four updates within the remaining declared session budget. These are
API ceilings, not evidence that long training is qualified. Each update uses
one actual complete teacher-forced model forward, one backward and one Adam
step. Each session restores exactly one private model and one Adam, including
all saved named moments. No model, optimizer or cached tensor is returned.

The opaque session capsule is reused unchanged from
`legal_compact_content_weighted_prepared_training_v1` at SHA256
`6f7248714cea81edfe6fda69bb0abe38bb37535f2cb92d460d8e38c4d2cd4b07`.
Its old `prepare` is never called. The new consumer owns its dispatch and new
report identities. Operational errors use this consumer's `PreparedTrainingError`
(a `ValueError`); capsule attribute/copy/serialization errors retain the pinned
capsule's `ValueError` subclass. Catch `ValueError` when handling both surfaces.

## Validation, caching and lineage

At entry the original scope owner performs complete checkpoint, original
baseline inventory, refined scope inventory, policy, donor and progress
validation. Its composed `_scope` remains open for the entire session. The
original mutable caller checkpoint and independently captured input are both
fenced; caching does not release the caller's immutability obligation.

The consumer caches the two validated conditioning vectors, target IDs, labels,
original position weights and refined Boolean scope masks. Every public
checkpoint/advance/close path checks source custody, original input custody,
runtime, CPU RNG, process/thread identity, row metadata and exact tensor marks.
Ready-state operations also check private model, Adam, module flags and exact
state bytes. The new consumer and both directly used owners have separate
source/origin commitments, while the scope owner's fence covers its existing
transitive dependencies.

Actual restore and every completed update use the original weighted owner's
`_numeric` and `_actual` numerical/state helpers. Every successor preserves the
new scope schema, original immutable metadata, new policy and both inventory
commitments. Packing validates complete actual model weights and named Adam
moments, commits the exact immediate parent, advances progress by one, and
retains the exact initial checkpoint identity. It constructs the same fields
as the direct scope `pack`, without redoing complete grammar inventory
validation each step. The once-validated private metadata is never exposed.
Independent qualification must compare complete successor checkpoints against
the direct owner; an exported checkpoint alone is not a durability receipt.

The entire checkpoint remains in each step report and in `advance`'s result.
Each report is bounded to 24 MiB; an advance result is bounded to 112 MiB.
Checkpoint size remains subject to the original 16 MiB limit. The admitted
caller may impose stricter artifact and overall output bounds.

## Exact objective and diagnostics

Both policies retain **baseline-v1** forced/choice position weights of 1:4.
There are 46 supervised positions and a weight sum of **67** in each row.
Refined allowed sets do not reclassify those weights. The policies differ only
in the cross-entropy denominator:

- `full537` computes unreduced cross entropy over all 537 original logits.
- `scope_conditional` masks disallowed logits to negative infinity only after
  all 537 original scores pass the finite float32 check, then computes
  unreduced cross entropy over the refined allowed set.

Each loss is `(per_position * position_weights).sum() / weight_sum` using the
same PyTorch operations and float32 dtype as the direct scope owner. The direct
owner exposes no independently reusable loss kernel, so this consumer repeats
only its small loss/report construction rather than invoking its expensive
whole-checkpoint validator on every update. The numerical qualification must
compare its actual outputs, gradients and complete successors to retained
direct transitions. No monkeypatch disables an existing validator.

Conditional training additionally computes unmasked full537 per-position and
weighted losses under `no_grad`. In full537 training the diagnostics reuse the
detached original losses. The complete 537-score tensor is retained for every
position regardless of objective. An `objective_report` uses the direct owner's
observation schema, fields and flags. Its `forward_performed`,
`backward_performed` and `optimizer_update_performed` fields describe the
objective calculation only; actual enclosing update work is separately counted.

Each refined target set is nonempty and contains the original target. These
rows have 39 singleton and seven nontrivial positions. Singleton conditional
loss and gradient are zero regardless of model quality; masked-out coordinates
have zero conditional gradient. Lower conditional loss is not improved
reconstruction, and losses across the two denominators are not accuracy
comparisons. Preclip and postclip complete parameter gradients and the exact
Torch clip norm are retained; logits-gradient observations belong to the
independent caller's hooks on the same backward, with no extra differentiation.

## Failure and close semantics

An invalid advance count is refused before entering work and leaves a ready
session usable. A failure inside an operation poisons the session. `inspect`
continues to expose detached accounting and the last complete checkpoint hash.
Restoring a mutated borrowed input does not unpoison the session. `checkpoint`
can return only the last fully packed checkpoint after custody/runtime/cache
checks; a partial live update is never packed for recovery. Mutating a detached
checkpoint result does not mutate the internal state.

`close` fences and releases private model/Adam/cache references, including after
failure. It is idempotent. A closing error on an already-poisoned session is
reported through `closing_guard_passed` and error types; it does not suppress
the earlier failure. Advancing or requesting a checkpoint after close is refused.
The capsule is confined to its original process/thread and cannot be copied or
serialized. The API is an ordinary cooperative library boundary, not a sandbox
against malicious Python reflection or arbitrary process memory mutation.

## Accounting and required qualification

New report identities are `legal-compact-scope-prepared-training-session/v1`,
`legal-compact-scope-prepared-training-advance/v1` and
`legal-compact-scope-prepared-training-step/v1`. Accounting retains entered and
completed model construction, optimizer construction, model forward, backward
and optimizer step calls. `full_state_exports` counts the initial restored
state plus each completed update. Model-forward accounting is not independent
GRU observation; the admitted caller must observe actual modules and work.
Phase clocks report wall and calling-thread CPU time only. Durable I/O and
unattributed dispatch/copy work remain outside listed phase sums. Frequent
source/input and state fences still have costs; throughput improvement must be
measured rather than inferred from the cache design.

The narrow intended qualification uses both original objective policies and
compares cp0→cp1→cp2 plus a serialized cp1→cp2 replay to the six retained direct
transitions. It compares complete checkpoint/Adam bytes, objective observations,
full logits, actual logits gradients, pre/post parameter gradients and clip
norms. Four sessions account for six forwards/backwards/updates and four model
and Adam allocations. It also checks preallocation policy/schema refusal,
returned-export isolation, bounds, use after close, idempotent close and late
borrowed-input mutation followed by permanent poison. Those are planned checks
until a separate admitted execution and saved-only audit record their results.
