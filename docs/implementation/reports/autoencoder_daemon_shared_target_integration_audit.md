# U.S. Code daemon shared-target integration audit

Read-only call-path audit, 2026-09-25. No daemon training, benchmark, source
selection, or checkpoint promotion was performed for this audit. Worker
qualification does not establish a daemon speedup.

Subsequent implementation is tracked in the
[verified daemon handoff report](autoencoder_daemon_shared_targets.md).
The findings and proposed work below describe the pre-integration audit.

The normal U.S. Code cycle already uses the native one-pass optimization in
[`evaluate_autoencoder_with_bounded_metric_bridges`](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/uscode_modal_daemon_runner.py).
After evaluating bridges and aliasing their numeric targets, it reuses that
evaluation only for the exact native model/methods when every bounded sample
is the original object. Truncated clones and custom evaluation/alias methods
retain both passes. Empty inputs or disabled bridges use the bridge-off path.
The cycle passes this helper as `evaluation_callback` to the TODO supervisor.
It also supplies lineage-matched and precomputed evaluations where existing
state/sample checks permit reuse.

[`ModalTodoSupervisor._autoencoder_evaluation`](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_todo_daemon.py)
is a separate fallback. It evaluates the full bridge-off batch before its
bridge subset. Reordering those calls can change reconstruction through target
cache priming; the current compatibility test explicitly preserves that order.
The normal runner callback already avoids this fallback.

| Capability | Current daemon path | Separately implemented worker path |
| --- | --- | --- |
| Bridge-pass reuse | Native full-sample shortcut and existing evaluation caches | Ordinary native evaluator |
| Reusable complete targets | Ordinary process/disk metric caches; no sealed bundle handoff | Verified target artifact, exact requested sample/config checks, full target hydration |
| Sparse candidate ownership | Direct projection call and existing state/checkpoint writer | Explicit sparse backend, accepted-patch capture/replay, registry-owned result registration |
| Mapped Arrow artifacts | No Arrow input/feature-artifact loader at the audited callsite | Optional producer-bound input and checkpoint-bound feature artifacts |

The runner calls `train_generalizable_projection` directly. It passes metric
bridges, text limits, acceptance settings and precomputed evaluations, but no
`legal_ir_targets`, `projection_update_backend`, or `accepted_patch_sink`.
Its CPU update backend therefore follows the method's existing `auto` to
`native` resolution. Neither daemon module dispatches this call through
`run_training_jobs`. An in-process sparse update option alone would not provide
registry ownership or durable patch registration.

The existing target caches matter to the opportunity cost. Repeated daemon
evaluation can already reuse target results. Successful disk-cache writes also
replace the process entry with a numeric summary containing a document hash,
losses and view distribution; that summary is not a complete target artifact.
The disk fingerprint covers selected producer paths and uses cached file
metadata. It is not the complete package-content/configuration binding of
[`target_snapshot_config`](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_target_preparation.py).
The native worker's cold-versus-shared savings cannot be assigned to an
already-warm daemon cache.

The bounded next integration is an opt-in complete-target artifact handoff for
repeated or restarted projection candidates with the same verified selection.
It should begin with full samples for which the existing bounding helper
returns every original object. Required work remains:

1. Bind artifact SHA/bytes, full producer configuration and exact sample
   coverage through the existing bundle loader and `targets_for`; check the
   producer again after use and require a fresh process on source/runtime
   drift. Preserve the full artifact and preparation failure telemetry.
2. Pass verified targets to the bridge-on callback and projection training.
   Keep `legal_ir_targets=None` for bridge-off/base evaluation: the model's
   explicit-target branch precedes its bridge-name check. It also silently
   omits missing mapping IDs, so the integration must verify coverage first.
3. Retain the current path for bounded clones until their exact IDs, text,
   vectors and policy are separately bound. The daemon defaults to two metric
   bridges and a 600-character cap; truncated clones have synthetic IDs and
   mock vectors. Numeric cache aliases do not make them full-source,
   producer-bound samples. The worker's five-bridge/full-sample receipts cannot
   substitute for those checks.
4. Verify default, disabled-bridge, custom-method, bounded-clone, partial-target
   and source-drift behavior. Compare complete evaluation fields, state,
   acceptance decisions and capture observations before measuring one bounded
   actual daemon path. Do not regenerate a fresh bundle every cycle merely to
   introduce the artifact interface.
5. Treat registry-owned projection dispatch and candidate adoption as a later
   explicit integration: preserve immutable base identity, daemon acceptance
   gates, result lineage and head ownership. Keep Arrow optional until an
   actual daemon measurement establishes its benefit.

Existing gates provide useful foundations:
[`test_daemon_bridge_evaluation_reuse.py`](../../../tests/unit/optimizers/logic_theorem_optimizer/test_daemon_bridge_evaluation_reuse.py)
checks exact one-pass/two-pass metrics, target caches, subsequent evaluation,
custom hooks, bridge-off behavior and supervisor ordering.
[`test_modal_todo_daemon.py`](../../../tests/unit/optimizers/logic_theorem_optimizer/test_modal_todo_daemon.py)
checks bounded target aliases and precomputed evaluation/state reuse.
[`test_legal_ir_target_bundle.py`](../../../tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_target_bundle.py)
checks complete payload/evaluation parity, rich grammar, timeout inventory,
sample/config binding, independent shard validation and later file mutation.
Worker tests additionally cover verified full-target injection, changed
bindings, sparse replay and mapped-input closure. These tests were inspected,
not rerun for this audit.

The historical
[produced-corpus worker receipt](evidence/autoencoder_control_plane_plan/produced-arrow-training-20260925.json)
and [hydration-GC receipt](evidence/autoencoder_control_plane_plan/target-hydration-gc-native-20260925.json)
qualify their recorded bounded owner/worker jobs. They support reusing existing
artifact machinery, not a daemon throughput estimate. The produced-corpus
comparison did not show a complete-job benefit for mapped inputs over shared
targets with JSON inputs on its small batch. Full targets and source checks
take precedence over introducing another transport.

No default mode, model weights, target semantics, admission rule, DuckLake
activation or publication changed. The Constitution remains unformalized;
only an actual `lake build <Lib>` constitutes a Lean admit.
