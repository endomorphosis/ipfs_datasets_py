# Opt-in cached role-training consumer v2

This additive development consumer targets the two authored 384D H0 rows, fixed 537-token vocabulary, and explicit role-training checkpoint schema. It is based on the qualified 27,465-byte role prepared v1 lifecycle. It neither replaces that consumer nor changes the role checkpoint schema, implementation identity, immutable basis, objective policy, or authority flags. The original v1 source remains a pinned provenance dependency.

The intended improvement removes repeated validation of invariant checkpoint grammar, basis, inventories and policy during each private update. The v1 public objective validates the complete current checkpoint once; its public pack validates both current and successor checkpoints. Those three per-update validations include nested basis validation and inventory reconstruction. This v2 performs one lifecycle entry validation and retains the original public restore, which revalidates independently. It does not claim only one total validation at preparation.

No callable cached objective or pack kernel exists in the pinned direct owner. Consequently this small consumer mirrors the direct role objective expressions and observation fields, plus its seven changed pack fields. It reuses the original custody context, validation, public restoration, numeric runtime, progress validator, complete changed-state validator, and opaque session capsule. It does not copy the separate 43 KB scope prepared engine or modify a loaded module.

## API and accounting

```python
session = prepare(checkpoint,
    expected_checkpoint_sha256=checkpoint_sha256,
    expected_policy_sha256=objective_policy_sha256,
    max_steps=declared_remaining_work)
status = session.inspect()
answer = session.advance(steps=1)
last_complete = session.checkpoint()
close_report = session.close()
```

The capsule's actual public `advance` signature is retained from the pinned weighted prepared owner. Each advance requests one through four updates, bounded by both remaining session capacity and the original cumulative 2,048-step checkpoint limit. A declared bound is not qualification of a long run. Saved complete checkpoints resume through the same `prepare` API and public role restore.

Consumer session, advance, step and timing schemas use `/v2`; the profile is `authored-h0-384-fixed537-cached-role-training-consumer-development/v2`. The returned checkpoint remains `legal-compact-role-training-checkpoint/v1`, and the objective observation remains `legal-compact-role-objective-observation/v1`. Byte-identical successor checkpoints and numerical reports require independent qualification; the candidate source does not establish that result.

Accounting distinguishes the changed path explicitly: `cached_objective_calls_entered/completed` and `checked_pack_calls_entered/completed` replace v1's `public_objective_calls_*` and `public_pack_calls_*`. Restoration, forward, backward and optimizer-step counters retain their original names. These are reported call counters; independent caller observations are still needed for actual factory and GRU counts.

## Cached invariant inputs and unchanged objective

Preparation constructs six private CPU tensors for each validated row: conditioning, complete teacher-forcing targets, labels, positive role weights, their 67.0 denominator, and the 46 by 537 allowed-token mask. It checks the original population of 39 singleton and seven nontrivial positions. Every cached tensor is covered by the existing identity, storage, shape, stride, dtype, gradient flag, mutation-version and exact-byte guard. Guarded metadata remains private; exported objective observations copy its lists.

The differentiated scalar remains conditional per-position cross entropy, multiplied by the original role weights, summed and divided by 67.0. It uses the original `ignore_index=0` and `reduction='none'` settings. All 537 logits must be finite before masking. The full-vocabulary observation is evaluated separately under `no_grad`; it does not replace the scalar passed to backward. Logit version and exact values, ambient CPU RNG and runtime are checked at the objective boundary. Singleton zero loss is not accuracy, and conditional and full-vocabulary losses are not interchangeable accuracy measurements.

## Changed-state packing and custody

Each update uses the original `weighted._progress` and `weighted._actual`. The latter checks exact parameter order, actual model geometry/finiteness, named Adam membership, policy, step counters, moment shapes/finiteness and nonnegative second moments, then exports and checks the actual changed state through its original owners. The successor is a private deep copy with only model state/hash, optimizer state/hash, progress, immediate parent and initial checkpoint commitment updated. It is serialized under the unchanged 16 MiB checkpoint bound. Existing invariant fields and checkpoint implementation identity remain intact.

A complete new recovery state is committed only after changed-state checks, exact lineage construction and closing source/input/RNG/runtime custody. A later post-pack guard still runs before export. This v2 does not rerun the whole role grammar validator on every successor; its argument depends on once-validated invariant data remaining private and on exact changed-state construction. Finite qualification must compare the resulting complete checkpoints with the public direct owner and qualified v1.

The four inherited guard sites remain before forward, after forward, before Adam and after packing before report export. Their function body, source and runtime checks, model/Adam snapshots, module-mode checks, cache checks, process/thread confinement, dispatch, poison handling, closing behavior and outer preparation cleanup are AST-identical to v1. The source-owner loop additionally covers v1 as provenance. An active failure poisons the session. Closing releases private model, optimizer, cached tensors and snapshot even when its guard fails, records that failure and remains idempotent. Restoring a caller's corrupted input does not unpoison an active session.

A poisoned session can recover its last complete checkpoint only when the retained source/input/runtime/cache custody passes. This is not recovery from arbitrary cache corruption, nor a durable write guarantee. Durable outputs and admission remain the caller's responsibility.

## Qualification still required

No installation, product import, model execution, optimizer update, native request or saved-reader execution was performed to author this candidate. The companion AST delta audit is source inspection, not pytest or numerical qualification.

Before claiming a speedup or adopting the consumer, compare contemporaneous v1 and v2 at the same runtime, source and initial checkpoint pins. Prespecify baseline and structural-priority policies, two ordinary updates and one saved-step-one resume per policy, with counterbalanced execution order. Require exact direct/v1/v2 checkpoint, objective observation, full-sequence logits, gradients, Adam and lineage agreement. Retain all failures and complete phase/setup/close timings; cached-kernel timing alone is not end-to-end throughput. Exercise v2 cache-tensor, model-tensor, Adam-moment, default-dtype and ambient-CPU-RNG faults and record poisoning, unused capacity and closing outcomes. Borrowed-input and model-mode guards are retained by unchanged lifecycle AST and predecessor evidence; they are not additional live v2 witnesses in this fixed cohort. This document proposes qualification; it does not run or authorize it.

The scope remains this two-row authored development fixture. No new holdout reconstruction, US Code autoformalization, statutory accuracy, source semantics, graph or Lean admission, 768D/4096D behavior, long-run readiness or default/production adoption is claimed.
