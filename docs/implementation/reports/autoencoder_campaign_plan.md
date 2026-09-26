# Immutable campaign plans and restart inspection

Implemented and qualified offline: 375 tests, an archived six-record plan and
restart probe, and all 57 closeout checks passed on the same guarded revision.
This establishes campaign orchestration contracts, not completed end-to-end
training or improved model quality. Native validation remains deferred.

The immutable campaign plan connects already registered v8 batches to the
existing DuckDB owner and training coordinator. It records their order, exact
job artifacts and canonical digests, shared campaign roots, model variant,
ordered training/validation IDs, target and Arrow artifact descriptors, and
configuration digests. Its parent policy either requires one common fixed
base or binds explicitly registered parent versions for each job. It never
selects the latest head or predicts an unregistered future candidate. The plan
lives in the existing content-addressed artifact store; the existing registry
run records remain the execution authority. No SQL migration or second queue
was added.

The closed canonical JSON format permits up to 128 batches, 32,768 projected
record occurrences, 64 MiB of aggregate job JSON and a 4 MiB plan. Each batch
retains the existing limit of 256 projected records and the cycle's 128 training
feedback records. Repeated training IDs are rejected within this one-pass plan;
shared validation IDs may repeat, with unique and occurrence counts recorded
separately. Coverage includes the frozen declared-source partition and embedding
status denominators. These counts do not establish complete or authoritative
federal-law coverage.

`AutoencoderRegistry.get_run_completion()` resolves durable completed work after
restart. It checks the original completion operation and payload digest, the
retained historical lease, candidate content identity and lineage, exact result
metadata, and durable event. Historical leases need not remain live. A completed
row or a manually registered version alone cannot satisfy this lookup. The
method reads registry history; current artifact verification remains separate.

The plan inspector independently checks all registered jobs before dispatching
any of them. Completed jobs also require the retained CAS worker receipt and
current checkpoint evidence. Receipt binding checks reuse the coordinator's
existing validator. Accepted patches are replayed against their exact bound
base; their provenance, capture contexts and order must agree. Sparse worker
manifests must match their authorized parent and patches, including when the
owner compacted the result into a full checkpoint. Compaction policy, reasons,
storage closure and lease assignment must match the recorded result. Inspection
performs no model inference, optimization, artifact staging or run mutation.

`run_campaign_plan()` dispatches only the requested ordered slice of untouched
queued jobs through `run_training_jobs()`. It skips completed work only after
the checks above. An existing running, failed or ambiguous attempt leaves the
plan unresolved and dispatches nothing. This supports restart between batches,
including completion committed before an outer campaign receipt was saved.
It does not retry interrupted computation. Candidate heads and publication
remain unchanged. Caller-owned resource admission and process supervision are
still required; worker count is not resource approval.

For an existing owner and already registered v8 jobs, the local API is:

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_campaign_plan import (
    seal_campaign_plan, inspect_campaign_plan,
)

