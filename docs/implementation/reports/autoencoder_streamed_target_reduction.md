# Incremental hydration for worker-private target reduction

Implemented and qualified in 222 guarded offline cases, 2026-09-26. Native
training validation remains deferred. This work targets the rich-target allocation peak that limits safe
parallel training; it does not change target artifacts, training objectives,
bridge names, parser behavior or the meaning of a Lean admit.

## Measured reason for this change

The [previous native reduction experiment](autoencoder_worker_target_reduction.md)
lowered retained memory before training from 1,450.5 to 682.5 MiB, but reduced
workers still reached an observed lifetime peak of 1,556.1 MiB. They hydrated
the complete requested batch before deriving immutable evaluator values. That
peak prevents using the retained-memory reduction alone to justify more workers.

Those are historical measurements on the recorded source tree and six-target
bundle. They are not measurements of this implementation. The old complete-job
median changed only from 19.731 to 19.047 seconds, with one pair slightly slower.
Broader Arrow mapping also lacked a demonstrated complete-job benefit in the
subsequent [produced-corpus comparison](autoencoder_produced_corpus_arrow_training.md).
The immediate opportunity is reducing
simultaneously retained rich graphs while keeping numeric weight access local.

## Behavior and compatibility

The existing `reduce_native_targets` option remains false by default. Its
eligible native bundle path validates and checks eligibility for every target
without retaining all rich graphs, then rehydrates and reduces one target at a
time. Only the existing immutable worker-private capsules remain for training.
The full target bundle remains authoritative and reusable; capsules are neither
an artifact format nor verification authority.

The complete first pass is deliberate. The existing path validates all targets
before checking whole-batch eligibility and invoking the reducer's additional
document hashes. Full target validation already hashes each document; that
validation hashing remains mandatory in both passes. Reducing
an early target immediately could raise a hashing error before a later corrupt
target, or invoke reduction when a later unsupported target requires the whole
original mapping. The new path preserves those outcomes. An ineligible
batch falls back to full hydration, with no mixture of rich targets and capsules.

The bundle iterator retains the same configuration, sample, compressed and
expanded byte, codec, complete-target and source-text checks. Entire requested
membership is checked before selected shard reads. File identity is checked
through iteration and at exhaustion. Early iterator close must release its
private buffers; consumers that retain yielded targets remain responsible for
that memory. The ordinary `targets_for` API still returns its complete mapping.

## Cost and qualification

| Choice | Intended benefit | Cost or limit |
|---|---|---|
| Validate eligibility in a complete first pass | Preserve fallback and error ordering | Eligible targets decode twice; validation hashes run twice, followed by the existing reduction hash |
| Reduce one verified target at a time | Remove batch-sized rich-graph retention | Capsules, source samples and model state still occupy memory |
| Restore the caller's GC state before reduction and hashing | Preserve the existing GC boundary | Eligible deferred-GC batches perform N+1 explicit collections for N selected targets |
| Keep full artifacts and independent checks | Preserve semantics and reusable evidence | Does not remove artifact hashing, first-time bridge generation or codec validation |
| Keep the option off by default | Avoid treating a prototype as measured production behavior | Native qualification is required before recommending adoption or more workers |

`TargetBundle.iter_targets_for` yields complete validated `(sample_id, target)`
pairs. The worker closes each pass and releases each caller-held rich target
before advancing. The iterator releases its own reference on advance or close.
Telemetry distinguishes caller reference unlinking from iterator finalization;
cleanup of earlier graphs is included in subsequent hydration scopes. Complete
`target_load_seconds` includes both passes, reduction and cleanup. The reported
hydration total sums disjoint hydration scopes, rather than including reduction
again.

Offline tests compare outputs and failure behavior with the existing full
hydration/reduction path. They cover unsupported late targets, corrupt late
shards, class drift, early close, source/configuration changes, GC restoration
and absence of partial capsule installation. Object-lifetime checks establish
bounded rich-graph retention under the tested fixtures. They do not establish
native process RSS, bridge-on latency or parallel throughput.

## Offline evidence

All 222 selected cases passed with zero failures, errors or skips: 27 new worker
cases, 63 bundle cases (including 17 new iterator cases), 13 snapshot cases,
35 reducer cases, 28 reduction integration cases, 35 GC cases, 10 selected
injected-worker cases and 11 semantic/pilot cases. The last group includes the
authorized 24-hour deadline identity, unchanged historical case baselines,
the three required legal gates and empty-vocabulary abstention.

The [test receipt](evidence/autoencoder_control_plane_plan/campaign-streamed-target-reduction-tests-20260926-r1.json)
records 9.540 seconds of test wall time. The complete
[audit](evidence/autoencoder_control_plane_plan/campaign-streamed-target-reduction-audit-20260926-r1.json)
took 97.821 seconds, including a 60-second stability window and resource checks.
These durations are offline validation costs, not bridge-on or training timings.
All 7,778 package files and 1,300 dependencies remained unchanged across the
parent and child before/after snapshots. The captured
[source](evidence/autoencoder_control_plane_plan/campaign-streamed-target-reduction-sources-20260926-r1.json)
and [dependency](evidence/autoencoder_control_plane_plan/campaign-streamed-target-reduction-dependencies-20260926-r1.json)
maps also retain unrelated unexecuted context; they do not qualify those features.
Harness, protected checkpoints/receipts and prior retained claims passed their
guards. No native worker, checkpoint training, external prover or Lake build ran.

The retained [JUnit output](evidence/autoencoder_control_plane_plan/campaign-streamed-target-reduction-junit-20260926-r1.xml)
includes the three-target lifetime fixture: streaming performed six decodes,
retained at most one decoded target and released all six graphs. The same test
then observed three retained decoded targets through ordinary `targets_for`.
Capsule values, payloads, document hashes, order and negative zero match full
reduction. Separate bundle tests track both target and document lifetimes.
This is structural evidence on synthetic inputs, without a native memory claim.

Fresh reservation `2ee6923d8220468f99732cf5f390a713` and its host lease were
[released](evidence/autoencoder_control_plane_plan/campaign-streamed-target-reduction-release-20260926-r1.json)
after zero live owned processes were confirmed. Its 50 MB allowance included
30 MB for external fixtures; final charged attempt plus fixture allowance was
36,098,314 bytes. All previous failed claims remain retained. The campaign cap
remains 60 GB and the per-worker cap remains unchanged.

## Remaining qualification and delivery

Future native comparison must count both passes and all cleanup in complete-job
time. Preserve the exact checkpoint, sample count, ordered bridge names, prover
flag, metric-cache flag, worker count, sample-memory setting and projection
limits. Report cold preparation separately from shared-target hydration and
state-dependent evaluation. Do not infer a speedup from target count zero or
from the duration of these offline tests.

The corpus-delivery audit also found a separate gap: selected campaign packages
and the existing IR summary export do not provide a complete source-first federal
dataset. The next delivery integration should reuse the frozen source inventory,
partitions and embedding receipt sets to stream all declared rows, including
gaps and exclusions, into DuckDB-queryable Parquet. Constitution source selectors,
full semantic observations, Lake evidence, production DuckLake materialization
and Hugging Face delivery remain distinct unfinished work.

Only `lake build <Lib>` supplies a Lean admit. The Constitution remains
unformalized, and this work must not mark any Constitution span `roundtrip_ok`.
