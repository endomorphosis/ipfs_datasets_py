# Lease renewal during owner-side result preparation

The [training coordinator](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_training_coordinator.py)
previously stopped polling all workers while it checked a finished worker's
receipt, reconstructed and replayed sparse updates, compacted a checkpoint, and
copied/fsynced artifacts. A slow completion could therefore expire the leases
of unrelated parallel jobs and waste otherwise valid training work.

Those operations now run serially on one owner-side preparation thread. The
calling owner thread continues renewing every active run, including workers
that have already finished and are waiting for completion. A run retains its
dispatch slot until it completes or its quarantined work drains. The change
adds neither an unbounded completion queue nor parallel reconstructed state
graphs. Worker processes still receive only immutable job specifications.

The private preparation helper may use only the registry's file operations:
`artifact_path`, `verify_artifact`, and `stage_artifact`. These operations do not
use the DuckDB connection. This is the existing daemon artifact-staging pattern,
now applied to the complete coordinator verification/staging phase. All claim,
renewal, failure, operation-resolution, and completion commands stay on the
calling owner thread. Registry schema, operation IDs and exact-payload response
loss recovery are unchanged.

A failed renewal quarantines that run once without stopping other heartbeats.
Queued preparation can be cancelled; running file work is allowed to unwind
before its result is discarded. An immutable CAS file alone is not a registered
version. Only a final owner renewal followed by the original `CompleteRun`
artifact check and lease/fence transaction can register a candidate. Failure
still cannot promote a branch or produce a Lean admit. The preparation executor
is joined before the caller can close the registry. A completed preparation
future is released before waiting for another worker, so its exception traceback
does not remain retained in that local across subsequent jobs.

The opportunity cost is one thread and periodic heartbeat transactions during
preparation. Replay, serialization and storage byte volume are unchanged; this
change prevents an avoidable control-plane stall rather than speeding up those
operations. Dispatch remains bounded by the existing worker count, and receipt
schemas, shared targets, sparse policy and Arrow opt-in defaults are unchanged.

`CompleteRun` still synchronously hashes the final artifact on the owner thread
before committing. An unusually slow final hash can still expire a lease; the
original fence rejects completion in that case. Long GIL-holding native work,
unresponsive filesystem calls, and process shutdown also prevent a hard
heartbeat deadline guarantee. This change does not qualify cross-host Quack,
activate DuckLake, change resource ceilings, or introduce a production timeout
supervisor. A later source-bound native comparison must measure these remaining
latencies before any end-to-end throughput claim. The canonical-tree and
producer-source guards remain enforced: future qualification must use artifacts
sealed against the current sources, while earlier receipts retain their
historical source bindings.

The [focused liveness tests](../../../tests/unit/optimizers/logic_theorem_optimizer/test_autoencoder_completion_liveness.py)
passed **10 checks in 4.34 pytest seconds** (5.278581 seconds for the bounded
subprocess). The
[focused receipt](../../../workspace/test-logs/federal-corpus-audits/autoencoder-completion-liveness-20260925/liveness-r3-receipt.json)
records stable worker source pins, coordinator, registry and test hashes. Real
registry files and filesystem preparation threads are used with injected
synthetic workers, bounded event gates and a deterministic clock. The selection
covers:

- Renewal of the current result and other finished or still-running workers
  during blocked replay and receipt staging, with no extra dispatch.
- One preparation at a time, owner-thread SQL, pool drain and scratch cleanup.
- Real lease replacement/fencing of either the preparing or another run,
  preserving the replacement lease while the surviving run completes.
- Preparation failure isolation, exact operation/payload retries after lost
  renewal/completion responses, and no duplicate durable-candidate events.
- Rejection when the final synchronous artifact hash outlasts the lease.

The [combined regression](../../../workspace/test-logs/federal-corpus-audits/completion-liveness-20260925/combined-r1-receipt.json)
passed **541 checks across 12 files in 46.71 pytest seconds** (48.668660 seconds
for the bounded subprocess), with no failures, errors or skips. All 7,743
canonical package Python files, selected tests and protected historical
artifacts stayed unchanged during capture. The selection also covers worker
contracts, independent sparse replay/compaction, registry recovery, offline HF
package reopening, pinned-tree semantic gates and the round-trip pilot. Focused
and combined counts overlap and must not be added.

Combined receipt SHA-256:
`db715f12de050c8f64b157b03eac1e59e1140078d4aa5b9eb82a0e6960315800`.
The [frozen pre-edit coordinator](../../../workspace/test-logs/federal-corpus-audits/completion-liveness-20260925/autoencoder_training_coordinator.before.py)
is retained at SHA-256
`a1530b22629efc868cd8d9dbce2cb9a8f010b8ff899ade2075b1d7e141615c11`.
The final production coordinator is SHA-256
`f997f298dcd4527a78c82d0eed57a9d416e8c1a710dc5a991a702e0876149e92`.

An intermediate expanded focused capture was interrupted after one pass and one
failure when another process edited the pinned parser. Worker provenance refused
to continue with changed sources. That
[receipt](../../../workspace/test-logs/federal-corpus-audits/autoencoder-completion-liveness-20260925/liveness-r2-receipt.json)
and its log are retained separately; they are not qualifying evidence. The new
pending-worker fixture also exposed a test-only wait when an earlier worker
failed before entering preparation. Its fallback is bounded; the production
source guard is unchanged.

Native training validation remains deferred at the user's request. No new wall
time per legal span or bridge-on evaluate is claimed. No model was published or
promoted. Only `lake build <Lib>` is a Lean admit. The Constitution remains
unformalized, with no new `roundtrip_ok` spans.
