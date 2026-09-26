# Owned dispatch for immutable autoencoder campaign jobs

Design and implementation status, 2026-09-26. The
[B1 prepared-request implementation](../reports/autoencoder_campaign_owned_preparation.md)
passed 338 bounded offline regression cases on the captured source revision:
169 codec, 72 owner, 45 journal and 52 resource cases, with no failures, errors or
skips. The user-authorized 60 GB cap increase preserved every historical ledger
record; the fresh 50 MB test reservation and host lease were released. The
[audit receipt](../reports/evidence/autoencoder_control_plane_plan/campaign-owned-preparation-audit-20260926-r1.json)
records unchanged package/dependency and protected-input guards.
[B2 worker execution](../reports/autoencoder_campaign_owned_execution.md) is now
implemented and passed 486 guarded offline regression cases. B3 transport remains
proposed. No native qualification, full-corpus
run, legal-IR speedup, live Quack listener, DuckLake write or Hugging Face upload
is claimed. Native validation remains deferred.

Historical capacity observations remain unchanged. The independent non-atomic census completed
at 2026-09-26T17:10:53Z observed 40,037,331,746 bytes plus 10,030,000,000 bytes across
17 retained reservations: 50,067,331,746 bytes, exceeding the 50 GB cap by
67,331,746 bytes. It found zero active/reserved claims and 185,935 entries with
no disappearances; roots and ledger stayed unchanged during observation. Ledger
SHA-256: `3dad515ba59e9494687f2bfa9c9b8be36479e80ced854cff6a415e7b8eb66b76`.
This blocked validation before the explicit cap increase; it is not the current
status. No historical evidence or retained claim was deleted or expired to pass
admission. Fresh work must still satisfy
`observed + outstanding + new reservation + expected growth + margin <= cap`;
the cap change grants no unbounded worker allocation. The earlier blocker
persisted across three consecutive goal turns and was resolved through the
authorized policy change, followed by the guarded offline tests. No native
validation window is requested by this plan.

This extends the [control-plane plan](AUTOENCODER_DUCKDB_DUCKLAKE_TRAINING_PLAN.md)
and [federal-law plan](FEDERAL_LAW_END_TO_END_TRAINING_PLAN.md). Preserve their
success criteria: only `lake build <Lib>` supplies a Lean admit. The Constitution
is unformalized. No model loss, checkpoint, transport receipt or database row
changes that status.

## Recommendation and the semantic boundary

Prioritize owner-controlled execution of the existing v8 worker jobs. It keeps
the user's shared targets, accepted sparse updates and optional Arrow weights
on the already implemented worker/coordinator path. The offline immutable request contract, durable operation recovery and resource
supervision are implemented and regression-tested. Exposing this execution
through Quack is the next stage.

An input-to-prepared-daemon map is smaller, but solves a different problem. A
daemon consumes the original job's corpus snapshot while using its own parsed
arguments and distinct run ID. It neither inherits `TrainingConfig` nor completes
that worker job. Worker evaluation disables sample memory; daemon training can
enable it. Shared-target consumption and sparse persistence also differ. Use
such a map only when explicitly choosing a separate daemon
experiment; it is not the default campaign execution adapter.

| Route | Reuses | Status | Result |
|---|---|---|---|
| Restricted daemon input map | Existing prepared handles, daemon journals, owned Quack control | Proposed: exact batch-to-input-to-request mapping and separate progress | A separately configured daemon run consumes campaign inputs |
| Owned v8 worker dispatch, recommended | Exact registered jobs, target bundles, worker patches, owner replay/compaction, Arrow weights | Implemented B1/B2; native validation deferred and Quack transport pending | The original registered campaign jobs complete through their existing acceptance path |

Neither route puts parameter access in DuckDB or Quack. Numeric reads remain
local; the control plane carries bounded immutable descriptors and status.

## What current code already guarantees

- [`autoencoder_campaign_plan.py`](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_campaign_plan.py)
  seals at most 128 batches and 64 MiB of job bytes. `_inspect` reconstructs the
  exact plan, verifies all jobs, and replays completed candidates. Running,
  failed or ambiguous original attempts block `run_campaign_plan` dispatch.
- [`autoencoder_training_coordinator.py`](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_training_coordinator.py)
  validates all selected jobs before claiming one. `_verify_receipt_payload`,
  `_prepare_completion` and `_verify_and_stage_patches` retain independent
  receipt validation, accepted-patch replay and owner compaction policy.
  Public `run_training_jobs` keeps its per-call operation IDs. The separate
  owned route adds a persistent journal without changing that public default.
