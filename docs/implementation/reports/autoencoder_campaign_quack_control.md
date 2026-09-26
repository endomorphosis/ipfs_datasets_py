# Quack control for prepared autoencoder campaign jobs

Implemented and qualified in 208 guarded offline cases, 2026-09-26. This extends
the [owned execution path](autoencoder_campaign_owned_execution.md) to the
existing explicit Quack prototype. It does not start a listener on import or
change the existing daemon control profile.

## Ownership and data movement

The owner supplies a closed set of prepared campaign requests. Each request
already binds the original jobs, model variant and language, base checkpoint,
corpus roles, full shared targets, optional Arrow feature weights and sparse
update policy. A remote caller can submit, read or resolve a submission using
only its immutable request descriptor. It cannot supply training arguments,
local paths, leases, candidate results or a different bridge configuration.

The gateway records or reads control history. An explicit owner drain calls
the existing B2 execution path outside the gateway pump. Requests drain
sequentially, while B2 provides bounded parallel workers within each request.
The existing registry remains the single writer for leases and completion.
Workers keep numeric weight access local and return accepted sparse updates
through the existing verification path. No parameter is fetched through Quack
inside a training step.

Status polling reads durable control and registry history without opening the
worker execution journal or loading checkpoints. One bounded query fetches the
known drain-phase keys, and each completed candidate is checked at most once
within that history read. No cached result survives to the next poll. The reused
registry completion verifier still queries its operation and event history for
each completed run; that cost remains part of end-to-end polling. Recorded completion describes
the observed execution; it does not revalidate current artifact availability.
A submitted request is not a completed model, and a completed model is not a
formalized law.

## Explicit owner interface

```python
from ipfs_datasets_py.duckdb_control.autoencoder_campaign_control import OwnedCampaignControl
from ipfs_datasets_py.duckdb_control.autoencoder_quack import RegistryQuackGateway, WorkerScope

ref = prepared["request_artifact"]
control = OwnedCampaignControl(
    registry, worker_id="campaign-owner",
    prepared_campaigns={ref["sha256"]: prepared},
)
gateway = RegistryQuackGateway(
    registry, WorkerScope(control.worker_id, control.run_ids),
    enable_prototype=True, campaign_control=control,
)
```

The worker ID must match the sealed preparation. Construction starts no listener
or training. The existing transport client uses `request(command, payload,
operation_id)` with payload `{"request_artifact": ref}` for
`SubmitCampaignTraining`, `ReadCampaignTraining` and `ResolveCampaignTraining`.
Endpoint startup remains an explicit owner action under the prototype policy.

After submission, owner code calls
`control.execute_pending(max_new_batches=1, max_workers=1)` outside the gateway
pump. `max_new_batches` bounds the total new-batch budget across that call, not
a separate allowance for every request. `max_workers` cannot exceed the sealed
request policy. At most one B2 invocation is made per request in a drain.

## Retry and partial progress

A request may contain more jobs than one bounded owner drain starts. The owner
records each drain before execution and its result afterward. A recorded
partial result can be continued by a later explicit drain. A start without a
confirmed finish requires recovery: automatically invoking B2 again could
train another untouched batch even when an earlier batch finished successfully.
Submission retries resolve the same durable operation and cannot create a
second assignment for an original run. Completion references contain hashes
of the exact registry receipts. Before any worker starts, the controller checks
that a worst-case finish for the assigned runs fits the registry command bound.
Closing the controller and starting a drain are serialized by the same lock.

## Cost and remaining validation

| Choice | Benefit | Cost or limit |
|---|---|---|
| Descriptor-only remote commands | Avoid weight copies and mutable parameter writes through Quack | Owner must stage and validate the complete request first |
| One registry writer | Keeps workers away from competing DuckDB writers | Owner completion and compaction can become bottlenecks |
| Local Arrow views | Reuse existing mapped feature weights during worker execution | Does not make every model tensor or intermediate zero-copy |
| Accepted sparse updates | Reduce repeated full-state transfer where patches are small | Replay and eventual compaction still consume CPU, memory and I/O |
| Durable drain records | Prevent ambiguous retries from duplicating computation | Adds bounded control writes and explicit recovery for incomplete history |
| Sequential request drains | Avoid nested pools and uncontrolled resource multiplication | Independent requests wait; parallelism initially comes from jobs within a request |

The interface alone establishes no training speedup. Native checkpoint and
listener validation remain deferred. Future measurements must compare complete
jobs with the same source, checkpoint, bridge names, prover/cache flags, worker
count and sample count; legal-IR evaluation must have nonzero targets. Report
target construction, local projection, patch replay, compaction and control
time separately before increasing concurrency or changing a backend.

