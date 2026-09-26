# Worker-private target retention after full validation

Qualified on 2026-09-25, with the option **off by default**. Complete target
artifacts and validation remain unchanged. On one fixed U.S. Code batch,
retaining immutable evaluator values after hydration reduced memory before
training by 53% and initial bridge-on evaluation time by 16%. The complete-job
median improved 3.5%, but one of the two pairs was slightly slower. This is
primarily a measured memory improvement, with a modest and noisy job-time
result. It is not a new accepted weight update or corpus formalization.

The [native receipt](evidence/autoencoder_control_plane_plan/worker-target-reduction-native-20260925.json)
contains four independent owner-managed jobs, complete worker receipts, exact
comparison exemptions, retained source snapshots and before/after producer
guards. The [benchmark](../../../scripts/ops/legal_ir/benchmark_worker_target_reduction.py)
uses the same freshly prepared six-target bundle in full/reduced/reduced/full
order. It does not reuse historical target bytes.

## Implementation and boundaries

[`run_training_jobs`](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_training_coordinator.py)
accepts `reduce_native_targets=False`, independently of
`defer_target_hydration_gc`. Both require actual booleans; target reduction
rejects injected executors, workers and trainers. Its private spawn entry
requires an exact native bundle, the main Python thread and no other Python
threads. Existing public worker entrypoints retain their previous behavior.

The [worker](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_training_worker.py)
first runs the unchanged artifact/configuration/sample checks and complete
requested-target hydration. The [private helper](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/_autoencoder_prepared_targets.py)
then checks every target before converting any. Exact native targets with
ordinary declared fields and unchanged local class/method contracts receive
detached, immutable numeric mappings, bridge names, acceptance and document
identity/hash. The hash includes existing timestamp metadata. Rich targets,
subclasses, attached grammar fields, overrides and unsupported containers
retain the identical original mapping. Hashing errors propagate.

The worker releases its original graphs before training. Capsules are not
accepted by the artifact codec and have no validation or admission authority.
The complete bundle remains the reusable artifact. Neither the native
evaluator nor ontology capture was changed: each evaluation still constructs
sample-dependent structural targets, preserves subset/order behavior, primes
numeric caches and evaluates grammar on its existing applicable path.

These are worker-local mutation guards, not global bytecode attestation.
Strict bundle decoding supplies the ordinary nested-value prerequisite; the
helper is not a general validator for arbitrary caller-owned object graphs.
Existing restrictions on code loaded before first-process verification remain
explicit. Conservative class-shape guards can disable the option after benign
future class changes; receipts retain the reason. Initial full hydration still
occurs, so its memory peak and validation cost remain.

## Native measurement

Three training spans and three disjoint validation spans use the frozen,
producer-bound v7 selection. This validation set is not a held-out canary.
All jobs use `modal_frame_logic`, `deontic_norms`, `fol_tdfol`, `cec_dcec`,
`external_prover_router`; external provers false, metric disk cache 0, one
bridge worker, one adapter worker and one training worker. Sample memory is
false, temperature 0, CPU `python_sparse_batch`, one epoch, one update family,
one line-search attempt and the existing 180-second cooperative budget.
Arrow inputs/feature weights and deferred hydration GC are identical in both
arms. No backend, context limit, weights or bridge set changed.

| Median wall time | Full runtime targets | Reduced runtime targets |
| --- | ---: | ---: |
| Complete owner job, including process cleanup and durable verification | 19.731 s | 19.047 s |
| Complete owner job per training span, including validation work | 6.577 s | 6.349 s |
| Worker execution | 15.671 s | 15.347 s |
| Training loop | 8.693 s | 7.132 s |
| Initial bridge-on evaluation, three validation targets | 4.158 s | 3.475 s |
| Initial bridge-on evaluation per validation span | 1.386 s | 1.158 s |
| Hydration including deferred-GC collection, six targets | 2.892 s | 2.958 s |
| Added reduction initialization, preparation and release | 0 | 1.016 s |

Reduction adds approximately 0.728 seconds of hashing and 0.242 seconds of
reference release. These costs precede the training clock but remain included
in complete owner time. Pair one changed owner time from 19.087 to 19.143
seconds; pair two changed 20.375 to 18.951 seconds. Both evaluation comparisons
improved. Two pairs on a shared host do not establish a stable general
throughput percentage; OS cache and host contention were uncontrolled.

| Median process memory | Full | Reduced |
| --- | ---: | ---: |
| RSS immediately before training | 1,450.5 MiB | 682.5 MiB |
| PSS immediately before training | 1,410.5 MiB | 642.5 MiB |
| RSS after training, before serialization | 1,612.7 MiB | 867.5 MiB |
| Observed lifetime peak at that point | 1,696.6 MiB | 1,556.1 MiB |

