# Owner-leased U.S. Code daemon invocation

Status: **implemented; native owner lifecycle qualified for the exact six-record,
zero-update slice**, 2026-09-25. The
[implementation report](../reports/autoencoder_daemon_owned_invocation.md) records
the concrete API, current refusals, 635 passing guarded regression checks and
140 passing checks after the resource-lane correction.
This slice connects one supported daemon invocation to the existing registry
owner. The
[first attempt](../reports/evidence/autoencoder_control_plane_plan/owned-daemon-invocation-native-20260925-r1.json)
stopped at resource preflight because the recorded scheduler had no trainer CPU
capacity, before input export or daemon execution. The wrapper incorrectly used
`TRAINER`; it now uses the existing canonical-trainer `HAMMER_LEAN` mapping,
without changing the 20-slot capacity or lane reservations. After guarded
correction tests, [native r2](../reports/evidence/autoencoder_control_plane_plan/owned-daemon-invocation-native-20260925-r2.json)
passed actual owner-leased execution, full-candidate verification and identical
restart replay for three training and three validation records. It accepted zero
updates and left the logical state and head unchanged; changed-state learning
and general held-out/canary qualification remain unproven. The failed r1 receipt
is preserved and no resource guard was weakened. It does not change
the optimizer, enable sparse or mapped storage, promote a branch head, publish a
model, or qualify a Lean admission. Only `lake build <Lib>` is an admit. The
Constitution remains unformalized; no HACC work or model-weight downloads are
part of this slice.

The subsequent [offline sparse-shadow slice](../reports/autoencoder_daemon_sparse_shadow.md)
is also implemented: exact complete-state endpoint differences replay against
the authoritative full checkpoints. This is diagnostic evidence, not live
mutation capture, sparse candidate authority or native changed-state learning.

The [owner-integrated optional shadow](../reports/autoencoder_daemon_owned_shadow.md)
is implemented and off by default. `prepare_daemon_invocation(...,
sparse_shadow=True)` seals a closed v2 request; ordinary v1 requests remain
unchanged. The real independent verifier produces the nested shadow after
verifying the full candidate, and the owner stages `sparse_shadow_patch` and
`sparse_shadow_receipt` alongside its existing evidence. Full checkpoints retain
candidate authority and historical completion replay retains the same evidence
references without re-execution. The guarded production suite passes 515 checks;
25 harness checks pass. The
[bounded hybrid r2 qualification](../reports/evidence/autoencoder_control_plane_plan/owned-daemon-shadow-20260925-r2.json)
passed real describe/verify subprocesses around a disclosed synthetic execute
boundary: one directly assigned scalar, zero accepted epochs and
`evaluation_matches_final=False`. Owner completion and exact restart replay
passed with the full candidate authoritative. The
[failed r1](../reports/evidence/autoencoder_control_plane_plan/owned-daemon-shadow-20260925-r1.json)
is retained: an early runner import changed the fixture environment before the
sealed-environment check, which correctly rejected it before checkpoint copying
or mutation. The harness now matches native import order; a subprocess
regression exercises the unchanged real environment guard. This qualification
does not establish native changed-state learning.

## Starting evidence and remaining boundary

The [native input-cycle qualification receipt](../reports/evidence/autoencoder_control_plane_plan/daemon-corpus-input-native-cycle-20260925-r1.json)
passed through the actual parser/main with three frozen training records and
three validation records, ordinary list vectors, default asynchronous snapshots,
and no loader/evaluator/trainer replacements. Source, producer configuration,
protected checkpoint and input guards passed. One snapshot completed and matched
its evaluation version; final checkpoint persistence was durable. The projection
accepted **zero epochs**, the supervisor applied zero updates, and the final
logical state identity matched the initial identity at revision zero. Its final
compact checkpoint was 1,664,462 bytes. This qualifies the exercised control flow;
it does not demonstrate learning, successful changed-state adoption, general
held-out qualification, or a speed improvement. Raw checkpoint identity is
separate from logical state identity.