DuckLake materialization and Hugging Face delivery remain separate existing
owner/outbox workflows. This controller does not publish model heads or upload
artifacts. Only `lake build <Lib>` supplies a Lean admit. The Constitution
remains unformalized.

## Qualification scope

The corrected capture passed all 208 cases with zero failures, errors or skips:
the original 207 plus the existing
canonical identity test for the authorized 24-hour deadline. That test requires
the exact gold-supported deadline addition, the other four historical case
identities, and the unchanged executive-order historical identity after removing
only that addition. The three legal gates, empty-vocabulary abstention and typed
pilot thresholds remain selected. Passing transport tests alone is insufficient.

The [test receipt](evidence/autoencoder_control_plane_plan/campaign-quack-control-tests-20260926-r1.json)
records 199.271 seconds of test wall time. The complete
[audit](evidence/autoencoder_control_plane_plan/campaign-quack-control-audit-20260926-r1.json)
took 288.851 seconds, including the source-stability window and resource checks.
These are offline validation durations, not legal-IR or training speed results.
All 7,778 package files and 1,299 dependency entries stayed unchanged across
parent and child snapshots. The final
[source](evidence/autoencoder_control_plane_plan/campaign-quack-control-sources-20260926-r1.json)
and [dependency](evidence/autoencoder_control_plane_plan/campaign-quack-control-dependencies-20260926-r1.json)
maps preserve the exact observed context. Harness, protected artifacts, input
evidence, produced evidence and retained claims also passed their guards.

The fresh 100 MB reservation `c957da8125f246d99209af4935be9d61` and host lease
were [released](evidence/autoencoder_control_plane_plan/campaign-quack-control-release-20260926-r1.json)
after zero live owned processes were confirmed. The 80 MB external fixture
allowance stayed within that reservation. Both earlier failed reservations
remain retained. The campaign cap remains 60 GB; no per-worker bound changed.

The capture also records an unrelated between-attempt edit to
`logic/autoformal/entity_cache.py`. That module is unexecuted context, with an
explicit assertion that the tests do not import it. It is outside this B3
publication and carries no feature qualification. Whole-package source and
dependency checks still apply before and after the fresh capture; the old failed
captures retain their original identities.

## Retained first capture

The first capture ran all 207 selected cases: 203 passed and four failed. Three
new daemon-profile fixtures used a nonexistent `TrainingJobSpec.variant_id`
attribute; the correction reads the actual registered variant. The injected
B2 fixture stopped during setup when `platform.platform()` tried to spawn
`uname`, which its no-process guard correctly rejected. That fixture now uses
an explicit synthetic platform label consistently during target construction
and consumption. Its process, network and native-resource guards remain intact.
The real B2 path had not yet been reached by that failed integration case.

Production source was unchanged by these fixture corrections. The
[failed test receipt](evidence/autoencoder_control_plane_plan/campaign-quack-control-failed-tests-20260926-r1.json)
and [failed audit](evidence/autoencoder_control_plane_plan/campaign-quack-control-failed-audit-20260926-r1.json)
remain separate evidence, together with the original
[controller test](evidence/autoencoder_control_plane_plan/campaign-quack-control-failed-control-test-20260926-r1.py)
and [gateway test](evidence/autoencoder_control_plane_plan/campaign-quack-control-failed-gateway-test-20260926-r1.py).
The source, dependency, harness and protected-input guards held; this was a test
failure, not a source-drift rejection. Reservation
`af51e1abd59442fb8fd55a61781b5961` remains retained. The later successful capture
above is separate evidence and does not relabel this failure.

The second capture passed 197 of 207 cases. All new controller, gateway and wire
cases passed, including the actual injected B2 path. Ten existing B2 cases then
failed because the synthetic platform label remained in the producer's resident
context after the platform fixture ended. The producer correctly rejected the
changed runtime identity. The corrected fixture restores both values at the
integration boundary and asserts that their original identities are restored.
It also changes the runtime label within the operation and asserts that the
producer still rejects drift without replacing its fingerprint. This is test
isolation, not a production provenance exception.

The second [failed test receipt](evidence/autoencoder_control_plane_plan/campaign-quack-control-isolation-failed-tests-20260926-r1.json)
and [failed audit](evidence/autoencoder_control_plane_plan/campaign-quack-control-isolation-failed-audit-20260926-r1.json),
with the [prior controller fixture](evidence/autoencoder_control_plane_plan/campaign-quack-control-isolation-failed-control-test-20260926-r1.py),
remain separate evidence. Its test receipt records unchanged source,
dependency, harness and protected-input checks; its overall qualification failed.
Reservation `af5bab36df5a4c59a9b6a52867d09b81` remains retained. Neither failed
capture is a speed measurement or successful qualification.
