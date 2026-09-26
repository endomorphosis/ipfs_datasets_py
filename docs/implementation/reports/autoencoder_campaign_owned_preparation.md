# Preparation of original campaign jobs for owned execution

Implemented B1, 2026-09-26; **338 bounded offline regression tests passed on the
captured source revision**, with zero failures, errors or skips. The user
authorized increasing the campaign cap to 60 GB, and the guarded test attempt
completed and released its reservation. The
[test receipt](evidence/autoencoder_control_plane_plan/campaign-owned-preparation-tests-20260926-r1.json)
and [audit receipt](evidence/autoencoder_control_plane_plan/campaign-owned-preparation-audit-20260926-r1.json)
cover synthetic request, owner, journal and resource fixtures. No native or
full-corpus execution, model construction, legal-IR speedup, or completion
qualification is established.

The later [combined integration capture](autoencoder_campaign_integration_validation.md)
passed 580 offline cases, including these 338 B1 cases, on its separately bound
source revision. It also covers the semantic repairs, Constitution observation
boundary and bounded ingest scheduling. B2 worker supervision and B3 Quack
submission remain unimplemented; the additional tests grant no execution authority.

This implements the first stage of the
[owned dispatch plan](../plans/AUTOENCODER_CAMPAIGN_OWNED_DISPATCH_PLAN.md), using
the existing [sealed campaign plans](autoencoder_campaign_plan.md) and
[deterministic batches](autoencoder_campaign_batches.md). The
[control-plane plan](../plans/AUTOENCODER_DUCKDB_DUCKLAKE_TRAINING_PLAN.md) and
[federal-law plan](../plans/FEDERAL_LAW_END_TO_END_TRAINING_PLAN.md) retain the
broader training and publication sequence. The result qualifies the bounded
offline contracts below, not the remaining execution or publication stages.

The pure
[`autoencoder_campaign_training_request.py`](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_campaign_training_request.py)
codec seals an explicit selection of at most 64 batches, ordered as their plan.
Its closed canonical JSON binds owner paths, the exact plan descriptor, variant
and campaign roots, job descriptors and digests, original run/base/output
identities, target and Arrow descriptors, and resource/execution policies.
Duplicate keys, unknown fields, invalid scalar types, noncanonical encodings,
unsafe lexical paths and oversized input are rejected. Codec validation performs
no filesystem operation. Numeric, structural and request-size bounds belong to
this new contract; they do not expand existing worker limits.

The owner API in
[`autoencoder_campaign_owned_training.py`](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_campaign_owned_training.py)
provides `prepare_campaign_training` and `inspect_campaign_training`. Preparation
reconstructs the registered plan through the existing metadata verification path,
then compares its exact canonical bytes. It verifies corpus closure and checkpoint
inventory without constructing weights, replaying candidates or hydrating target
payloads. The canonical workspace logic tree is required; an import from the
editable HACC install is rejected by the existing pin.
The capture uses the existing operation-local campaign root scope to avoid
decoding the same roots once per job. It closes that scope before returning;
current root hashes, both-role authorization and selected-artifact checks remain
per-job requirements. This integration has no comparative performance result.

Original v8 job bytes, inline embedding vectors, configuration and shared target
references remain unchanged. Optional Arrow feature weights and sparse checkpoint
policy remain explicit. There is no conversion to Arrow embedding inputs or
replacement checkpoint. Existing job bridge names, prover settings, worker count,
memory-evaluation setting and update backend are retained. The request is not an
accepted input to the current daemon owned-control profile.

Preparation selects only pristine queued runs: attempt and fence zero, no lease,
no result, and no worker output directory. It stages a separate immutable request
in owner CAS and uses a distinct control journal directory. It creates no new run,
claims no job, changes no checkpoint head and enqueues no publication. One short
owner transaction binds every selected run and records the preparation operation
using the existing operation table; there is no database schema change.

Each run has a deterministic binding keyed by its owner and run identity.
Conflicting selections, including overlaps from different plan pages, cannot
obtain a second assignment. Retry resolves the same exact operation and payload.
Identical preparation is allowed only while the selected jobs remain pristine.
The same immutable request may be restaged if its CAS copy is missing; original
inputs and an existing journal may not be recreated by preparation or inspection.
A failed final guard can leave an already committed historical binding and
staged artifacts. Those remain inspectable evidence, not a successful completion.

The existing
[`DurableDaemonOperationJournal`](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_operation_journal.py)
now supports `create=False` for reopening required journal and lock files. Its
default creation behavior remains unchanged for existing callers. The owner
holds the journal context through its final metadata and artifact checks.
Current run/base-version records, owner paths, resource roots, worker output
parents, output presence and captured input bytes are checked at the operation
boundaries. These guards do not make arbitrary concurrent filesystem mutation
atomic. The module-level source guard is limited to its declared validators;
the qualification capture separately checked the whole package and its declared
test dependencies before and after execution.

