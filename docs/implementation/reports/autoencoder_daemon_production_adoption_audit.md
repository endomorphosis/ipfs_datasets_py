# Production adoption of verified corpus inputs and candidate versions

Read-only code audit, 2026-09-25. This specifies the next integration after
[full-report reuse](autoencoder_daemon_shared_reports.md). Worker qualification
does not establish that the ordinary U.S. Code daemon uses those paths. This
audit adds no training run, model promotion, DuckLake activation or HF upload.
The Constitution remains unformalized; only `lake build <Lib>` is a Lean admit.

Follow-up: the [verified local input implementation](autoencoder_daemon_verified_inputs.md)
now addresses the first input/role boundary with an owner-exported immutable
descriptor and an offline daemon session. The findings below preserve the audit
baseline. Full cycle candidate adoption, sparse capture of every mutation,
mapped daemon state, and destination consumers remain later integrations.

The subsequent [native-cycle qualification](evidence/autoencoder_control_plane_plan/daemon-corpus-input-native-cycle-20260925-r1.json)
passes actual sampling, bridge evaluation, one rejected projection attempt,
default asynchronous snapshot completion and final checkpoint durability. It
does not claim an owner training lease or register a candidate. The
[owned-invocation plan](../plans/AUTOENCODER_DAEMON_OWNED_INVOCATION_PLAN.md)
refines section 2's first topology to one bounded native invocation: adopt the
final durable checkpoint after successful shutdown, covering shutdown mutations
as well as cycle mutations. Resident per-cycle handoff remains a later option.

## Findings that determine implementation order

| Boundary | Current code | Required next change |
|---|---|---|
| Corpus input | The daemon's `load_laws_table` uses remote `HfFileSystem`; `row_to_sample` does not supply an embedding. `USCodeParquetRecord.to_sample` consequently uses `mock:stable-sha256`. | Add an explicit verified local corpus session through the actual loader and sample factory. No mock or network fallback in that mode. |
| Dataset roles | Native sampling draws training and validation from one table. Fixed canaries become projection acceptance and supervisor validation inputs. | Enforce frozen training/validation partitions at sampling. Indexed canaries are reserved for representation promotion and must not become optimizer validation. |
| Input ownership | The worker verifies v6/v7 source, index, vector and producer closure; the coordinator additionally establishes registry artifact ownership. | Reuse both boundaries. Calling the standalone input verifier does not establish owner authority. |
| Candidate state | The daemon invokes projection without `accepted_patch_sink`; later TODO optimization, guidance and capacity compaction can also mutate state. | Register a complete immutable cycle candidate first. Projection patches alone cannot describe a normal daemon cycle. |
| Persistence | The daemon writes existing full checkpoints/component deltas. Component-delta serialization replaces whole changed components. | Preserve that distinction from accepted sparse row patches. Sparse authority requires exact replay of every mutation in the final cycle state. |
| Mapped inputs | Worker mappings own readers, file descriptors and memory maps. The daemon deep-copies samples for asynchronous snapshot evaluation. | Start with exact verified vector values in ordinary lists. Qualify explicit vector detachment and mapping lifetime before mapped daemon input. |
| External destinations | Registry outbox intents and consumer leases exist. No autoencoder consumer of `claim_outbox`/`ack_outbox` was found in package or ops callers. | Implement destination-specific commit/reconciliation and recovery; an outbox table alone is not a DuckLake or HF integration. |

Primary code: [daemon runner](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/uscode_modal_daemon_runner.py),
[dataset samples](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/uscode_dataset.py),
[worker verification and patch capture](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_training_worker.py),
[owner staging and replay](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_training_coordinator.py),
[registry](../../../ipfs_datasets_py/duckdb_control/autoencoder_registry.py),
[component checkpoint deltas](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder_checkpoint.py),
[mapped inputs](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_arrow_inputs.py).

The existing dataset test references `load_uscode_embedding_lookup` and a
`row_to_sample(..., embedding_lookup=...)` argument absent from the current
runner. That is a test/API discrepancy, not an implemented production vector
path. A first-vector-per-CID lookup also cannot substitute for exact source and
producer bindings. The published 1,491-vector audit still grants no training
eligibility to those vectors.

## 1. Verified local corpus session

Add an opt-in bounded descriptor for an immutable v6 input job artifact, its
SHA/size and read-only owner-registry resolution. Extract a shared verification
context from existing worker input validation; do not invoke training to load
inputs or duplicate a weaker subset of its checks. Bind source selectors, exact
text, citation, index, producer receipt and vector bytes. Construct native
samples explicitly; the ordinary row parser's text cleanup must not silently
change verified text.

