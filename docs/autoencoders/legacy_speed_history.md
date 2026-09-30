# Legacy training speed: retained history and selective ports

Audit date: 2026-09-30. The reference runtime is the isolated 8-dimensional
`autoencoder_lineages.legacy_v1` snapshot from
[`ddf6b794`](https://github.com/endomorphosis/ipfs_datasets_py/commit/ddf6b79467b68159650df81befc288c8553df664).
The snapshot already contains substantial performance work. Replacing it with
the current runtime, or changing its reconstruction objective, would not be a
speed-only port. The [lineage guide](legal_autoencoder_lineages.md) describes
the checkpoint ancestry, explicit 8D/384D profiles and shared compiler boundary.

This audit uses local Git objects and source diffs. Commit descriptions below
identify implementation changes; they are not fresh throughput measurements.
The historical snapshot is later than the June teacher checkpoint's preparation
commit, so these changes do not establish how that checkpoint was trained.

## Already present in the frozen runtime

| Commit | Mechanism retained in `legacy_v1` | Operational implication |
| --- | --- | --- |
| [`2af27f1c4`](https://github.com/endomorphosis/ipfs_datasets_py/commit/2af27f1c4a7a595eab36e9a3d998e01e8388e311) | Target timeout fallback and cache management | Target fallback remains an observation, not successful semantic conversion. Cache state must be reported in timing comparisons. |
| [`eaefe6c9c`](https://github.com/endomorphosis/ipfs_datasets_py/commit/eaefe6c9c), [`93dc670a3`](https://github.com/endomorphosis/ipfs_datasets_py/commit/93dc670a3) | CUDA profiling, resident state and batched multi-head updates | CUDA support did not disappear when the historical namespace was created. Select it only after profiling the actual workload. |
| [`6fa83e051`](https://github.com/endomorphosis/ipfs_datasets_py/commit/6fa83e051749739ba51d3d427677607c33a11a60) | `projection_max_update_families` | The historical search can already be bounded explicitly; reducing the family count changes the attempted search and must be recorded. |
| [`174357d19`](https://github.com/endomorphosis/ipfs_datasets_py/commit/174357d19) | Incremental state identity | Avoids whole-state JSON hashing for unchanged components; identity work can still scan changed components. |
| [`a13fd23df`](https://github.com/endomorphosis/ipfs_datasets_py/commit/a13fd23df) | Compact versioned checkpoints and append-only state deltas | These primitives exist in the frozen helper closure. This does not mean every facade or distributed runner supports every format. |
| [`7b5117933`](https://github.com/endomorphosis/ipfs_datasets_py/commit/7b5117933) | Touched-row copy-on-write transactions | Proposals already use sparse journals. They still make avoidable postimage copies during norm accounting and rollback. |
| [`e7b48cab2`](https://github.com/endomorphosis/ipfs_datasets_py/commit/e7b48cab2) | Deterministic packed tensor state | Packing exists; it is not a reason to silently change checkpoint storage or load a different teacher. |
| [`c03c66ffd`](https://github.com/endomorphosis/ipfs_datasets_py/commit/c03c66ffd) | True batched CUDA training kernels | Keep kernel and Python paths comparable, including fallback telemetry and update acceptance. |
| [`eff0b57a0`](https://github.com/endomorphosis/ipfs_datasets_py/commit/eff0b57a0b6615afa55cf74cadeef23d86604c76) | Collated minibatches and resource-safe batch autotuning | `modal_autoencoder_batching` is frozen with the model; external hardware orchestration is not automatically frozen with it. |

The snapshot also includes later capacity selection, factorized heads and
low-rank legacy distillation helpers. Capacity selection and distillation are
modeling choices; their presence is not a reason to prune or adapt the full
teacher during a speed comparison.

## What changed after the snapshot

| Commit | Relevant change | Port decision |
| --- | --- | --- |
| [`9422f1835`](https://github.com/endomorphosis/ipfs_datasets_py/commit/9422f1835f6ad8ef1bd14414effb5ae9d4fe0895) | Verified Arrow-backed feature-weight override, accepted-patch sink, complete shared-target infrastructure, and a guarded native-target summary fast path | Reuse the control-plane infrastructure through explicit versioned adapters. Porting only the Arrow override without its source-row verification and mutation/replay contract is insufficient. |
| [`f342f78a8`](https://github.com/endomorphosis/ipfs_datasets_py/commit/f342f78a84b42823cdf8ca42b52f5292e04ae1c3) | Owner-caught target deadline cancellation escapes adapter `except Exception` handlers | A correctness change for cancellation and fallback reporting. Test owner cleanup and deadline disposition; do not classify fewer returned targets as a speed gain. |
| [`fa1a70176`](https://github.com/endomorphosis/ipfs_datasets_py/commit/fa1a7017632b6b0be6b74f96a7ebffc5d5c76db2) | Process resource envelopes, optional worker reuse, evaluation phase telemetry and disjoint tuning protection | Useful orchestration, with producer binding and cache isolation. Worker reuse is not automatically faster for a complete small run. |
| [`1df3c496d`](https://github.com/endomorphosis/ipfs_datasets_py/commit/1df3c496d), [`ea8213e48`](https://github.com/endomorphosis/ipfs_datasets_py/commit/ea8213e48cf1d12d01dc7f583fcde7f962fd793d) | Bounded qualification parallelism and training-first screening of optional reconstruction refinements | Screening can avoid an expensive validation after a necessary condition already failed. Refinement itself changes the proposal set and needs a separate optimizer version. |
| [`c16bcdf1c`](https://github.com/endomorphosis/ipfs_datasets_py/commit/c16bcdf1c), [`424ba3dda`](https://github.com/endomorphosis/ipfs_datasets_py/commit/424ba3dda) | Guarded adaptive learning rates, momentum, productive search and epoch controls | Algorithm changes, not implementation-equivalent speed ports. Compare accepted gain per wall time on disjoint validation before adopting. |
| [`03bf05a51`](https://github.com/endomorphosis/ipfs_datasets_py/commit/03bf05a51992bd70c2e6f225e656babe9b0dfa2e) | Shared-target handoffs; streamed transaction norm accounting; fewer candidate snapshots and rollback copies; consistent proposal deadline boundaries | First source for a narrow, behavior-preserving optimized legacy descendant. Keep the original snapshot reproducible. |
| [`8b59c5eeb`](https://github.com/endomorphosis/ipfs_datasets_py/commit/8b59c5eeb83ab882c6c65da92947ffe62bfe8e16) | Target readiness and compact structural/decoder proposals | Readiness reporting is reusable. Proposal-shape changes need explicit search versioning and parity/quality evaluation. |
| [`3675513ea`](https://github.com/endomorphosis/ipfs_datasets_py/commit/3675513ea) | Explicit raw-decoder feature training with verified inputs and private parallel lanes | Retain for the current legal line. Legacy target-aware safety projection and raw reconstruction measure different objectives. |
| [`f4c76aded`](https://github.com/endomorphosis/ipfs_datasets_py/commit/f4c76aded) | Bounded legacy CUDA census workers and paired outputs | Inference/census scheduling, not evidence of faster legacy training epochs. |

The historical model already accepts `legal_ir_targets` and precomputed
evaluations. The missing part is a verified, lineage-aware handoff through the
current producer/worker/control-plane boundary, rather than inventing a new
target cache. Target artifacts need sample content and embedding identity,
ordered bridge names, prover/worker/timeout configuration, canonical producer
identity and complete target semantics. A lossy metric-cache row is insufficient.

## Recommended order and opportunity cost

1. **Stream transaction norms in an opt-in legacy descendant.** The old helper
   calls `capture_patch()` before discarding unrelated rows, then builds complete
   flattened before/after dictionaries. Borrow only owner-checked journal rows
   during synchronous read-only accounting, filter before visiting values, and
   stream leaves in the historical reduction order. This targets temporary
   allocation without changing updates, objective weights or accepted proposals.
   Preserve stringified-key collision behavior, nonfinite handling and component
   journal semantics; public patch APIs must still return isolated snapshots.
2. **Extract a narrow search hook before porting discard/deadline work.**
   Historical `rollback_projection_transaction` captures a patch whose return
   value its callers discard. A private discard operation can restore the same
   journal without that postimage. However, replacing the entire thousand-line
   search solely to reach this hook creates substantial maintenance risk. Keep
   public `rollback()` unchanged, test exception paths, and apply cooperative
   deadline checks before starting new capture/evaluation work. A deadline is
   not proof that an in-flight native operation was forcibly interrupted.
3. **Bind prepared targets to the versioned runtime interface.** Sharing targets
   across many proposals or workers can save more wall time than a microkernel
   improvement. Account for preparation separately; a one-off short run may cost
   more overall. Never share an incomplete target, bypass source provenance or
   silently reuse targets with different bridges. Keep failed/timeout statuses.
4. **Add Arrow and sparse publication at the adapter boundary.** The existing
   mapped weights and accepted-patch infrastructure are candidates for reuse.
   Preserve source-row verification, parent identity, complete replay and private
   proposal state. Measure loading, resident memory, accepted delta size and
   consolidation cost before making mapped storage the legacy default.
5. **Ablate optimizer changes separately.** Adaptive steps, raw reconstruction,
   compact proposals and refinement may improve useful learning, but are not
   guaranteed to preserve the historical result. Compare the same starting
   checkpoint, sample identities, real embeddings, objective and validation
   gates. No implementation here proves convergence to a global minimum.

## How to verify a port

For bookkeeping, compare exact norm reports, exact accepted/rejected outcomes
and final state identities against the unmodified historical namespace. Include
insertions, deletions, nested values, string-key collisions, nonfinite leaves,
whole-component journaling, inactive/conflicting ownership and failure cleanup.
Run both namespaces in one process to detect cache/module replacement. Keep
public snapshot isolation tests independent from private borrowed iteration.

Microbenchmarks must state touched rows, unrelated rows, dimension and whether
they measure Python allocation or process RSS. A faster norm operation is not
an end-to-end training speedup. For a bridge-on comparison, record wall time per
evaluate and per span, sample count, the actual bridge names, prover flag, worker
count, metric disk-cache flag, explicit target reuse and sample-memory setting.
`legal_ir_target_count == 0` cannot substantiate a legal-IR speed claim.

The dated [shared-target and bookkeeping report](../implementation/reports/AUTOENCODER_SHARED_TARGET_HOTPATH_20260929.md)
contains earlier 384-dimensional observations, their sample/configuration scope,
and unsuccessful native training outcomes. Those are historical evidence, not
benchmarks of the newly isolated 8-dimensional runtime. Fresh port results must
be recorded separately.

## Other IRs remain different models and contracts

The native structural backend's streamed successor arrived in
[`6ee602832`](https://github.com/endomorphosis/ipfs_datasets_py/commit/6ee60283230db13c203c4efd5eae37286828dd5b)
as `autoencoder_projection_features_v2.py`. Preserve both native v1 and v2
identities alongside Security, Intent and UI/UX projection contracts. This is
not an 8D legal speed port. A common interface should select an explicit
domain, backend version, feature-space/embedding identity, checkpoint parent
and projection/validator contract; it must not pretend different modality
targets or qualification evidence are interchangeable.

All speed and feature results remain non-authoritative for legal admission.
Only the applicable source-bound `lake build <Lib>` proof path can admit a Lean
artifact; syntax, loss, bridge targets and stored rows cannot. The Constitution
is not formalized by any runtime or storage change described here.

## Implemented opt-in profile and measured scope

The frozen baseline remains `autoencoder_lineages.legacy_v1`. Select
`autoencoder_lineages.legacy_v1_optimized` explicitly to use the
`legacy-v1-streamed-norms/v1` runtime profile. Both belong to `legacy_hub_v1`,
accept the same historical eight-dimensional state class and local checkpoints,
and keep the historical reconstruction objective and acceptance criteria.

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages import (
    legacy_v1_optimized,
)

model = legacy_v1_optimized.load_checkpoint(
    local_checkpoint_path,
    expected_sha256=recorded_checkpoint_sha256,
    compute_device="cpu",
)
print(model.describe()["runtime_profile"])
report = model.train_generalizable_projection(
    training_samples,
    validation_samples=validation_samples,
    legal_ir_bridge_names=(
        "modal_frame_logic", "deontic_norms", "fol_tdfol", "cec_dcec",
        "external_prover_router",
    ),
    legal_ir_evaluate_provers=False,
    legal_ir_parallel_workers=1,
    epochs=1,
    learning_rate=0.01,
    max_seconds=180,
    max_line_search_attempts=1,
    projection_max_update_families=1,
    projection_update_backend="python_sparse_batch",
)
```

Use the existing canonical import pin and explicit embedding provenance when
constructing those samples. This example does not download weights, establish
semantic embeddings or grant admission. The bridge settings above are explicit
usage settings; they differ from the bridge-off bookkeeping diagnostic below.

The implementation ports only the streamed norm accounting from `03bf05a51`.
A static batch-method override has the same syntax tree as its frozen parent,
except for the relocated CUDA helper import; the selected norm helper is local
to the optimized module. Tests bind the parent's method SHA256 and compare the
syntax trees, so maintenance cannot silently introduce a different update loop.
There is no replacement of process-global modules or private mutation of another
runtime's helper. Public transaction snapshot and rollback APIs remain intact.
The profile intentionally retains the historical treatment of standalone
whole-component deltas, which that norm report did not count.

The [September 30 diagnostic receipt](../implementation/reports/evidence/legal-lineages-20260930/legacy-streamed-norms-benchmark.json)
records five alternating repetitions on CPU with exact output parity:

| Measurement | Frozen runtime | Optimized runtime |
| --- | ---: | ---: |
| Median norm accounting, 3,000 touched eight-wide embedding rows and 300 compiler-facing head rows | 14.812 ms | 1.513 ms |
| Peak Python allocations during norm accounting, measured separately from timing | 1,498,262 bytes | 54,484 bytes |
| Median complete two-epoch diagnostic, 3 training and 3 validation samples | 0.8680 s | 0.8085 s |
| Complete diagnostic wall time divided by its 6 input spans | 0.1447 s/span | 0.1348 s/span |

The norm operation was 9.79 times faster in this fixture; the complete small
training diagnostic used about 6.9% less wall time. These are local observations,
not a guaranteed corpus or CUDA throughput gain. Allocation figures measure
Python allocation peaks, not process RSS. The training run accepted one of two
epochs and produced identical weights, state identities and reports after
excluding elapsed-time fields. All thirteen historical trainable norm fields,
key collisions, nonfinite leaves, ownership errors and component replacement
are covered by the focused 21-test suite.

The diagnostic used synthetic vectors, no bridge names, provers disabled,
metric disk cache disabled, one configured metric worker and sample memory
disabled. Its legal-IR target count was zero. It therefore provides **no
bridge-on evaluation or legal conversion speed claim**; the per-span values
above divide a whole training experiment by its input count. It loaded no
archived teacher weights and measured no held-out semantic qualification.

Reproduce the bounded diagnostic after installation with a new output path:

```bash
PYTHONPATH=. python3 scripts/ops/legal_ir/benchmark_legacy_streamed_norms.py \
  --rows 3000 --head-rows 300 --repeats 5 \
  --output workspace/test-logs/legacy-streamed-norms-new-run.json
PYTHONPATH=. python3 -m pytest -q \
  tests/unit/logic/test_legacy_autoencoder_streamed_norms.py
```

Shared-target job handoffs, discard-without-postimage and deadline changes remain
separate follow-up ports. The optimized profile does not inherit current raw
reconstruction or adaptive-search policies merely because they are faster on
another lineage.

## Installed validation and bridge-on parity

The final installed suite passed **201 tests in 11.82 seconds**, covering both
legal lineages, the optimized profile, modality contracts, native v1/v2 kernels,
the common version interface, and the three compiler/decompiler gates. All 23
frozen modules regenerated byte-for-byte from their historical Git source.
The [validation receipt](../implementation/reports/evidence/legal-lineages-20260930/streamed-norms-interface-validation.json)
records source hashes, scope and commands. These checks ran in the shared
canonical checkout, which contains unrelated uncommitted work; the receipt does
not claim a clean-tree campaign or a full dependency provenance attestation.

The [baseline](../implementation/reports/evidence/legal-lineages-20260930/streamed-norms-baseline-bridge.json)
and [optimized](../implementation/reports/evidence/legal-lineages-20260930/streamed-norms-optimized-bridge.json)
bridge-on runs used the protected restart12 checkpoint and the three gate
sentences, with explicitly synthetic 8D diagnostic vectors. Each produced
**3 targets for 3 spans**. All recorded reconstruction and family metrics matched
exactly; canonical compiler/parser/decompiler hashes were stable within and
between measurements.

| Runtime | Bridge-on evaluate wall time | Wall time per span |
| --- | ---: | ---: |
| Frozen `legacy_v1` | 7.209 s | 2.403 s |
| Opt-in `legacy_v1_optimized` | 7.107 s | 2.369 s |

Both used `modal_frame_logic`, `deontic_norms`, `fol_tdfol`, `cec_dcec`, and
`external_prover_router`; provers were false, metric disk cache was 0, metric
workers were 1, and sample memory was false. Each ran in a fresh process with
no supplied targets: process and metric target caches were cold; OS cache was
uncontrolled. Loading and sample preparation are recorded separately. The
evaluation implementation is unchanged, and these single measurements do not
establish an inference speedup or semantic qualification. No Lake build or
model admission was performed by this comparison.

```bash
PYTHONPATH=. python3 scripts/ops/legal_ir/measure_legacy_runtime_bridges.py \
  --runtime legacy_v1 --output workspace/test-logs/frozen-bridge-new.json
PYTHONPATH=. python3 scripts/ops/legal_ir/measure_legacy_runtime_bridges.py \
  --runtime legacy_v1_optimized --output workspace/test-logs/optimized-bridge-new.json
```