Inspection reads the exact request, registered plan, assignment history and
existing journal. It reports observed registry status and whether each selected
run remains pristine. `prepared` and `recovery_required` describe that eligibility;
neither verifies execution. Even an observed completed registry row retains
`completion_verified=false` because this API performs no candidate replay.
Nonempty execution-journal history also reports `recovery_required`, even if
the registry rows still look pristine; an unresolved intent cannot authorize
another computation.
Inspection must not repair missing inputs, recreate journals or mutate run state.

The resource policy binds ledger path, disjoint named roots, storage bytes, memory
and CPU allocation per future worker. Preparation constructs the existing
reservation validator but never enters it. This checks policy/path shape and
containment; it does not read capacity into a reservation, acquire a worker lease
or promise future capacity. Preparation's own filesystem work requires separate
admission when invoked outside the isolated test fixtures. `capacity_admitted` and
`execution_available` remain false.

At **2026-09-26 16:44:13.978619 UTC**, a read-only standard-library census observed
40,003,977,864 bytes in the named roots. Seventeen retained claims reserved another
10,030,000,000 bytes, giving **50,033,977,864 bytes against the 50,000,000,000-byte
quota: 33,977,864 bytes over quota**. The ledger also contained 31 released claims
and no active/reserved claims. Its 92,871-byte SHA-256 was
`3dad515ba59e9494687f2bfa9c9b8be36479e80ced854cff6a415e7b8eb66b76`.
The canonical retained-record census SHA-256 was
`a182f9505d5ecf83f57c0f233656b878681670a4f09f66fd97fde3ada927757b`.
Ledger bytes and named-root identities stayed unchanged during that census.
This non-atomic observation is not admission and must be refreshed before work.

A second read-only census at **2026-09-26 17:02:06.207074 UTC** observed
40,037,331,746 bytes: with the same retained reservations, total charged bytes
were **50,067,331,746**, or **67,331,746 bytes over quota**. All 17 retained
records, the ledger hash and named-root identities were unchanged. There were
185,935 entries and no observed disappearances. This later observation still
provided no capacity for the then-proposed bounded validation.

A third independent read-only census completed at **2026-09-26
17:10:53.301034 UTC** with the same observed and charged bytes, all retained
records, ledger bytes and root identities unchanged. The same capacity blocker
had persisted across three consecutive goal turns. At that point the five
implementation and test files retained their prior hashes and runtime validation
had not begun. Those observations remain historical evidence; they are not the
current validation status. No evidence, failed claim or existing data was deleted
to obtain capacity.

The user then explicitly authorized a cap increase. At **17:49:26.752924 UTC**,
the live ledger's top-level limit was migrated from 50,000,000,000 to
60,000,000,000 bytes under its lock, preserving the exact original backup,
all 48 reservation records, all 17 retained claims and their historical accounting.
The audit binds the migration receipt and backup. The campaign request's
per-worker 50 GB bound and unrelated legal-runtime limits remain unchanged.
Old 50 GB ledgers still require explicit migration; readers never upgrade them
or expire retained claims implicitly.

The fresh capture passed **169 request-codec, 72 owner-preparation, 45 journal
and 52 resource cases** in **94.221646142 seconds**. Whole audit wall time was
**179.306021646 seconds**, including a **60.869669710-second** pre-admission
source-stability window. All 7,772 package files and 925 dependency files stayed
unchanged across the parent/child chain; harness, input, produced-artifact and
protected-checkpoint guards passed. The child installed network denial before
project imports and pinned compiler, decompiler and parser to the canonical tree.
These are test timings, not training or inference benchmarks.

The explicit bound was **50 MB storage**, including a 30 MB charge for unique
temporary fixtures, **1,536 MiB memory**, **one CPU** and **1,200 seconds**.
The [release receipt](evidence/autoencoder_control_plane_plan/campaign-owned-preparation-release-20260926-r1.json)
records 5,753,402 final attempt bytes and 35,753,402 charged attempt bytes.
Reservation `8c28e7c80769498089f115c46820852c` and lease
`cdf4bcbb590a4edbb85861ed33b788ab` were released; the final owned group had no
live processes. All 17 earlier retained claims remained unchanged. Successful
test fixtures were ephemeral under the explicit private retention policy;
no prior failed fixture or capture was removed. Earlier failed current-tree
closeouts retain their original failed status.

B2 remains planned: journaled owner execution through the original coordinator,
with independently admitted resources, bounded child groups, normal completion
verification and exact recovery. B3 remains planned: a typed sibling Quack
controller and explicit gateway profile using bounded submit/read/resolve.
Neither stage is implemented by this request format. Native qualification remains
deferred; no live Quack listener or Hugging Face upload has been started.

All admission, formalization, source-authority, global-holdout, execution,
promotion and publication authority flags remain false. A request, journal,
registry row, checkpoint inventory or successful future training step is not a
Lean admit. Only the required `lake build <Lib>` path can admit a formalization.
The Constitution is not formalized, and no Constitution span is marked
`roundtrip_ok` by this work.
