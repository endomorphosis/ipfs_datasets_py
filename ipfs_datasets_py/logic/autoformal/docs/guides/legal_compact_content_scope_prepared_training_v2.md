# Scope prepared training v2: explicit fast input custody

This opt-in consumer uses the qualified framed fingerprint helper while keeping
the existing scope checkpoint, objective, numerical implementation and named
Adam state. The original v1 consumer remains available unchanged. No dispatcher
or default training route is redirected by adding this module.

## Interface and identities

```python
session = prepare(
    checkpoint,
    expected_checkpoint_sha256=checkpoint_sha256,
    expected_policy_sha256=policy_sha256,
    max_steps=bounded_updates,
)
```

The result is the existing pinned `PreparedTrainingSession` capsule. Its
`advance(steps=1..4)`, `checkpoint()`, `inspect()` and `close()` operations retain
their original behavior. `max_steps` remains a plain positive integer within
the unchanged 2048-update lifetime limit and the checkpoint's remaining work.
The caller owns admission, physical accounting, output retention and durability.

The session, advance, step and phase-timing reports use v2 identities. Preparation
and every step include an `input_custody` record with the executing consumer,
qualified fingerprint helper and original prepared-mechanics source descriptors.
That record identifies bounded original copying, both input commitments, four
update guard sites and the retained nested closing checks. It grants no authority.

Checkpoints remain `legal-compact-scope-training-checkpoint/v1`. Their
`implementation`, objective policy, initial and immediate-parent commitments,
model state and named Adam metadata are produced under the unchanged direct
owner contract. The v2 consumer's execution identity belongs in its reports;
it is not inserted into or substituted for the historical checkpoint identity.
No old checkpoint is relabeled, converted or admitted by a weakened validator.

## What changes

The v1 prepared function has no injectable custody hook: its state, step and
dispatch functions are private closures. This additive v2 retains that
orchestration with an explicit custody-context substitution. It reuses the
original scope owner's `_validate`, `_row`, canonical serialization and digest,
the weighted owner's `_numeric` and `_actual`, the same model/Adam factories,
and the original opaque session capsule. The objective kernels, update order,
clipping, complete actual-state export and successor construction are unchanged.

The new private `_scope(original)` yields `(captured, modules, fence)` without
constructing a model or optimizer. Its two nested contexts preserve the original
weighted-source and scope-dependency lifecycles. The original `_scope` functions
are not entered, and no loaded legacy function or global is rebound. Importing
the original prepared module supplies a pinned mechanics reference only; its
`prepare()` is not the implementation executing the v2 session.

The input layer still copies the borrowed value through the original runtime's
bounded `_copy(..., maximum=24 MiB, allow_bytes=True)`. It commits the captured
input with `legal_compact_content_fingerprint_v1.fingerprint`. Each input fence
checks both that captured input and a fresh bounded copy of the current original
against the same commitment. It does not cache a mutable object's hash or remove
either traversal. The helper preserves the head's exact framed bytes and adds
its own aggregate validation; that work remains charged to this consumer.

## Preserved guards

Every fence retains the full weighted source roster and loaded-module origins,
scope-owner source identities, selector/token object identities and source pins,
and the token/scope-policy agreement. The new consumer and fingerprint helper
are also bound by exact source bytes, physical identities and loaded origins.
The helper is checked before its initial hash and before each inner input fence,
including inner close/finally checks. The surrounding checks independently cover
the same helper and the original prepared-mechanics reference.

The four update guards remain before forward, after forward, after gradient
capture/clipping, and after actual-state export and successor construction.
Process/thread confinement, CPU RNG, dtype/grad mode, runtime identity, cached
row metadata and exact tensor marks, private model and named Adam state checks
remain unchanged. Construction, checkpoint export and close retain their guards.
Normal exit, exceptional exit and both nested finally paths are preserved;
flattening those contexts would omit checks.

A failed operation poisons the session. Restoring a changed borrowed input does
not make it ready again. A poisoned session can export only its last complete
checkpoint, subject to the original recovery checks. Close releases private
references and is idempotent; an already-poisoned session reports closing failures
under the original rules. Exported checkpoints and reports remain detached.
The session capsule retains its own original exception type for capsule-level
refusals; v2 preparation and operation failures use `PreparedTrainingError`.

These are finite source/input/runtime checks, not protection against arbitrary
Python reflection, malicious interpreter mutation or unobserved descendant work.
A source read lease remains the caller's responsibility and does not replace
local source checks.

## Qualification boundary

The source-only AST comparison records the narrow changes to the retained v1
body. It does not establish numerical parity by itself. Before relying on the
new consumer, qualify both objective profiles against unchanged direct and v1
transitions, including logits, losses, gradients, full model/Adam state,
immediate parents and resumed transitions. Retain pure-context mutation tests
and independent session poisoning witnesses with actual work counts.

The previously measured helper gain is not a v2 training-throughput result.
Any training comparison must hold checkpoint, objective, physical updates,
source/runtime, output cadence and acceptance rules fixed and keep all attempts.
Preparation, update, validation, output and close intervals have distinct scopes.
No reconstruction improvement, statutory or held-out accuracy, graph/Lean
admission, or separate 768D/4096D qualification follows from this change.
