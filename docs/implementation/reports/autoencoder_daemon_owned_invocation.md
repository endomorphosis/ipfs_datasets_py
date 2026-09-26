# Owner-leased native daemon invocation

Status, 2026-09-25: **implemented; native owner lifecycle qualified for the exact
six-record, zero-update slice**. The
adapter connects one actual U.S. Code daemon invocation to an existing registry
owner, with a live lease, private attempt directory, durable operation journal
and independent verification of its full final checkpoint. The guarded combined
regression passes 635 checks; a guarded follow-up after the lane correction
passes 140. The first native qualification attempt stopped before input export
or daemon execution; r2 passed after correcting that integration error. The
native run verifies this bounded ownership lifecycle, not changed-state learning,
general held-out/canary qualification, head promotion, publication or admission.

## Implemented authority boundary

The [owner adapter](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_invocation.py#L151)
exposes:

```python
prepare_daemon_invocation(
    registry, *, run_id, variant_id, base_version_id, input_snapshot,
    daemon_argv, output_directory, resource_policy, environment_overrides=None,
) -> prepared

run_owned_daemon_invocation(
    registry, prepared, *, lease_seconds=300, timeout_seconds=900,
) -> completion
```

Preparation checks the registered base and variant, the input capsule's owner
CAS location and registered input anchor, and the actual parser's effective
arguments under the sealed environment. It stages a separate immutable daemon
request and creates a distinct execution run. The input-anchor run is not used
as execution authority. The prepared handle binds the request, journal path
and run/variant/base identity.

Execution claims a lease before copying the base or starting the daemon. It
records an exclusive attempt directory and launch descriptor, then runs the
real `uscode_modal_daemon_runner.main(argv)` in a separate process. The same argv
and sealed environment are checked again in the child; ordinary relative daemon
output paths resolve under that private working directory. The child does not
open the registry database. The owner renews while supervising computation,
staging and independent verification, with registry commands serialized on the
owner thread. File staging can run separately without sharing the DuckDB
connection.

Only after successful cleanup, exactly one cycle and durable writer/snapshot
drain does the owner stage the final checkpoint and invoke a separate verifier
process. It stages the launch, native receipt, verifier receipt, raw summary and
cycle log as immutable evidence before calling the existing `CompleteRun`.
Completion creates a version parented to the registered base; it does not call
`promote_head`. Results explicitly retain `admitted=false`, `promoted=false`
and `publication_performed=false`.

`CompleteRun` provides staged-byte and exact-live-lease checks; the
[worker verifier](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_invocation_worker.py#L328)
adds daemon checkpoint semantics. Registration does not authenticate arbitrary
issuers or prove native computation by replay. Input descriptors require a
trusted local handoff.

## Native execution, state and evidence

The owner launches the worker by its absolute script path. Its
[bootstrap](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_invocation_worker.py#L29)
installs Linux seccomp network denial before importing package ancestors and
checks socket denial. Compatibility invocation through `python -m` does not
establish that same pre-import ordering. Offline environment settings prohibit
automatic model downloads; no loader, evaluator or trainer replacement is
installed by the production worker.

The default-off
[observation context](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_observation.py#L137)
records native state identities, revisions and component digests without cloning
weights. The [runner](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/uscode_modal_daemon_runner.py#L19407)
observes the loaded base, startup completion, actual evaluation/projection
boundaries, completed cycle after all mutations, and final shutdown state after
durable persistence. It records ordered selected indices, record IDs and sample
IDs. Checkpoint metadata binds `daemon_invocation.request_sha256` and
`daemon_invocation.launch_sha256`. The context grants no lease authority and
marks success only after actual main returns successfully and context cleanup
completes. Exceptions retain partial observations without suppressing the
primary error.

The independent verifier loads the registered full base and staged full compact
float64 candidate with recovery disabled. It reconciles exact bytes, metadata,
source/input bindings, ordered selection, default and metric-lineage state
identities, revision, final writer checksum and clean shutdown. It reconstructs
the base and final state only: intermediate observations are bound execution
facts, not replayed computations. Async evaluation matches the candidate only
when its complete state/compiler/holdout/schema lineage agrees with the final
state. Otherwise the candidate remains explicitly unevaluated, without granting
promotion authority. Projection patches cannot substitute for the full final
state, which also includes startup, supervisor and compaction effects.

Actual synchronous training evaluations request `use_sample_memory=True`;
validation evaluations request `False`. Optional diagnostic passes retain their
own recorded flags. The projection report's `sample_memory_used` is a separate
fact and does not establish the policy or hits of every evaluation. Receipts
record observed per-pass policy, relevant requested arguments and the projection
flag; memory-hit counts remain unknown. Internal snapshot/trainer passes are
not expanded into that observation list. `daemon_seconds_including_shutdown`
measures actual main through cleanup; `elapsed_seconds` measures the worker
through receipt preparation. Overlapping async phases must not be added as
disjoint wall time.

## Configuration, restart and resource limits

The [closed contract](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_invocation_contracts.py#L182)
binds actual daemon arguments, not worker `TrainingConfig`. Currently supported
execution requires the autoencoder role, explicit `max_cycles=1`, Python CPU
backend, verified local v6 corpus inputs and zero indexed canaries. External
bridge provers are disabled; worker count must match the sealed environment.
Warm-start state/run IDs and canonical warm starts are explicitly refused until
their dependency closure is bound. External guidance paths, guidance projection
or training, external guidance waits, non-packet executor mode and commit mode
other than `none` are also refused. Internal TODO/projection settings, sampling,
caps, optimizer policy, compaction, cache and async settings are retained rather
than silently rewritten. Full legacy JSON and full compact bases are supported;
sparse bases and noncompact final candidates are refused.

The [operation journal](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_operation_journal.py#L202)
durably records each exact operation ID, command and payload before submission.
Restart resolves a pending completion first. Historical completion remains a
historical fact and explicitly does not imply current artifact availability.
An uncommitted old attempt is quarantined, never attached to a fresh lease.
Renewal and completion are serialized because renewal changes the exact lease
payload. Expiry or unresolved authority prevents completion; existing local
async writes may still drain into the isolated attempt and are not claimed to
have been rolled back.

The [resource reservation](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py#L163)
checks explicit memory, CPU and storage reservations, named-root disk use, child
process-group RSS and invocation deadlines. Storage includes retained attempts,
temporary/CAS copies and diagnostics within the existing **50,000,000,000-byte**
campaign budget. Insufficient capacity prevents launch; failed attempts retain
accounting. No unowned artifact is automatically removed and no concurrency or
quota increase is implied. Source and input checks establish integrity at the
checked boundaries, not proof against a transient mutate-and-revert event.
The resource wrapper now records workload `canonical_trainer` and scheduler lane
`HAMMER_LEAN`, matching the existing
[pipeline mapping](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/pipeline_stage_scheduler.py#L486)
and [hyperparameter admission policy](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_ir_hparam_scheduler.py#L1489).
This corrects the wrapper's former use of the unprovisioned `TRAINER` lane;
the scheduler's 20-slot capacity and lane reservations are unchanged. RSS and
disk checks are cooperative polling observations, not kernel-enforced quotas.

## Validation and native qualification

| Evidence | Result | Scope |
| --- | --- | --- |
| [Focused observation receipt](../../../workspace/test-logs/federal-corpus-audits/daemon-owned-observation-20260925/focused-r2-receipt.json) | 24 passed, 5.70 s | Earlier synthetic observer/runner wiring and native checkpoint codec; no native training or lease qualification. |
| [Focused worker/memory receipt](../../../workspace/test-logs/federal-corpus-audits/daemon-owned-observation-20260925/worker-memory-focused-r2-receipt.json) | 31 passed, 6.56 s | Synthetic worker/runner integration, actual checkpoint codec and direct-script seccomp failure path, including actual per-pass memory metadata. |
| [Guarded combined receipt](../../../workspace/test-logs/federal-corpus-audits/daemon-owned-invocation-20260925/combined-r1-receipt.json) and [log](../../../workspace/test-logs/federal-corpus-audits/daemon-owned-invocation-20260925/combined-r1.log) | 635 passed, 97.88 s pytest / 100.314 s wrapper | Owner, contracts, journal, resources, observation, worker, registry, input, checkpoint, writer, shared-target/report integrations and 31 semantic gate/pilot checks. All 7,729 package files unchanged. |
| [Native owner attempt r1](evidence/autoencoder_control_plane_plan/owned-daemon-invocation-native-20260925-r1.json) | Failed resource preflight, 2.399 s total | No trainer CPU capacity; stopped before input export, new base creation or actual main. No candidate was produced. |
| [Guarded lane-correction receipt](../../../workspace/test-logs/federal-corpus-audits/daemon-owned-invocation-20260925/lane-fix-r1-receipt.json) and [log](../../../workspace/test-logs/federal-corpus-audits/daemon-owned-invocation-20260925/lane-fix-r1.log) | 140 passed, 39.49 s pytest / 42.115 s wrapper | Resource, owner, qualification harness and semantic gate/pilot checks. Sources unchanged during tests; the resources module is the only production change from the 635-check capture. |
| [Native owner attempt r2](evidence/autoencoder_control_plane_plan/owned-daemon-invocation-native-20260925-r2.json) | Passed, 191.251 s total qualification | Actual owner-leased main, staged full-checkpoint verification, durable completion and identical restart replay; exact six-record, zero-update scope. |

The test sets overlap and must not be summed. Each test receipt names its command
and captured sources; the combined source inventory is retained in
[its sidecar](../../../workspace/test-logs/federal-corpus-audits/daemon-owned-invocation-20260925/combined-r1-source.json).
No native speed claim follows from these tests or the single native qualification.

The native attempt's `ResourceUnavailableError` reports that its one-slot trainer
request exceeds the capacity available to that lane. The recorded scheduler has
20 total CPU slots and reservations totaling 20 for other lanes, leaving none
for this request. The attempt preserves the failed receipt, unchanged package
sources, protected checkpoint and environment, with no automatic retry or
weakened resource guard. Historical-input verification had not been reached;
its false result flag is not evidence of an observed input mutation. This is
preflight failure evidence, not a completed owner invocation.

Investigation identified the incorrect wrapper lane selection, rather than a
need to raise global capacity. After the correction and guarded follow-up tests,
native attempt r2 passed with the existing scheduler policy and unchanged limits.
The r1 failure remains retained; the correction did not change global scheduler
capacity or bypass resource admission.

## Native r2 scope and measurements

The [r2 receipt](evidence/autoencoder_control_plane_plan/owned-daemon-invocation-native-20260925-r2.json)
has SHA-256 `0c7b84a8cd11dc9f181c68d2124786b020edaff990a5565dfa3e54c8fdc7863f`.
Actual main consumed the frozen three training and three validation records,
with verified v6 list vectors and unchanged source/input/protected-checkpoint
guards. All four before/after optimizer evaluations retained three targets.
The five requested metric/diagnostic bridges were `modal_frame_logic`,
`deontic_norms`, `fol_tdfol`, `cec_dcec` and `external_prover_router`, with bridge
provers false, metric disk cache zero, one bridge worker and full selected text.
The one-epoch, one-family, one-line-search projection accepted zero epochs; the
supervisor applied zero updates. Observed base, startup, completed-cycle and
final logical identities remained equal at revision zero.

The full compact candidate is **1,664,643 bytes**, SHA-256
`dc133884a94e6a10cbbab41a9b9293428f970f668b392ffaa144dfa8932a45f6`.
The independent verifier child reconstructed the registered base and staged
candidate, reconciled the final receipt and input closure, and found the final
async evaluation lineage matched. Owner completion created one candidate
version/event parented to the registered base. After owner restart, replay
returned the identical completion; candidate bytes, version/event counts and
the private head were unchanged. Raw summary, log, launch and both worker
receipts are retained in CAS.

The separate [read-only post-run audit](evidence/autoencoder_control_plane_plan/owned-daemon-invocation-native-20260925-r2-independent-audit.json)
also passed. It independently decoded the base and final checkpoint, compared
their complete canonical state and all 38 component digests, checked 40 artifact
descriptors, and reconciled all six journal operations against the DuckDB ledger.
It verified two versions (base and candidate), exactly one candidate event, an
unchanged head and unchanged database bytes after its read-only inspection.
Package sources matched the guarded follow-up tests before and after the audit.
This audit did not rerun training, bridge evaluation or intermediate computation;
historical completion is not a claim of a currently live lease.

| Measurement | Seconds | Scope |
| --- | ---: | --- |
| Input export | 5.075540 | Historical closure verification and private owner input setup. |
| Owner preparation | 15.020175 | Effective configuration, source/base checks and immutable request/run setup. |
| Owner execution | 168.507620 | Lease supervision, actual execution, staging, independent verification and completion. |
| Execute child | 143.544584 | Native worker receipt timer; includes guards around actual main. |
| Actual daemon main | 135.479983 | Includes native shutdown and drain. |
| Independent verifier child | 7.563710 | Separate native candidate/base verification. |
| Complete qualification | 191.251031 | Harness wall time, including setup and restart checks. |
| Before-training full-family evaluator | 28.615178 | Actual evaluator call with bridges and three targets; **9.538393 s/span**, not an isolated adapter timer. |
| Projection report | 2.620000 | Native trainer-reported elapsed time; surrounding projection phase is 2.686 s. |
| Async snapshot evaluation | 45.913635 | Overlaps daemon execution; do not add to main as separate wall time. |

These scopes overlap. Cycle phase timers also include heartbeat/persistence
overhead: before-training is 28.617 s, before-validation 27.937 s, after-training
2.025 s and after-validation 2.434 s. They are not isolated bridge timings or
additive owner overhead. Training evaluations requested sample memory true;
validation evaluations false; projection reported false. Memory-hit counts were
not inferred. Processes and attempt storage were fresh. The existing pretrained
base was loaded, ordinary in-process caches warmed during execution, and OS
cache state was uncontrolled. This is not an all-cold workload or a cold/warm
speed comparison.

Owner execution includes 33.028 seconds outside actual main on this run. That
difference includes worker startup, surrounding integrity checks, CAS staging,
independent verification and completion; it is not an isolated measurement of
lease overhead. The extra work establishes complete-state and restart evidence.
It also creates a measurable cost to reduce through verified reuse and, later,
resident workers. Changing the final representation to sparse updates must first
replay every state field against this full-checkpoint reference. Mapping more
weights should follow measured copy pressure and asynchronous reader-lifetime
checks; this run supplies no new Arrow speed result.

Default asynchronous snapshots remained enabled. Snapshot diagnostics can
include local tableaux and compile-only routing despite bridge provers being
false; they do not establish a theorem or admission count. No registry head
promotion or external publication occurred. Global holdout, semantic duplicate
isolation, broad canary qualification and native changed-state capture remain
unqualified by this run.

The earlier [native input-cycle receipt](evidence/autoencoder_control_plane_plan/daemon-corpus-input-native-cycle-20260925-r1.json)
and [independent full-state audit](evidence/autoencoder_control_plane_plan/daemon-corpus-input-native-cycle-independent-audit-20260925-r1.json)
qualified an unleased input invocation: three training and three validation
records, zero accepted projection epochs, and unchanged final logical state.
They do not qualify this new owner boundary; r2 now supplies the separate bounded
owner lifecycle evidence. Native changed-state capture and learning still need
separate evidence because r2 also accepted no update.

The subsequent [offline sparse-shadow report](autoencoder_daemon_sparse_shadow.md)
now verifies all 38 fields for this unchanged candidate and a separate archived
six-scalar update. It compares complete endpoints without changing owner
acceptance or replaying intermediate mutations. The later
[owner-bound shadow slice](autoencoder_daemon_owned_shadow.md) seals an optional
v2 request and stages exact shadow evidence with the full candidate. Its real
description/verifier qualification surrounds a synthetic execute fixture;
zero accepted optimizer epochs and an explicitly unevaluated candidate do not
extend the native learning evidence above. The
[implementation plan](../plans/AUTOENCODER_DAEMON_OWNED_INVOCATION_PLAN.md)
keeps full checkpoints authoritative until native changed-state, recovery and
sparse authority are qualified, followed by mapped storage only after
asynchronous lifetime and equivalence checks. Resident warm-cache execution, corpus-scale inventory,
held-out qualification, DuckLake destination consumers and HF publication remain
separate work. The Constitution remains unformalized; no HACC work or model
weight downloads are included. Only `lake build <Lib>` is an admit.
