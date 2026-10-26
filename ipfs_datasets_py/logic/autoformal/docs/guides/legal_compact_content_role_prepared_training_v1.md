# Explicit role checkpoint: bounded prepared training

`legal_compact_content_role_prepared_training_v1` is an opt-in consumer of
`legal-compact-role-training-checkpoint/v1`. It retains one actual model and one
named Adam across a bounded session. Current weights, optimizer history, role
objective, immutable original basis and immediate-parent lineage keep their
existing identities. The checkpoint is never translated into an older schema.

The current development domain is the same two exposed authored rows, 384D
conditioning, 537-token vocabulary and denominator 67 qualified by the direct
role-training owner. `baseline` and `semantic_priority` remain distinct bound
policies. A session is not evidence of improved reconstruction, held-out legal
accuracy, source meaning, statutory applicability, graph admission or Lean
admission. Other widths and actual USCode deployment require separate work.

## Public interface

```python
session = prepare(
    checkpoint,
    expected_checkpoint_sha256=checkpoint_digest,
    expected_policy_sha256=role_policy_digest,
    max_steps=declared_finite_update_count,
)
status = session.inspect()
result = session.advance(steps=1)
last_complete_checkpoint = session.checkpoint()
close_report = session.close()
```

The caller obtains `prepare` from this explicit module. These calls belong
inside the existing admitted native worker and source lease. This API creates
no scheduler, lease, output directory, publication, checkpoint upload or model
download. The caller must enroll and durably retain every call and failure.

`max_steps` is a plain positive integer bounded by the existing total 2,048-step
limit. Each `advance` admits one through four updates within the remaining
session budget. These bounds do not qualify a long run. Invalid counts are
rejected before training. The opaque existing `PreparedTrainingSession` capsule
cannot be copied, pickled or given replacement attributes; operations are
confined to their original process and thread and cannot overlap or reenter.

`inspect` returns status, current progress, remaining updates, entered/completed
work counters, preparation provenance and phase timing. `advance` returns each
actual step's complete checkpoint and observation, plus the final checkpoint,
its digest, accounting and timing. `checkpoint` returns a detached last-complete
state. No returned checkpoint claims durable storage.

## Reused owners and numerical path

The adapter pins the direct role-training owner and existing session capsule.
The role owner's qualified `_scope` retains bounded original/captured input
commitments and the existing fast custody, source and loaded-origin checks.
Its `_validate` and `_row` establish the complete original basis, explicit role
inventory and two-row ordering at entry. Its public `restore`, `objective` and
`pack` execute the existing named state restoration, differentiated scalar and
same-schema successor construction. The returned public objective scalar is
the scalar actually passed to `backward`; the complete objective report is
returned unchanged. Existing numerical factories, Adam, clipping and actual
state checks remain their original owners.

The public restoration, objective and packing calls retain their complete
checkpoint validation. This consumer does **not** implement cached objective
kernels or claim the fast prepared trainer's throughput. It reuses one model
and Adam across updates and caches only each row's conditioning and target
tensors. The first qualification concerns same-state consumption, objective
parity, saved resume and custody. Kernel or end-to-end performance needs its
own measured comparison.

The consumer counts public restoration calls, forwards, objective calls,
backwards, Adam steps and pack calls as entered/completed. Exact model/Adam
factory counts and GRU calls require independent native instrumentation; a
failed public restoration is not assigned invented internal factory counts.
Reported phase intervals are sequential calling-thread CPU and wall clocks.
They exclude durable I/O and contain validation costs; neither GPU use nor
isolated kernel throughput follows from them.

## Custody and failures

Each update has four guards: before forward, after forward, before Adam, and
after the fully validated pack immediately before exporting the report. They
check source bytes and physical identities, loaded owner origins, original and
captured caller inputs, runtime and ambient CPU RNG, cached row metadata, and
private model/Adam state. Tensor identity, storage pointer, shape, stride,
dtype, gradient flag, version counter and exact bytes are retained. Thus an
in-place `add_(0)` is detected even when tensor bytes are unchanged. Named Adam
membership and module training flags are also checked.

A failed active operation poisons the session and prevents further updates.
`inspect` remains available. A recovery `checkpoint` can return the last
complete checkpoint only when source, input, runtime and row-cache custody
still passes; it never exports partially modified live state. Corrupt cache or
unrestored borrowed input can therefore prevent recovery. Restoring a borrowed
input does not unpoison the session.

`close` attempts both the ordinary guard and nested custody closing checks,
then clears the capsule's private model, optimizer, row cache and snapshot
references even when checks fail. Its report retains the prior status, private
reference-release indication and closing guard outcome. A poisoned session can
return a failed-closing-guard report; a ready session with a closing fault
raises after clearing those references. Repeated `close` returns the retained
closing fields without executing more work. This is a statement about capsule
references, not all external instrumentation or exception tracebacks.

No default dispatcher, existing owner implementation, acceptance threshold or
native resource policy is changed by this addition. Numerical qualification
results belong to the separately frozen execution record, not this source
description.