Pass the context through real loading, sampling and sample construction calls.
Expose stable source-record IDs and indices. Extend sampling with separate
eligible indices for training and validation while preserving random-number
use, count limits, text caps and memory exclusions. Authorize the actual selected
IDs for their operation before use. Empty or insufficient partitions fail;
they do not trigger a new split seed or fallback to unverified rows.

Initially require `validation_canary_count=0` in indexed corpus mode. A later
explicit representation-promotion evaluation can consume indexed canaries.
Do not relabel a canary as ordinary validation to preserve the old option.
The existing six-record native fixture used its three validation records via
the daemon's fixed-validation mechanism; it does not qualify campaign-wide
canary policy or production sampling.

Keep v6's exact verified vectors as lists in this first integration. Bind input
and index identities plus ordered selected IDs to evaluation lineage, restart
state and summaries. Verify them before consumption, before persistence and at
shutdown. Verification failures suppress new authoritative checkpoint or
promotion writes for the unverified/provisional work; they do not undo earlier
completed valid writes or promotions. Tests must exercise real input functions offline, exact
vectors, no mock fallback, cross-role exclusions, exhausted partitions,
restart changes and failure suppression.

Current produced-vector receipts/Arrow batches have a 256-record limit and the
frozen index supports 65,536 records. Scale by an immutable catalog of bounded
batches under one index with lazy loading. Larger corpus runs require that
catalog; raising a batch cap or regenerating splits is not the implementation.

## 2. Registry-bound complete cycle candidates

The daemon owner adapter must bind the immutable base version and artifact
closure, loaded logical identity/revision, actual daemon configuration, actual
sampled source/vector identities and producer version. Do not silently translate
ordinary daemon settings into the narrower worker `TrainingConfig`.
Startup compaction also mutates state immediately after checkpoint loading.
Bind the pre-compaction base and include that mutation in the first complete
candidate, or register a separately verified anchor before sparse capture.

For the first topology, lease one bounded native invocation before startup and
give it an exclusive attempt directory. Keep the lease alive through snapshot
and writer drain, successful shutdown, final artifact verification and owner
completion. Submit the final immutable checkpoint, covering shutdown mutations
too. A resident per-cycle handoff at the post-input-guard boundary is a later
optimization; the cycle snapshot alone does not prove that final shutdown left
state unchanged.

Resolve completion through the existing lease/fence and operation-ID protocol,
with operation identities and exact payloads durably journaled before sending.
An expired lease or unresolved completion prevents authoritative registration
or promotion of the candidate. Cleanup and isolated local checkpoint writes do
not themselves grant that authority. Candidate durability and head promotion
remain separate. Snapshot eligibility is not registry promotion authority;
promotion still needs the owner's evaluation policy and version/generation
compare-and-swap, with metrics bound to the exact final candidate state.

The first integration intentionally pays full-candidate serialization. This
establishes one correct authority boundary before reducing transport bytes.
Qualify stale completion, response loss, owner restart, async snapshots,
rejected projection updates, later successful mutations and compaction. A
rejected projection does not imply the complete daemon cycle left state
unchanged.

## 3. Sparse capture, then optional mapped daemon state

The existing worker sink and portable patch codec already bind accepted updates
to their base/result identities, revisions, sequence and provenance. The owner
already independently replays them. Full-candidate mode compares the submitted
state directly; sparse mode verifies the reconstructed full-state identity,
serialized SHA/size and exact sparse manifest without requiring a full candidate
file. Bounded
checkpoint inventory preparation no longer reconstructs the weight chain;
semantic replay still happens in worker/owner execution.

Add daemon patch capture first as an audit alongside complete candidates.
Ordered replay must reproduce the entire final cycle state. Sparse persistence
can then be enabled for an explicitly qualified projection-only configuration,
or after TODO, guidance, compaction and every other mutation participate in
the same replay contract. Preserve full snapshots for uncovered cycles and
record why; never silently omit mutations or describe component replacement as
row-sparse capture.

Only then evaluate mapped input/feature-weight state in the daemon. Explicitly
detach verified vector values at async snapshot boundaries and retain mappings
for all other live consumers. Test copying, shutdown, cancellation, rejected
updates and snapshot overlap. Other weight families remain Python state until
separately implemented. Do not apply worker-only garbage-collection policies to
a daemon with background writers without a separate concurrency argument.