The [independent native checkpoint audit](../reports/evidence/autoencoder_control_plane_plan/daemon-corpus-input-native-cycle-independent-audit-20260925-r1.json)
loaded the protected initial checkpoint and final compact checkpoint with the
native loader. Their complete canonical state bytes, all 38 component digests,
and same-lineage identity records matched at revision zero; their transport
bytes differed. This audit did not rerun training or proof evaluation, and did
not repeat the full source manifest check.

Native projection took 2.569 seconds within 133.940 seconds of actual main.
The before-training evaluator call took 28.789 seconds; the before-validation
phase took 27.561 seconds; warm after-evaluation phases took 2.013 and 2.464
seconds. The 45.205-second async snapshot overlapped daemon work and must not be
added to those phases as disjoint wall time. Peak RSS was 1,791.62 MiB. All four
train/validation evaluations retained three targets. Snapshot proof diagnostics
reported 32 valid results across mixed modal compilation/routing; local tableaux
may execute, and this validity can be true without a proved theorem. There was
no Lean/Lake route or admission. These are measurements of one invocation, not
a comparison or proof that checkpoint work dominates end-to-end cost.

That receipt's private registry run remained unleased and its database remained
unchanged after input export. The current
[input export](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_corpus_inputs.py#L145)
and [registration](../../../ipfs_datasets_py/duckdb_control/autoencoder_registry.py#L393)
bind an immutable input closure; neither grants execution/checkpoint authority.
A trusted local descriptor handoff is required. A digest or registration record
does not authenticate an arbitrary issuer or prove native computation by replay.

The implemented boundary independently verifies a complete final daemon state
before acceptance under a live owner lease. Native r2 qualifies that lifecycle
for the exact zero-update slice; it does not establish changed-state capture.
Projection patches alone are insufficient.
The existing [training coordinator](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_training_coordinator.py#L601)
is useful precedent for staging and fencing, but its `TrainingJobSpec`,
`TrainingConfig`, receipt verifier and
[`registered_checkpoint_inputs`](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_training_coordinator.py#L62)
are not a native compact-daemon-checkpoint acceptance contract.

## Implemented topology and public API

Use one owner-leased child process running the actual daemon `main`, with an
explicit `max_cycles=1` invocation bound and an exclusive attempt directory.
The lease covers startup recovery and compaction, the complete
cycle, snapshot shutdown, final writer drain, candidate verification and owner
completion. A separate owner loop renews the lease while native computation or
artifact hashing blocks. The child never opens the registry database.
Warm starts are currently refused until their dependencies can be bound.
Schedule renewal independently of long child/hash work, but serialize all
registry commands through one owner dispatcher. Background computation may
return verification results to that dispatcher; it must not concurrently share
one DuckDB connection among worker threads. Keep renewal deadlines visible while
non-database work runs outside the dispatcher.

Start with one active invocation. Later same-base parallel candidates use
separate attempt directories and leases; the single owner serializes registry
mutations and any separately authorized head transition in short transactions.
Long computation and artifact hashing stay outside those transactions. Parallel
candidates do not merge one another's state or race to overwrite a shared head.
Do not raise default concurrency before measuring aggregate memory and CPU
pressure; the observed approximately 1.75 GiB peak for one invocation matters.

Before each launch, reserve explicit per-attempt memory and storage bounds in
the owner scheduler. Memory reservations cover the child, snapshot copies,
decoded targets, writer buffers and the owner's independent checkpoint load;
the observed child RSS is evidence for sizing, not a safe universal upper bound.
For storage, account current named campaign roots plus retained and concurrent
reservations against the existing **50,000,000,000-byte campaign budget**. Include
the staged base and private copy, full candidate, sealed receipts/diagnostics,
temporary writer/staging files, CAS publication copies, journals and any bounded
cache/queue output. Do not assume CAS deduplication or temporary-file removal
until verified. If the requested bounds cannot fit, do not launch. Retain
reservations until cleanup or immutable retention is accounted for; enforce
the configured attempt bounds and stop/quarantine on overrun. Do not raise the
campaign/artifact limits or automatically clean unowned artifacts to make room.

Implemented [owner adapter API](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_invocation.py#L151):

```python
prepare_daemon_invocation(
    registry, *, run_id, variant_id, base_version_id, input_snapshot,
    daemon_argv, output_directory, resource_policy, environment_overrides=None,
    sparse_shadow=False,
) -> prepared

run_owned_daemon_invocation(
    registry, prepared, *, lease_seconds=300, timeout_seconds=900,
) -> completion
```

The first call stages a bounded immutable daemon request and creates a distinct
execution run. The registered input-anchor run is not the execution run. The
second resolves that exact request from the owner, claims the execution run,
creates a fresh attempt directory beneath the request's output root, invokes
the real CLI, verifies the result and calls the existing `complete_run`.
Requested output paths must be confined to this attempt; a prior attempt's
mutable summaries, queues, crash manifests or checkpoint files must not be
silently resumed. Reuse requires an explicit new registered base/dependency
handoff. The attempt path and lease identity are recorded before launch.
Because the fence is unknown during preparation, the immutable request specifies
the output root and deterministic relative path rules. After `ClaimRun`, seal a
launch receipt containing the unchanged argv, environment, attempt directory and
lease binding. Ordinary relative output paths resolve under that private working
directory. Reject argument/environment changes and persist the receipt before
starting the child.

Use a new closed, versioned daemon-request schema in `run.spec`, with an artifact
descriptor rather than an oversized inline configuration. Bind the actual
parsed/effective daemon arguments and relevant environment; do not translate
them into worker `TrainingConfig` defaults. Record the original argv separately
for diagnostics. Resolve environment-derived settings before sealing the request
and reject any effective-settings mismatch in the child. Path values must refer
to the explicit staged dependencies or the isolated output directory.

Within the supported configuration this preserves optimizer families, epochs, line search,
learning schedules, bridge loss/metric/diagnostic lists, prover policy, sample
memory, text/count caps, internal queue policy, compaction limits,
disk cache, thread count and snapshot/writer settings. Async snapshots remain
enabled when the ordinary configuration enables them. The invocation bound must
not silently force `python_sparse_batch`, one family, zero TODO work, or a
different acceptance policy. Unsupported settings fail preflight rather than
being rewritten. No network fallback or automatic download is introduced.

The current contract requires the autoencoder role, explicit `max_cycles=1`,
Python CPU backend, verified local inputs and no external bridge provers. It
refuses warm-start state/run IDs and canonical warm starts, unbound external
guidance paths/waits/projection/training, executor modes other than `packet_only`
and commit modes other than `none`. Bridge workers must match the sealed
environment. These are preflight refusals, not silent changes to native settings.
Actual training evaluations request sample memory; validation evaluations do
not. Per-pass observations distinguish those policies from the projection
report's separate `sample_memory_used` value and do not infer memory-hit counts.

The request binds the variant manifest, registered base and dependency closure,
trusted input snapshot, complete producer/source identity, environment, effective
configuration. The adapter does not change the registry head. The input snapshot still
transitively binds the v6 job, frozen index, source records and native embedding
receipt. Preserve current canary-zero and v6 ordinary-vector limits. Record
all additional imported dependencies before any future warm-start/guidance support.
Generated artifacts must remain traceable to this invocation. Unbound external
guidance arriving during the attempt cannot silently become an accepted
candidate dependency.

## State capture and runtime integration

The default-off observation context is installed by the native child wrapper;
the ordinary CLI path remains unchanged and needs no new observation flags.
The owner is responsible for authority. The child validates its bounded launch
descriptor, calls actual main, and the runner reports execution facts,
without claiming that an arbitrary local request file proves a live lease.

Capture these identities under one explicit state-identity/metric-lineage
contract, with revisions and immutable byte descriptors where available:

| Boundary | Why it must be retained |
| --- | --- |
| Registered base before startup | Establishes the immutable parent independently of the daemon's mutable output path. |
| Effective state after recovery and startup compaction | Startup changes already precede training and may write a checkpoint; owned warm starts are currently refused. |
| State before each evaluation and projection phase | Prevents attaching metrics to a later different state. |
| Completed-cycle state after supervisor, guidance and compaction | Includes every model-state mutation in the cycle. |
| Final shutdown state | Includes any final capacity compaction and is the accepted checkpoint candidate. |

Relevant current boundaries are
[startup compaction/warm starts](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/uscode_modal_daemon_runner.py#L19402),
[direct guidance and post-guidance compaction](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/uscode_modal_daemon_runner.py#L21532),
[selected-input verification and snapshot publication](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/uscode_modal_daemon_runner.py#L21600),
and [shutdown compaction/final persistence](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/uscode_modal_daemon_runner.py#L22884).
After-training metrics precede direct guidance and cannot certify the later
candidate by themselves.

Retain the existing immutable
[`ArtifactSnapshotHandle`](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/async_artifact_writer.py#L111)
and [revision-checked serializer](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/async_artifact_writer.py#L437).
The first invocation's final candidate is one full compact float64 checkpoint,
including all native state fields and ordered applied-ID lists. Reuse the final snapshot
bytes and writer receipt; do not reconstruct a candidate from projection patches
or perform a second divergent serialization. Ordinary cycle full/delta cadence
and asynchronous snapshot copies remain intact. Only the sealed final full
checkpoint becomes an owner candidate in this slice.

The daemon receipt records actual ordered training/validation record indices,
record IDs, runtime sample IDs and exact input identities; target/report bundle
identities and live-fallback decisions where applicable; complete cycle count;
all state boundaries; writer/snapshot completion; final bytes/checksum/revision;
and source/config/input guard outcomes. Stage the detailed receipt and summary
as immutable artifacts. The small registry result binds their descriptors and
the candidate descriptor, with `admitted=false`, `promoted=false`, and
`publication_performed=false`. The entire registry command, not merely its
result, must fit the existing 65,536-byte command limit.

TODO queue and guidance side effects remain visible and local to the attempt.
The full checkpoint captures model state, not an atomic transaction over every
queue/log/external effect. A failed candidate does not claim to roll those
effects back. Bind queue/import/export receipts needed for a future continuation;
do not overwrite an unrelated shared queue or head to simulate rollback.

## Owner verification and completion

1. Before launch, verify the request artifact against the registered run and
   variant; verify the input capsule and all dependencies; check the source and
   producer configuration; and load the registered base through an explicitly
   supported codec. Initially support full legacy JSON and full compact binary
   bases. Reject sparse manifests unless the adapter deliberately uses the
   existing semantic [sparse resolver](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder_sparse_checkpoint.py#L388)
   and verifies its entire closure. Never feed a sparse manifest to the generic
   JSON state loader as though it were a full checkpoint.
2. Claim a lease before any daemon startup mutation. Record its attempt, fence,
   owner generation and the exclusive directory. Supervise the child with the
   requested hard invocation timeout; keep heartbeat independent of parser,
   training, snapshot drain and artifact verification work.
3. Preserve current selected-sample and boundary checks through
   [`VerifiedDaemonCorpusInputs`](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_corpus_inputs.py#L187).
   Verify package/source, producer configuration and input closure again at
   completion. Input guards run before consumption/persistence and after
   snapshot drain; failures suppress new candidate acceptance. File checks
   establish observed integrity boundaries, not proof against transient
   mutate-and-revert events by a concurrent writer.
4. Require successful child exit, exactly one completed cycle, no provisional
   cycle/source/input failure, final checkpoint durability, writer drain and
   cleanup completion. Zero accepted optimizer updates is a valid result; it
   must remain explicit. Preserve failures and pending local artifacts without
   calling them candidates. A zero-cycle startup success is not completion.
5. Copy/fsync the sealed output into owner CAS with
   [`stage_artifact`](../../../ipfs_datasets_py/duckdb_control/autoencoder_registry.py#L274),
   checking exact receipt SHA/bytes and regular-file/path identity. Independently
   load the staged full compact artifact with
   [`load_checkpoint`](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder_checkpoint.py#L1069),
   `allow_json=False`, `recover=False`, no delta path, and expected schema/revision.
   Reconcile reconstructed state identity, metadata, request, input binding,
   effective configuration, base ancestry and receipt. Bound file/decoded sizes
   before loading; do not silently increase existing artifact limits.
6. Preserve asynchronous evaluation as an independent result. Compare its
   complete state/compiler/holdout/schema tuple and sequence with the actual
   final state. Snapshot state identity uses the metric schema, whereas the
   checkpoint handle defaults to `metric_lineage=None`: recompute under the
   same lineage rather than comparing those two strings directly. A mismatched
   or incomplete evaluation leaves an unevaluated candidate and an explicit
   reason. It never authorizes registry head promotion. Existing local snapshot
   result promotion is metric acceptance, not registry model-head promotion.
7. With a still-live exact lease, invoke
   [`complete_run(operation_id, lease, artifact, result)`](../../../ipfs_datasets_py/duckdb_control/autoencoder_registry.py#L527).
   It creates one immutable version parented to the run's registered base and a
   `candidate_durable` event. It verifies staged bytes and fencing, but does not
   independently understand compact checkpoint semantics; step 5 is mandatory.
   Do not call `promote_head`, activate an outbox consumer, or publish externally.

## Durable operation journal and restart

The current coordinator retains UUID/counter operation IDs only in process
memory. Its response-loss retry is precedent, not a durable restart journal.
The new owner adapter durably writes each intended command's exact operation
ID, command name and canonical payload before submitting it, then persist the
returned receipt. Journal the request/run binding, lease transitions, attempt
directory, child identity, staged candidate/diagnostics and completion intent.
Use atomic publication plus file/directory fsync; an unreadable or partial journal
must not authorize guessing a new operation ID.

Serialize renewals and completion so that a heartbeat cannot replace the exact
lease JSON after the completion payload has been sealed. Stop renewal while that
exact `CompleteRun` is in flight. Choose a valid remaining lease allowance for
its final artifact rehash; if that work outlasts expiry before commit, fail
closed and quarantine the output. Do not bypass expiry or substitute a new
lease into the pending payload. On an ambiguous
response, use
[`resolve_operation`](../../../ipfs_datasets_py/duckdb_control/autoencoder_registry.py#L232)
with the same ID, command and payload. Persist the renewed lease before using it.
On owner restart, resolve any pending `CompleteRun` first. A matching committed
receipt is historical completion, even if its lease has since expired; separately
check current artifact availability. Never relabel committed completion as
failure because its original response was lost.

If completion did not commit and the owner generation/fence is no longer live,
quarantine the old output. Do not claim a new lease and retroactively accept old
computation. A new execution attempt uses a new isolated directory. On unresolved
renewal or lease loss, signal/terminate the child according to the bounded
supervision policy and reject its candidate. Existing queued writes may still
drain locally; they remain non-authoritative attempt artifacts. Call `fail_run`
only with a valid exact lease and after resolving ambiguous prior mutations.

## Implementation status and remaining validation

Request/launch contracts, the owner adapter, durable journal, resource
reservations, native child/verifier and default-off runner observations are
implemented. The [report](../reports/autoencoder_daemon_owned_invocation.md)
links focused receipts, the guarded 635-check combined result and the 140-check
lane-correction follow-up. Only the resources module changed between those
production captures, and sources remained unchanged during each test run. The steps
below retain the slice's acceptance obligations. Native r2 completes step 4 for
the exact six-record, zero-update slice; future unsupported mutation paths and
native changed-state capture remain separate gates.

1. Implemented: daemon request/receipt codecs and owner adapter with a durable intent
   journal, reusing generic registry methods without changing their authority
   model or introducing new registry DDL.
2. Implemented: default-off actual-runner observations at the state boundaries above.
   Preserve the no-option behavior, sampling RNG, rejection limits, ordinary
   configuration, shared target/report semantics and asynchronous workers.
3. Focused and combined tests pass beside the existing
   [registry](../../../tests/unit/duckdb_control/test_autoencoder_registry.py),
   [corpus runner](../../../tests/unit/optimizers/logic_theorem_optimizer/test_daemon_corpus_input_integration.py),
   [checkpoint](../../../tests/unit/optimizers/logic_theorem_optimizer/test_modal_autoencoder_checkpoint.py)
   and [coordinator](../../../tests/unit/optimizers/logic_theorem_optimizer/test_autoencoder_training_coordinator.py)
   suites. Do not substitute fixture execution for native qualification.
4. Semantic/round-trip gates pass in the combined suite. Native r2 passed one
   guarded owner invocation with unchanged protected checkpoint/head and
   OS-denied network. Its complete receipt retains sources, configuration,
   selected records, diagnostics and owner-restart verification. It does not
   establish an accepted change, a speed improvement or broad canary success.
   No automatic retry on drift.

Required focused cases include default option omission; exact effective-config
matching; wrong base/input/source binding; malformed, truncated or oversized
compact candidate; unsupported sparse base; foreign path/symlink; selected-row
or vector mutation; zero cycles; late source failure; writer failure or timeout;
snapshot lag/failure and final-lineage mismatch; and no candidate on failed
cleanup. Exercise startup compaction, accepted projection, supervisor/applied-ID
changes and final compaction in bounded synthetic integration cases. Warm-start
and external guidance refusal tests preserve the current supported scope; their
future adoption requires bound dependencies and separate mutation coverage.
Verify complete reconstructed state, not just
projection numerics. Keep these changed-state fixture cases distinct from the
native zero-update evidence.

Resource tests must reject insufficient memory/storage reservations before
launch, count temporary plus CAS copies, retain accounting for failed attempts,
and leave unowned artifacts untouched. Bounded concurrency must not oversubscribe
the shared campaign reservation.

Owner tests must cover lease expiry, competing fences, renewal response loss,
completion response loss, crash before/after commit, journal truncation, restart
under a new owner generation, candidate corruption after staging, and the rule
that resolving historical completion is not a fresh availability check. Assert
one version/event for exact retries, unchanged head, `admitted=false`, and no
publication. A later native run with genuinely accepted changes is needed before
claiming native changed-state capture has been demonstrated.

## Opportunity cost and later storage work

This first topology pays process startup, cold caches, full checkpoint transfer
and an independent owner load. Those costs buy a bounded, reviewable authority
boundary around the actual daemon. Record startup, full-cycle, snapshot drain,
serialization, staging, owner verification, memory and disk use separately.
There is no unmeasured speed claim. A resident per-cycle owner acknowledgement
protocol could retain warm caches, but introduces interruption/restart and
parent-version transitions; defer it until this invocation contract is proven.

The [offline endpoint shadow implementation](../reports/autoencoder_daemon_sparse_shadow.md)
now derives and independently replays the complete net difference between sealed
full checkpoints. Its
[offline receipt](../reports/evidence/autoencoder_control_plane_plan/daemon-sparse-shadow-20260925-r1.json)
passes for the historical zero-update owner candidate (1,459-byte patch,
12.33855 s case wall time) and an archived six-scalar change (2,916-byte patch,
9.45630 s), with 29.60585 s total qualification wall time including guards.
All 38 raw native fields, exact revision and canonical state identities agree;
the zero-update compact checkpoint is reproduced byte-for-byte. A guarded
combined suite passes 250 checks in 10.93 s pytest / 13.143 s wrapper, with
unchanged sources. Case times are included in the total; this is not a speed
comparison. No new training, evaluation or owner operation was performed.

The archived change came from one accepted projection epoch on three in-sample
gate sentences; its legacy reload has revision zero. It does not establish an
owner-observed native changed-state transition or current owner authority.
The full endpoints remain authoritative. Next gates are intermediate mutation
and live capture coverage, rollback/rejection and recovery evidence, and an
explicit sparse candidate authority contract. Startup/final compaction,
supervisor/guidance effects, deletions and ordered applied-ID lists must remain complete;
unsupported owned warm starts/guidance do not become enabled by this diagnostic.
Projection-only patches remain insufficient. Sparse persistence is not enabled
by endpoint equivalence alone.

The [bounded mapped daemon input path](../reports/autoencoder_daemon_mapped_inputs.md)
now accepts opt-in v7 jobs through the owner-exported input snapshot. It verifies
the exact Arrow artifact, session-owned source/vector rows and checkpoint
provenance. Memo-aware `MappedEmbeddingVector.__deepcopy__` returns detached
ordinary lists, preserving exact float values, signed zero and aliases. Synthetic
producer declarations and optimizer fixtures exercise the real session,
asynchronous snapshot use after closure, in-flight shutdown and error cleanup.
Copying must finish before owner closure; this does not add concurrent copy/close
synchronization or establish whole-training zero-copy.

A complete native owner v7 cycle and speed comparison remain unqualified;
native validation is deferred at the user's request. A future authorized
comparison must use fresh native v6/v7 cycles with the same pinned checkpoint, source records,
splits and optimizer/snapshot settings: all five bridges, provers false, metric
disk cache zero, one bridge worker and explicit per-pass sample-memory policy.
Keep v6 list vectors and ordinary parameter storage as defaults. Historical mapped-input jobs were slightly
slower (23.0663 s versus 22.9321 s median), as was the mapped feature-table
comparison (12.7500 s versus 12.1534 s); neither justifies a default switch.

The [optional mapped feature-weight milestone](../reports/autoencoder_daemon_mapped_weights.md)
now adds `arrow_feature_weights` to owner preparation through a closed v3
request, preserving existing v1/v2 behavior. Exact sidecar/full-base binding
precedes attachment to the same native state without a revision change; all 38
fields and ordinary tracked update/rollback semantics must remain equivalent.
Native pruning or TODO state replacement may yield `detached_native`, reported
without automatic reattachment. The caller owns the mapped lifetime through
daemon cleanup, while asynchronous snapshots and checkpoint handles detach.
Per-boundary SHA checks add bounded, unmeasured overhead. The combined capture
passes 772 tests with all 7,737 package source files unchanged and protected
checkpoint/receipt hashes intact. Native validation remains deferred, full checkpoints retain candidate
authority, and no speedup, default switch or parallel-memory benefit is claimed.

The [isolated DuckLake delivery and compact private release slice](../reports/autoencoder_ducklake_delivery_and_compact_release.md)
now mirrors immutable owner events through a durable batch journal and a native
DuckLake event/marker transaction, with targeted lease recovery after partial
acknowledgement. Its fresh catalog/DATA_PATH and default 256 MiB namespace cap
do not transfer full-checkpoint or weight authority from CAS. The offline v2
private release profile accepts exact full float64 compact checkpoints; the
historical 1,664,643-byte, zero-update owner candidate packages twice with the
same bytes, all 38 fields, revision and package identity. Legacy package hashes
are unchanged; sparse/delta manifests remain rejected. Registry/HF focused
checks pass 69/93 cases and native sink/consumer checks pass 57/18, including
bounded process kill/restart recovery. The bounded storage/packaging combined r2
passes 558 checks across 14 test files in 167.97 s pytest / 170.354915 s wrapper,
with all 7,739 package Python sources, selected tests and protected artifacts
unchanged. The failed r1 and test-only HF fixture correction remain documented;
the production publisher guard is unchanged.
This performs no new daemon training or evaluation, no
upload and no admission. Production DQK activation, remote Quack adaptation and
the HF publication consumer remain pending, and native training validation
remains explicitly deferred.

The [daemon checkpoint-baseline implementation](../reports/autoencoder_daemon_checkpoint_baselines.md)
removes the retained full previous-state copy and repeated prior-endpoint
normalization from component-delta persistence. Tokens come from the already
serialized endpoint and advance after successful enqueue; existing byte formats,
replay/drain checks and full-candidate authority remain. The combined fixture
capture passes 651 checks across 20 files, with all 7,739 canonical Python
sources, selected tests and protected artifacts unchanged. Exact bytes are
compared against the saved pre-change serializer for both precisions and all
38 components; real writer/main fixtures cover multi-cycle and failure recovery.
This does not introduce row-sparse daemon checkpoints or establish an end-to-end
speed or concurrency improvement; native training validation remains deferred.

The [declared-release source inventory](../reports/autoencoder_uscode_source_inventory.md)
now connects complete source accounting to bounded exact input materialization:
the first offline scan verified 16 shards and 62,931 rows and materialized three
inputs, with 271 checks and source guards passing. A subsequent mixed
duplicate-wrapper accounting correction awaits fresh validation; its historical
scan receipt remains intact. This changes neither invocation schemas nor owner
dispatch and provides no new native training qualification.

Global source partition freezing, producer-receipt-set bindings,
multilingual/Constitution frontends, held-out qualification, production DuckLake
consumers and HF publication remain separate gates. Neither a completed registry
run nor a faster storage path changes the meaning of semantic success or Lean
admission.

The [owned-invocation Quack profile](../reports/autoencoder_owned_quack_control.md)
now records scoped immutable submissions through the existing registry and
exposes bounded status/exact resolution. The owner calls `execute_pending`
outside the gateway pump; the native invocation coordinator still owns leases,
resource reservations, child isolation, verification and candidate registration.
Raw generic worker mutations are denied for these prepared runs. A durable
start with no committed coordinator outcome remains `recovery_required` rather
than launching another attempt. This is exercised through real owner storage
and synthetic child fixtures, with live Quack/native validation still deferred.
The same-ledger parallel fixture found a pre-claim lock race. A separate bounded
five-second ledger-lock budget now permits brief bookkeeping serialization;
scheduler admission remains zero-wait and all quota/retention rules remain.
Actual owner execution with synthetic children verifies overlap and independent
failure handling; no native throughput gain is claimed.
The combined fixture capture passes 360 tests with two live-listener cases
skipped; all 7,742 package Python sources, selected tests and protected artifacts
stay unchanged. Native training and actual listener qualification remain deferred.

The [durable private-publication handoff](../reports/autoencoder_durable_private_publication.md)
adds offline preparation for one explicit owner version and its registered
variant. Complete package bytes are CAS-staged before a small HF intent is
enqueued; an exact operation journal supports lost-response and restart recovery.
Strong reopening and fresh-destination restore preserve legacy/compact checkpoint
bytes without resolving a new head. Restoration does not claim or acknowledge
the intent. This keeps release hashing and copying out of the native worker's
training path, but adds release-boundary I/O and requires scheduler disk allowance.
It leaves upload approval, remote visibility/reconciliation and model qualification
to the later guarded consumer. No new training or bridge evaluation is performed.
Exact historical-byte recovery passed under unchanged sources. The later combined
execution passes 555 tests but is unqualified because its full-source guard
detects four concurrent logic-file edits. Protected artifacts and the new
publication code stayed unchanged; no guard was relaxed or native run repeated.