plan_artifact = seal_campaign_plan(owner, ["registered-run-a", "registered-run-b"])
status = inspect_campaign_plan(owner, plan_artifact)
```

Persist the returned descriptor and use the pinned workspace tree. Dispatch is
a separate explicit call inside the existing resource/supervision boundary;
sealing or inspection starts no workers. Existing job IDs remain bound to their
persisted attempts rather than being regenerated from the plan digest.

This first scheduler deliberately pays for fresh verification of every planned
job on inspection, plus another reconciliation after dispatch. Completion
lookup also searches existing operation receipts. Those costs grow with plan
width and registry history. The immediate benefit is durable recovery without
repeating completed optimization or sharing mutable worker weights. It is not
a measured training speedup. Later amortization should retain exact root,
job, role and current-byte bindings; a reusable verified context or indexed
completion lookup needs its own profile and qualification. The previous
preparation measurements cannot be treated as this scheduler's throughput.

The offline audit covers the new campaign-plan and run-completion tests together
with the existing registry, campaign coordinator and general coordinator tests.
The artifact probe uses the six-record job from the passed
[campaign workflow capture](autoencoder_campaign_workflow.md). It verifies and
stages the exact archived source inputs and vectors into an isolated registry,
registers one queued v8 job with an explicitly created empty legacy checkpoint
fixture (`{}\n`, three bytes), seals a one-batch plan,
and inspects it before and after reopening the registry. The ordered plan,
queued run, checkpoint head and stored input bytes must remain exact. The probe
does not reuse the archived opaque base: the new plan correctly requires a
checkpoint inventory that the old metadata placeholder does not satisfy.
The synthetic replacement exercises that inventory contract without model
construction or loading actual weights. The probe calls no training dispatcher
and makes no claim that the complete new job equals the archived job.

The capture reserved 700,000,000 disk bytes, including a 500,000,000-byte
external pytest fixture charge, 1,024 MiB RAM, one CPU slot and 420 seconds for
the complete capture. The existing resource controller admitted the request
using a fresh named-root census before any capture outputs were created.
Pytest keeps its required cache provider and writes its private cache inside
the owned attempt. Temporary fixtures live outside that strict attempt and
remain charged. For this new, explicitly named fixture root only,
`tmp_path_retention_policy=failed` lets pytest remove successful `tmp_path`
fixtures at teardown while retaining failed fixtures. The installed
`_pytest/tmpdir.py` implementation is included in the dependency guard. No
prior fixture root, archived artifact or retained failed claim is cleaned up.
The ending fixture census measures retained bytes, not cumulative bytes
generated across all tests or a continuous peak. Live accounting continues
throughout the capture. Failed reservations and earlier failed receipts remain
retained.

The same package snapshot covered tests and the artifact probe, including
all Python package files, the selected test/helper dependency superset, legal-IR
scripts, and the audit harness. Exact archived sources, staged artifacts and
protected checkpoints/receipts are checked before and after. Each child denies
network syscalls before package imports and verifies the workspace logic-tree
pin. This is a revision-specific, offline contract qualification.

The [independent closeout](evidence/autoencoder_control_plane_plan/campaign-plan-closeout-20260926-r1.json)
records 375 passing cases with no failures, errors or skips: 57 new completion
cases, 77 new campaign-plan cases, and 241 existing registry/coordinator cases.
They cover restart without rerunning completed jobs, bounded dispatch, role
separation, shared targets and optional Arrow descriptors, full and sparse
candidate replay, compaction, and internally consistent forged receipts that
must still be rejected. Optimizer updates in these tests were injected fixtures.

The [test receipt](../../../workspace/test-logs/federal-corpus-audits/campaign-plan-20260926/capture-r1/tests/tests-receipt.json)
records 136.266512 seconds for the pytest invocation. The
[complete audit](../../../workspace/test-logs/federal-corpus-audits/campaign-plan-20260926/capture-r1/audit-receipt.json)
took 207.779295 seconds. All 7,761 package Python files, 904 dependency files,
the frozen harness, archived inputs and protected checkpoints remained unchanged
across the captured boundaries and closeout. These boundary checks are not an
atomic filesystem snapshot or a guarantee against subsequent edits.

The [artifact probe](../../../workspace/test-logs/federal-corpus-audits/campaign-plan-20260926/capture-r1/probe/plan-report.json)
sealed a 2,498-byte one-batch plan and obtained identical inspection results
after reopening the owner. Its queued run and checkpoint head were unchanged.
Coverage reports three planned training and three validation records against
62,839 eligible unique inputs: 51 embedded, 13 over the token limit and 62,775
unattempted. The physical source denominator remains 62,931 rows. This is scoped
inventory accounting, not a claim of formalization or complete federal coverage.

| Artifact-probe phase | Wall seconds |
|---|---:|
| Verify archived cycle inputs | 7.794252 |
| Stage selected closure | 0.171882 |
| Resolve registered corpus inputs | 8.133061 |
| Seal plan | 8.088805 |
| Inspect plan | 8.175184 |
| Inspect after owner restart | 8.243820 |

These single observations measure artifact preparation and inspection. No speed
comparison or legal-IR evaluation timing is claimed. The probe used six stored
records, one worker, bridge names `[]`, prover evaluation `false`, and metric
disk-cache flag `0`; OS cache state was uncontrolled, so this was not a claimed
cold run.

The [resource release](../../../workspace/test-logs/federal-corpus-audits/campaign-plan-20260926/capture-r1/resource-release.json)
records 83,823,257 final owned bytes and 583,823,257 total charged bytes including
the full external fixture reservation. Ending retained fixture bytes were zero.
Reservation `df68e3c2109c4d978a376ca6d3701ce3` and scheduler lease
`15ad55218f4e467db2ce745bd9371caa` were released; both child process groups had
exited. Closeout verified every preexisting retained claim row unchanged.
Resource enforcement remains cooperative and sampled, not a kernel quota or
continuous peak measurement.

The existing owned Quack Submit/Read/Resolve interface operates on explicitly
prepared invocation handles. Native invocation preparation, live Quack service
activation, native training dispatch, checkpoint qualification, DuckLake publication
and Hugging Face upload remain outside this offline audit. In particular, a
queued plan or a completion row does not prove source authority, semantic
correctness or a Lean admit. The Constitution remains unformalized. Only
`lake build <Lib>` counts as an admit.

The subsequent [deterministic batch generator](autoencoder_campaign_batches.md)
now prepares and registers bounded jobs from sealed campaign membership, with
stable page identities and explicit coverage dispositions. Its offline capture
passed 348 tests and a three-job archived-source repeat/restart probe; native
training remains deferred. Preparation profiling and complete offline campaign
publication/restore are next. Remaining orchestration work includes explicit
fenced recovery of interrupted attempts and realizing future parent dependencies
as new immutable jobs. The
owned Quack invocation path needs an explicit plan-to-prepared-handle adapter;
its native preparation remains deferred. Complete campaign publication and
restore, additional language frontends, source-authority checks and semantic
coverage are separate requirements.

Related work: [campaign job bindings](autoencoder_campaign_training_jobs.md),
[prepared-input reuse](autoencoder_prepared_campaign_inputs.md),
[diagnostic preparation profile](autoencoder_campaign_preflight_profile.md),
[control-plane plan](../plans/AUTOENCODER_DUCKDB_DUCKLAKE_TRAINING_PLAN.md), and
[federal-law training plan](../plans/FEDERAL_LAW_END_TO_END_TRAINING_PLAN.md).
