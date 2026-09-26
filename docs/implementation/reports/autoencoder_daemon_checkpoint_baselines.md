# Daemon checkpoint baselines without retained state copies

The daemon checkpoint path now retains a small immutable identity record for
its last queued endpoint instead of a second complete training state. Delta
serialization normalizes the current state once and compares its component
identities with that record. It still emits the existing component-replacement
checkpoint format, and the final full compact checkpoint remains authoritative.

The source-stable combined regression passes 651 checks. Native training
validation remains deferred at the user's request. Synthetic persistence fixtures are not evidence of native
learning, complete-cycle speed, or lower aggregate worker memory.

## Codec and writer

The [checkpoint codec](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder_checkpoint.py)
adds `CheckpointBaseline` and `SerializedCheckpoint`. The token contains schema,
precision, revision, requested metric lineage and component/state digests. It
contains no state object, parameter rows or checkpoint payload. It is a local
serialization aid, not a durable receipt or an independently verified artifact.

`serialize_checkpoint_snapshot` and `serialize_delta_snapshot` return the
existing encoded bytes together with the persisted endpoint identity.
`serialize_delta_from_baseline` avoids reconstructing the prior endpoint.
`checkpoint_baseline` supplies the initial identity on a resumed daemon when no
startup full snapshot was necessary. Existing byte-returning serialization APIs
remain available, as do the existing loader, log, schema and recovery rules.

The [asynchronous writer](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/async_artifact_writer.py)
attaches the token to its immutable snapshot handle. Source revision checks
remain in place; legacy callers supplying a mutable base state retain the
existing base revision check. Supplying both a base state and a token is
rejected. Precision and metric lineage must match the baseline exactly.
Noncompact snapshots do not acquire a checkpoint token.

## Actual daemon integration

The [runner](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/uscode_modal_daemon_runner.py)
reuses a startup full snapshot's identity when one is written. A fresh run's
first cycle still writes a full checkpoint; resumed cycles capture an initial
normalized identity when necessary. Subsequent full or delta snapshots advance
the baseline only after enqueue returns successfully. The baseline describes
the last queued endpoint, not confirmed disk durability.

Writer failures, drain results, replay and independent full-candidate
verification retain their existing meaning. Error cleanup can still persist
an independently valid full checkpoint; that file does not turn a failed
invocation into successful execution. The baseline does not grant model
promotion, publication or Lean admission.

## Cost and scope

This removes the runner's per-cycle full baseline copy and each delta's repeated
prior-state quantization/native reconstruction. Current-state normalization,
component digest calculation, whole changed-component encoding and log
verification remain. A single row change can still serialize its entire
component. This is not a new row-sparse checkpoint format or whole-training
zero-copy implementation. Writer byte reservations still count serialized
payload bytes; token and ordinary Python-object overhead are not an RSS bound.

The existing sparse v1 artifact path and diagnostic daemon sparse shadow keep
their separate contracts. Arrow mapping, shared targets, optimizer acceptance,
context limits, temperature and backend choices are unchanged. A future native
comparison must include startup normalization, serialization, queued memory,
writer drain and complete invocation cost; it must preserve the same bridges,
prover/cache flags, worker count, samples and sample-memory policy.

## Verification

The codec's pre-change source is retained in the
[frozen reference](../../../workspace/test-logs/federal-corpus-audits/checkpoint-persistence-baseline-20260925/modal_autoencoder_checkpoint.before.py),
SHA-256 `054f48d51309d6489c237bb18604ae9a6490c1597d00117dc5439cfd744bbba5`.
The new tests embed the original serialization bodies as an independent
reference instead of comparing only two wrappers over the new implementation.

- [Codec capture](../../../workspace/test-logs/federal-corpus-audits/checkpoint-persistence-baseline-20260925/codec-r3.receipt.json) and
  [checks](../../../tests/unit/optimizers/logic_theorem_optimizer/test_modal_autoencoder_checkpoint_baseline.py):
  136 passed in 3.19 seconds, including 26 existing and 110 new cases. They
  compare exact full/delta bytes for float32/float64 and all 38 components,
  preserve copied-base and revision semantics, exercise native replay and
  verify that a baseline delta constructs only the current persisted endpoint.
  The retained first fixture referenced a nonexistent replay helper; it was
  corrected to use the public loader, without a production change.
- [Writer checks](../../../tests/unit/optimizers/logic_theorem_optimizer/test_async_artifact_writer_checkpoint_baseline.py):
  34 passed in 3.48 seconds, including 17 new cases. They cover source/base
  revision drift, immutable handle compatibility, graph release, queue rejection
  and failed-write spool replay. A first test expected the wrong exception
  wrapper; its retained failure was corrected to expect the original `OSError`.
  No production failure behavior changed to satisfy that assertion.
- [Daemon checks](../../../tests/unit/optimizers/logic_theorem_optimizer/test_daemon_checkpoint_baseline.py):
  8 passed in 10.12 seconds. Actual `main` and the real asynchronous writer
  exercise three/five cycles, interval resets, restart, startup compaction,
  torn-tail recovery, replaced graph release and enqueue/disk failures. The
  optimizer and evaluation boundaries are explicitly synthetic.

The [combined regression receipt](../../../workspace/test-logs/federal-corpus-audits/daemon-checkpoint-baseline-20260925/combined-r1-receipt.json)
records **651 passing checks**, zero failures/errors/skips, across 20 files in
119.86 pytest seconds (121.963635 seconds for the bounded subprocess wrapper).
All 7,739 canonical package Python files and selected test files stayed unchanged
during capture. Protected checkpoint and historical receipt sizes/SHA-256 values
also remained exact. The capture includes semantic gates, the round-trip pilot,
compact HF packages, shared targets/reports, mapped weights and owner invocation
contracts. Receipt SHA-256:
`3c2e82042db6cee8f4474f0ba040d358c87f2f10eb005813d06c02876e951037`.

Focused and combined suites overlap; their counts must not be added. No new speed
or quality claim is made here. Only `lake build <Lib>` constitutes a Lean admit.
The Constitution remains unformalized. Producer source changes also invalidate
older sealed target bundles for new training; reuse requires the existing
current-source checks and fresh preparation where those checks demand it.