## 4. DuckLake and Hugging Face consumers

Use the existing DuckDB owner for leases and short control transactions. The
current coordinator uses local typed owner calls; Quack remains prototype-gated
and needs production qualification before transporting those closed commands.
Workers read local immutable bases and
submit sealed updates; per-weight remote SQL would add control-plane traffic to
the training loop. Different language/model branches remain independent
candidates. Registering a language does not qualify a language frontend.

Add a DuckLake outbox consumer that records the external commit identity and
reconciles a crash after commit but before acknowledgement. Add equivalent HF
parent/commit reconciliation after deterministic local packaging. Both need
artifact closure, retention pins, storage reservations and bounded retries.
Keep uncertain delivery explicit rather than training or publishing a second
version after response loss.

The [current HF builder](../../../ipfs_datasets_py/huggingface/autoencoder_release.py)
produces offline private exact-resume plans. It rejects sparse manifests until
verified full materialization and registration. It does not upload. An eventual
public legal dataset needs a separate approved publication profile; private
resume state may retain raw feature keys and sample memory. Publish source,
gap, attempted-IR and Lake-backed proof status distinctly. Constitution rows
remain `formalized=false` and never `roundtrip_ok`.

## Opportunity cost and evidence gates

| Work | Main benefit | Cost or remaining uncertainty | Gate before wider adoption |
|---|---|---|---|
| Full-report reuse | Avoid rebuilding reports separately for target scoring and diagnostics | Preparation, hydration, large Python graphs and producer invalidation; actual daemon speed comparison is still unqualified | Fresh cold/shared complete-cycle comparison, exact native outputs and nonzero targets |
| Verified production inputs | Makes bounded worker evidence usable through the actual daemon | Partition enforcement, source authority and embedding closure | Real-loader offline tests and native source/vector/index receipt |
| Full-cycle owner candidate | One durable authority for versions and recovery | Full serialization remains initially | Crash/reply-loss/fencing tests over all daemon mutation paths |
| Sparse daemon persistence | Fewer bytes and less snapshot churn | Replay and compaction can cost more than small updates save | Complete-cycle replay identity plus measured bytes and persistence wall time |
| Arrow daemon integration | Shared numeric buffers and potentially lower private memory | Snapshot copies, overlay lookups, mapping lifetime and nonnumeric state | Exact decisions, PSS/private memory and complete-cycle throughput at bounded concurrency |
| DuckLake/HF consumers | Durable searchable history and distributable releases | Cross-system recovery, capacity, privacy and retention | Commit-before-ack recovery, exact package closure and explicit publication configuration |

The existing small worker workload had negligible projection time relative to
target work; mapped inputs did not improve complete-job time. Start with one
and two independent candidates under measured memory/storage reservations.
More workers, Arrow by default, or a CUDA backend do not follow from completing
the control schema. Report preparation separately from reuse and include it in
amortized campaign cost; do not extrapolate six selected records to all federal
laws. Continue complete source accounting and semantic-gap work independently
of optimizer throughput.

The reserved two-minute check is recorded in
[its immutable receipt](../../../workspace/test-logs/federal-corpus-audits/reserved-validation-20260925/receipt.json).
Source remained unchanged and the protected checkpoint matched its pin, but
the combined regression returned 233 passes and eight capture-observation
parity failures. The [investigation](../../../workspace/test-logs/federal-corpus-audits/reserved-validation-20260925/observation-investigation/investigation.json)
identified a frozen test reference that predates the current actor-capture stage.
The original reference and failures remain preserved; a separately versioned
actor-aware reference now checks exact current output with observation enabled
and disabled, including actor/triple order, duplicates, bounds and failures.
Only tests changed. The [corrected combined regression](../../../workspace/test-logs/federal-corpus-audits/reserved-validation-20260925/corrected-combined-receipt.json)
passes 248 checks, including the 31 mandatory semantic/pilot checks, with all
7,720 package source files unchanged during that run and the protected pin
intact. This short check neither establishes native speed nor supersedes
historical native receipts.

The investigation separately records an existing actor-import fallback defect:
if importing `embedded_actor` raises `ImportError`, capture records suppression
and then calls the unbound `actor_triples` name. That path still raises
`UnboundLocalError`; this test-only correction does not fix it or claim complete
capture-failure coverage. Capture reuse remains unqualified.