- [`export_daemon_corpus_inputs`](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_corpus_inputs.py)
  already exports immutable v8 corpus snapshots with both roles verified.
  The wrapper binds corpus identity and does not translate training policy.
- [`prepare_daemon_invocation`](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_invocation.py)
  creates a distinct run and journal. Its `describe` child loads the full
  checkpoint; calling preparation is therefore outside the deferred native
  validation scope. Sparse bases require separately verified materialization.
- [`OwnedInvocationControl`](../../../ipfs_datasets_py/duckdb_control/autoencoder_owned_control.py)
  durably submits already prepared daemon handles. A committed start without a
  resolved terminal operation requires recovery, never automatic reexecution.
  Read status explicitly does not establish current artifact availability.
- The [owned Quack profile](../reports/autoencoder_owned_quack_control.md)
  accepts only submit/read/resolve with `run_id` and a request descriptor.
  Generic mutation commands reject registered worker jobs and daemon runs.
  Its current controller constructor accepts only the actual daemon controller.

The [package report](../reports/autoencoder_campaign_packages.md) records passing
historical test/restore captures and a failed current-tree closeout after
external edits. A restored package remains evidence, not an executable owner.
No adapter may infer current execution qualification from those captures.

## Optional route A: bind existing daemon handles to campaign inputs

Proposed new module: `duckdb_control/autoencoder_campaign_owned_inputs.py`.
Proposed APIs, deliberately without native preparation or execution:

```python
seal_campaign_owned_inputs(registry, plan_artifact, *,
    prepared_by_batch_id, worker_id, output_directory) -> assignment_artifact
inspect_campaign_owned_inputs(registry, assignment_artifact) -> report
```

The closed assignment manifest binds owner database/CAS paths, original plan
descriptor, ordered batch IDs, original run/job/canonical-job identities,
variant and base, input snapshot, complete prepared handle and distinct daemon
run/request identity. Bound one selection to 1–64 assignments, matching the
existing controller, and bound control bytes separately from existing job caps.
The supplied output is an exclusive local assignment directory, not any original
job's output. Seal only after checking every selected member; no auto-submission.

For each member, independently compare the plan batch, registered input anchor,
snapshot, actual request bytes, owner journal and execution run. Require request
base version and artifact to equal the original batch base; existing preparation
does not itself prove that equality merely by checking the corpus anchor.
Require unique execution IDs, exact owner CAS locators and exact handle/journal
binding. First scope: v1 daemon requests, full bases, no target snapshot, no
Arrow artifact and no sparse capture/storage policy. Reject unsupported inputs
before sealing; never silently omit a target or reinterpret sparse shadow as
accepted sparse storage. Broader mappings need separate compatibility contracts.

Keep the request's actual daemon arguments and environment intact. Report
`training_config_equivalent=false` and separate `input_run_id` from
`execution_run_id`; daemon completion must not increment original-plan completed
counts or mutate the original v8 run. Require explicit owner selection of an
experiment profile for any second execution of the same input batch. Do not
present a different daemon objective as execution of the original plan.

Reopening reconstructs existing `OwnedInvocationControl` assignments after fresh
checks. Its existing submit/read/resolve and execution behavior remain unchanged.
No new transport command or callable-from-wire callback is needed for route A.

## Recommended route B: prepared requests for the original v8 jobs

Stage B1 is implemented in `optimizers/logic_theorem_optimizer/autoencoder_campaign_owned_training.py`
with the separate `autoencoder_campaign_training_request.py` codec. Its bounded
offline regression capture passed; preparation and inspection remain metadata-only:

```python
prepare_campaign_training(registry, plan_artifact, *, selected_batch_ids,
    worker_id, output_root, resource_policy, execution_policy) -> prepared
inspect_campaign_training(registry, request_artifact) -> report
```

`selected_batch_ids` is explicit, ordered as the sealed plan and bounded to 64.
Reconstruct the entire plan through `build_campaign_plan`/`_capture` metadata and
checkpoint inventory, comparing exact canonical bytes before preparing a subset.
Do not use `_inspect` here: it replays completed candidates and can load weights.
Select only pristine queued runs with no attempt, lease, result or output;
other statuses are observed metadata, never verified completion. B2 uses normal
inspection and completion replay after resource admission. Original jobs, run
IDs, output paths, configuration and base versions stay byte-for-byte unchanged. Each new
request binds the plan/batch, exact job descriptor and canonical digest, owner
paths, variant/root binding, target and Arrow descriptors, sparse owner policy,
resource policy and exact runtime controls. Defaults stay unchanged, including
Python execution, no-memory evaluation and each job's bridge/prover settings.
Reject unsupported settings instead of rewriting them. V8 corpus vectors remain
inline; Arrow feature weights do not imply mapped multi-receipt embedding inputs.