The reduced workers still reached about 1,556 MiB before training. Do not
double concurrency from the 53% retained-RSS reduction: simultaneous hydration
still has a much larger peak. The observations are Linux process pages, not
inferred Arrow-buffer sizes or a claim about all future allocation peaks.

Preparation ran in a fresh process with metric disk cache disabled. Production
preparation took 59.254 seconds for six spans, or 9.876 seconds/span; dispatch
including the preparation process took 61.028 seconds, or 10.171 seconds/span.
Generation alone took 49.658 seconds, or 8.276 seconds/span. All six reports
contained all five implemented bridges and zero failures. The harness copies
bounded diagnostics at the preparation generator boundary and preserves
failures; the four training workers have no callable wrappers. These are not
an old/new cold-preparation comparison. Worker timings above use verified
shared targets and exclude that separately reported preparation cost.

The sealed bundle is 12,838,102 bytes, SHA-256
`72305e752a69ca2cc06ee45db0d59313cda29c356b104066eab6f0b733531cdb`.
All four workers independently validated their complete requested targets.
All 7,714 package-source bindings and dependency configuration stayed stable
through the native run. The pinned 25,895,338-byte restart12 checkpoint and
registry head were unchanged; exact receipts survived owner restart.

## Correctness evidence

Every worker field is compared except explicitly enumerated clocks,
memory/GC observations, run provenance and reduction telemetry. Numeric
results, document hashes, grammar/rejection fields, profiler counters/events,
state identities and decoded sparse artifacts match. There is no timestamp
exemption. Native ontology comparison covers the persisted sample order,
counts, outcomes and diagnostics; full captured records/triples are not in
those receipts and were not compared by this benchmark. Synthetic integration
tests separately check the capture loop with deterministic extraction leaves.

All four optimizer decisions rejected the update: zero accepted epochs and
zero patch segments. Accepted sparse replay has existing regression coverage;
this corpus experiment does not newly qualify an accepted training update.

Validation totals **460 distinct pytest checks**: 35 new reducer tests,
28 new integration tests, and 397 existing worker/coordinator, codec, GC,
grammar, semantic and pilot checks. The initial broad run had 396 passes and
one fixture-location failure: its fake outside parser was accidentally placed
inside the canonical tree by the audit's `--basetemp`. Rerunning that one check
with an external temporary directory passed without a code or test change.
The initial integration fixture also needed to respect the existing empty
batch behavior; its failed log remains retained. The
[audit directory](../../../workspace/test-logs/federal-corpus-audits/native-target-reduction-20260925)
contains the original files, scoped patch and test receipts. The
[integration receipt](../../../workspace/test-logs/federal-corpus-audits/target-reduction-integration-20260925/validation.json)
and [15 harness smoke checks](evidence/autoencoder_control_plane_plan/worker-target-reduction-harness-smoke-20260925.json)
record their separate scope. All mandatory semantics remain unchanged,
including empty-vocabulary abstention and non-renderable `within_duration`.
The [final validation inventory](evidence/autoencoder_control_plane_plan/worker-target-reduction-final-validation-20260925.json)
binds the tested implementation, receipts, document links, protected checkpoint
and the package-source observation made after this report was written.

## Opportunity cost and next integration

Keep this option available for bounded native workers and off by default.
It avoids retaining large graphs during training without changing artifact
trust, storage or evaluator semantics. Its added preparation consumes much of
the evaluation-time saving for one epoch. Longer jobs and larger bounded
batches need their own qualification, particularly memory peaks. A later
streaming loader could reduce initial peak memory, but would require a new
independent validation and lifetime study.

Cold preparation still costs more than an entire shared-target job here.
Reuse complete compatible targets before expanding weight mapping or moving
numeric lookups behind Quack. The
[daemon integration audit](autoencoder_daemon_shared_target_integration_audit.md)
identifies the next deployment gap: verified full-target handoff on the actual
daemon path, measured against its existing warm caches, followed by explicit
owner-managed candidate adoption. Arrow remains optional, and DuckLake
materialization and Hugging Face release stay outside the training loop.

The [end-to-end plan](../plans/FEDERAL_LAW_END_TO_END_TRAINING_PLAN.md) retains
full-source inventory, official-source authentication, global splits,
semantic coverage and actual Lake evidence as separate prerequisites.
No model was promoted, no release published and no production DuckLake catalog
activated. The Constitution remains unformalized, with no new `roundtrip_ok`.
Only `lake build <Lib>` constitutes a Lean admit.