Preparation verifies bytes, membership and checkpoint inventory without loading
weights, hydrating targets or claiming native compatibility. It seals control
artifacts and a separate journal directory, never the worker's output directory.
No `CreateRun` is needed: the original registered v8 run is the execution run.
The returned handle contains the request descriptor, journal path and exact
registration receipt. Inspection reports observed status and pristine eligibility
with `execution_available=false`, `capacity_admitted=false` and
`completion_verified=false` for every selected job. Existing-only journal opens
prevent inspection or retries from silently recreating missing history.

Stage B2 now supplies an owner-only execution entry point:

```python
execute_prepared_campaign_training(registry, prepared_artifact, *,
    max_new_batches, max_workers) -> report
```

Reuse the original worker/coordinator verification and completion logic.
`run_training_jobs` needs an explicit persistent operation journal and controlled
native launch integration, preserving its existing default behavior. Do not pass
an arbitrary executor factory and call the result native: the current API marks
such calls `injected_test`. Factor the existing native launch boundary narrowly;
native identity must be independently established and all injected test hooks
must retain `injected_test`. The native child must install the same offline
network denial as the owned daemon before package imports; this is a requirement,
not an existing guarantee of direct worker spawn. Install the canonical
workspace import path before any `ipfs_datasets_py` import, then enforce
[`require_workspace_logic_tree()`](../../../ipfs_datasets_py/logic/autoformal/tree_pin.py)
before worker execution. Importing HACC first cannot be repaired by subsequently
changing the path. Do not copy a second
receipt/replay implementation into the adapter.

Stage B3 adds a typed sibling owner controller and explicit gateway profile for
v8 training requests. Preserve the three bounded submit/read/resolve operations;
remote callers still provide no paths, arguments, policies, leases or results.
Keep the existing daemon profile and strict controller type checks intact.
Owner drains run outside the gateway pump; no listener is part of B1/B2 tests.
Use a separate campaign controller: one prepared request can contain multiple
original runs, and B2 can return partial `ready` progress. Cap the union of
assigned original runs, and initially drain requests sequentially while B2
provides parallelism within a request. A durable drain start without a finish
must remain `recovery_required`; calling B2 again could train an untouched next
batch. Continue only through an explicit new owner drain after the previous
finish is recorded. Status reads should use durable control/registry history,
not contend for the execution journal while a drain holds it.

## Identity, restart and resource rules for route B

Use canonical request content identities and deterministic operation IDs derived
from immutable owner/request/run bindings. Persist each exact operation payload
before its mutation and resolve response loss with that same identity. Reuse the
existing operation table and durable journal conventions; no schema migration
or parallel mutable queue is necessary.

Bind one selected owner request to each original run with a deterministic
operation-table key. Preflight all identities and output/journal paths before
the first mutation; register a bounded assignment set atomically. The binding
must exclude conflicting assignments from overlapping plan pages. Resource or
policy changes require an explicit new contract and cannot replace a started
assignment. Do not reset attempts, fences, leases or historical results.

Record the start intent and exact request/lease tuple
(`run_id`, `worker_id`, `owner_generation`, `attempt`, `fence`, expiry) before
spawning. Start the child behind an execution handshake, persist its observed
PID, process-group and birth identities, then release it to compute. Loss of
the handshake or owner connection must cause the waiting child to exit; no
gap authorizes an automatic second computation. Recovery must verify process
birth identity before acting on a PID. Reopening the owner invalidates earlier
owner-generation leases; it never authorizes implicit adoption, reclaim or retry.
A completed registry operation can be
reconciled after reply loss without another worker. An uncertain start or absent
terminal receipt requires explicit recovery. Fresh dispatch must recheck the
plan and job status; a registry fence rejects competing or stale completion.
Final plan completion continues to use `get_run_completion` plus current worker
receipt and candidate replay, not a control status flag or request acceptance.

Use the existing [resource reservation](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py)
before claims or child startup. Account for full outstanding reservations plus
observed named-root growth, journals, candidate copies, patches and compaction.
Retained failures never expire automatically. Cap simultaneous workers at the
admitted CPU/RAM/process capacity, initially at most four, with existing tighter
policy bounds preserved. Do not multiply nested pools beyond the reservation.

The current coordinator's cooperative `max_seconds` and pool shutdown are not a
hard deadline. B2 requires tracked isolated child groups and bounded supervisor
actions and termination attempts. Uninterruptible native or kernel I/O may still
prevent reaping: never claim successful cleanup, release or completion without
confirmed dead children and durable artifacts. Retain the claim and report
`recovery_required` otherwise. Keep lease renewal alive during receipt/replay
work and preserve exact pending completion before any failure transition.

## Acceptance and cost

New offline tests should cover exact plan/job/request identity, original bytes,
both-role checks before selected reads, wrong owner/base/target/Arrow descriptors,
and an invalid last member rejected before mutation. Include same-owner repeat,
reopen, overlapping pages, conflicting assignment, partial response loss,
missing/replaced journals, source/leaf mutation, policy drift, stale fences,
uncertain start and committed completion recovered without worker reexecution.

Injected end-to-end cases must retain actual target codecs, sparse patch replay,
compaction and optional Arrow transport, with unchanged original-plan completion
criteria. Include independent same-base branches and one failing worker without
head promotion or sibling cancellation. These establish isolation, not throughput.
Gateway fixtures must reject generic mutation bypass and foreign scopes. Quota
denial must occur before claim/start. If reaping or an owner mutation cannot be
confirmed, retain the unresolved lease/claim state and report recovery; do not
claim successful release or accept a new candidate. Interrupted completion stays
unresolved until its exact durable operation is reconciled.

Keep whole-package, dependency, harness and protected-artifact guards around
every admitted qualification capture and independent closeout. Narrow runtime
helper hashes do not replace that whole-producer boundary. Preserve failed
receipts and stop qualification when current source differs. No native run or
live-listener test is implicitly authorized by implementing these adapters.

Engineering sizing estimates, not measured runtime or delivery commitments:
route A is roughly 1–2 engineer-days plus qualification; B1 is 2–3 days; B2 is
3–5 days because journal recovery and child supervision interact; B3 is 1–2
days after B2. Route A's lower cost buys provenance and control access but no
equivalent worker execution, and can divert effort from shared-target/sparse
efficiency. B1/B2 address that objective directly. The initial synthetic test
proposal is 50 MB total: 30 MB charged fixtures plus 20 MB owned outputs.
Global capacity must allow the full 50 MB reservation plus 50 MB expected growth
and a positive margin, beyond existing observations and retained claims. This
needs over 100 MB of headroom beyond removal of the current 67.3 MB deficit.
These estimates do not override admission or predict parallel memory use.

Measure full jobs at one admitted worker before increasing parallelism. Attribute
target construction, hydration, projection, replay/compaction and CAS time
separately; preserve bridge names, prover/cache flags and sample counts. Keep
Arrow opt-in until complete-job measurements justify it. Neither route changes
parser trees, context limits, temperature, training objectives or legal success.

## Remaining end-to-end sequence

1. Extend sealed source receipts and shared-target coverage in bounded revisions.
   Deliver exact per-input embedded/gap/protected dispositions and target
   membership, not a claim that all federal provisions have usable vectors.
2. Build on the offline-qualified B1 with journaled, resource-supervised B2/B3 for exact original v8
   jobs. Deliver immutable requests, restart evidence and isolated candidate
   versions; native and parallel-throughput qualification remain deferred.
3. Once native validation resumes and capacity admits it, measure paired cold
   and warm complete jobs on one worker, then bounded parallel workers. Deliver
   separate time/memory/bytes and held-out learning reports with unchanged
   bridge/prover/cache/sample settings; an in-sample gain is not that canary.
4. Expand supported legal semantic families and review unresolved provisions.
   Deliver span-to-rule provenance and actual Lake receipts per admitted item;
   track coverage denominators separately for US Code and the Constitution.
5. Materialize versioned corpus, model and proof history through the existing
   owner/outbox-to-DuckLake path, with restart and snapshot reconciliation.
   A DuckLake row remains a record of evidence, never proof authority.
6. Seal dataset/model delivery packages with complete declared dependencies,
   licensing, private/public scope and verification levels. Resolve executable
   import and full-source packaging separately from selected-page evidence.
   Prepare a reviewable Hugging Face delivery through existing infrastructure;
   no upload or credentials use is part of this design. There is no ETA for
   complete faithful federal-law formalization.
