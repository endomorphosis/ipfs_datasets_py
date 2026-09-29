# Hardware-aware training: coordinator capacity and lower worker overhead

This change accounts for coordinator CPU while reducing sparse-state loading,
first-target import work, and fresh storage inventories. It also rejects
contradictory temporal metadata before generating logic-family artifacts.
Qualification thresholds and optimizer mathematics are unchanged.

Only `lake build Legal` admits generated Lean. The current renderer proves
source-locked integer minimum-duration patterns; it does not prove the complete
legal IR or the autoencoder. Parsing six logic projections establishes syntax,
not complete semantics for those families. The Constitution remains unformalized.

## Implemented changes

The training and inference capacity policies now reserve one CPU slot for the
coordinator. Hardware, affinity, cgroup, scheduler and parent-reservation limits
each include that cost. Nested workers consume the full parent envelope and
subtract the coordinator once, avoiding both overcommit and double charging.
For eight available scheduler CPUs and sufficient RAM/process slots, automatic
admission plans seven model workers plus the coordinator. Fleet admission also
includes the outer controller. These are cooperative reservations, not kernel
quotas; runtime resource observations remain necessary.
An execution group requires at least two available CPU slots; a one-slot
allocation now defers. This conservative accounting trades single-slot execution
for explicit coordinator headroom.

Stable logical lanes remain separate from concurrent execution. Keep
`--workers 0 --parallel-workers 0` for 32 logical lanes and automatic admission;
`--parallel-workers 4` caps execution without changing lane identities. Pending
work, `--max-batches`, memory, process slots, storage and other reservations can
reduce the actual width. Default batch counts have not been increased merely to
produce a larger worker count. Inference and training retain separate gates.

State tracking now recognizes exact built-in scalar types before generic
mapping/sequence dispatch. Subclasses still take the original dispatch path.
Nested tracking, mutation callbacks, revision identity, sparse patch replay,
Arrow mappings and rejection of non-finite state hashes remain intact. A sealed
same-process ABBA replay comparison improved from 2.4314 to 1.8237 seconds
(25.0%), with identical materialized bytes, logical identities and revisions.
Each measured replay still reads and verifies its full artifact closure.
This component benchmark injects the reference function explicitly; it is not
a native qualification or whole-route timing. Loaded RSS remained about 220 MB.

The modal package now loads public exports on first access instead of eagerly
importing optional integrations. Tests preserve all 261 historical objects,
the exact 255-entry `__all__`, object identity, submodule access, star imports
and concurrent first access. `vars(package)` before first access intentionally
does not contain every deferred value. A fresh-process first structural target
took 0.0298 seconds, with an unchanged payload hash; the earlier profile spent
about 2.16 seconds in its eager import path. The new subprocess took 0.1371
seconds overall. There was no hidden prewarm, model load or Lake execution.

The resource inventory reuses lexical path components within one traversal.
It still performs fresh metadata and root-identity checks at every previous
boundary; file sizes, identities and absence are not cached. Paired full-root
inventories averaged 3.4152 seconds before and 2.0419 after (40.2% lower).
All four observed exactly 47,092,265,113 bytes, 226,875 entries, 3,892 symlinks
and 30 special files. Tests verify syscall ordering and replacement, deletion,
symlink and sibling-prefix cases. Historical claims and resource caps remain.

Family qualification rejects different `(temporal_kind, quantity)` values
attached to the same canonical temporal atom. The previous path could emit
conflicting frame facts for quantities 20 and 21 or for minimum versus within
duration. Identical duplicates and distinct temporal atoms remain valid.
This closes an inconsistent-IR acceptance path; it does not lower a metric
threshold or reinterpret a syntax result as proof.

## Native observations and provenance limits

The first two native runs used eight synthetic minimum-duration training spans, one
disjoint but repeatedly used 30-day tuning span, the protected restart12 seed,
32 logical lanes, two four-worker waves, one epoch, one ordinary line-search
attempt and all five update families. They used Python sparse batch updates,
mock stable-hash embeddings, a 120-second optimizer bound and no optional
composed refinement. These fixtures are not held-out federal-law evidence.

| Observation | Whole-route seconds | Seconds/training span | Qualified rows |
| --- | ---: | ---: | ---: |
| Earlier baseline | 157.596 | 19.700 | 3/8 |
| Updated workspace | 113.956 | 14.245 | 3/8 |

These are observations, **not an isolated causal speed comparison**. Four
unrelated package changes separate the two source bindings. The updated run
sealed its own start/end source and checkpoint checks, but a later edit to
`entity_cache.py` prevented the independent audit from matching that producer.
Its audit remains failed: 793 checks passed and two complete-producer checks
failed. The baseline audit passed all 779 checks. The comparison preserves
136 successful per-row equality checks, including exact weights, selected
updates, objectives, metrics, dispositions, family artifacts and Lean sources;
the overall comparison remains failed because the updated audit prerequisite
failed. No speed claim is enabled by those receipts.

Each run produced 16 successful `lake build Legal` receipts and 96 artifacts
across FOL, deontic FOL, temporal FOL, deontic temporal FOL, DCEC and frame logic.
Five rows still failed the existing reconstruction qualification despite their
accepted epochs and successful numeric proofs. Those failures remain failures.
The source mismatch does not turn these old artifacts into qualification of
the current checkout or of the prepared-main tree.

The bridge timing appendix and raw receipts retain all five names:
`modal_frame_logic`, `deontic_norms`, `fol_tdfol`, `cec_dcec`, and
`external_prover_router`. Provers were false, metric disk cache was 0, target
workers were 1, and sample memory was false. Each first bridge-on evaluation
used one tuning sample and produced one legal-IR target. Processes and target
builds were cold; operating-system caches were uncontrolled. Later in-process
reuse is identified separately. No bridge-off result is used as an IR timing.
First-evaluation wall times ranged from 4.573 to 6.156 seconds in the baseline
and 4.149 to 4.436 seconds in the updated run, subject to the provenance limits
above. Polled group CPU peaked at 4.284 cores against the old four-slot
reservation, versus 4.290 against the new five-slot reservation. Sampled peak
group RSS was 5.51 GB and 4.73 GB respectively; polling misses short-lived
processes and can count shared pages more than once.

## Matched automatic-scaling comparison

A fresh four-worker run and an automatic run subsequently completed with the
same full producer manifest, inputs, protected seed and training settings. Both
independent native audits passed all 795 checks; their exact-result comparison
passed all 143 checks. Each retained the same eight candidate weights, selected
updates, metrics, three qualified rows, five blocked rows, 16 Lake builds and
96 family artifacts. The 32 logical lanes remained unchanged.

| Same-source run | Dispatch widths | Wall seconds | Seconds/span | Reserved CPUs | Sampled peak RSS, decimal GB |
| --- | --- | ---: | ---: | ---: | ---: |
| Four-worker ceiling | 4, 4 | 112.923 | 14.115 | 5 | 4.73 |
| Automatic admission | 7, 1 | 108.266 | 13.533 | 8 | 7.92 |

The automatic route was 4.12% faster in this single sequential comparison.
That is a modest observation, not a repeated benchmark or linear-scaling
guarantee. It used 67% more sampled peak RSS. Reserved CPU slots multiplied by
whole-route wall time increased about 53%; this is an allocation proxy, not
measured CPU consumption. Both reserved 12,288 MiB and 750 MB of
storage. Group CPU peaks were 4.303 and 7.505 cores, within their respective
five- and eight-slot envelopes. A four-worker ceiling remains a useful choice
when other workloads need capacity; maximum allowed concurrency is not
necessarily the best resource tradeoff for a small batch.

First one-sample bridge-on evaluations ranged from 4.347 to 4.837 seconds for
four workers and 4.097 to 4.477 seconds for automatic admission. All five bridge
names and prover/cache/worker/sample-memory settings are as listed above;
each evaluation produced one native target. Both routes were process-cold with
disk target cache disabled, while operating-system caches remained uncontrolled.
Worker dispatch occupied 36.651 versus 35.799 seconds, and serial qualification
35.339 versus 33.221 seconds. Qualification timing variation accounts for part
of the small whole-route difference; this experiment cannot establish a robust
causal scaling curve.

The first automatic attempt stopped before launching a worker because storage
admission exceeded the shared 80 GB cap. Its 2.311-second duration is excluded
from training timings. A subsequent fresh read-only inventory found 3.079 GB
headroom, so the retry used the identical 750 MB reservation. No cap increase,
retained-claim release or deletion was used. The failed admission did not save
its inventory, so its exact transient headroom cannot be reconstructed.

## Validation and publication scope

The workspace readiness suite executed 938 passing tests, but its full-source
guard failed because three unrelated package files changed during the suite.
The fourth unrelated file, `lean_units.py`, changed before that suite began.
The exact reconstructed before/after manifests and original failed receipt are
retained. They are not relabeled as a stable-source pass.

Focused checks passed 197 tracking/identity/Arrow tests, 133 inventory and lock
tests, 116 capacity/inference/fleet tests and 55 lazy-export/family cases. The
required obligation, prohibition, within-duration and minimum-duration gates
passed, including empty-vocabulary abstention and non-renderable within duration.
The five-case historical pilot remains green at forward 0.920 and cycle 1.000.
A broader canonical suite passed 126, skipped 13 and failed one pre-existing
UI bridge registry test. The same missing UI loss names fail with the original
eager initializer; this is recorded separately from the five training bridges.

The exact prepared-main integration suite passed **790 tests across 24 files**
in 40.05 seconds, with no failures, errors or skips. Source/dependency hashes,
module origins and live checkout/index preservation all passed. The harness
initially omitted the accelerator dependency and failed during collection;
that original failure is retained. The corrected harness exports exact
`ipfs_accelerate_py` Gitlink `5306d49957bba7444a31639584e26378f3e3fb19`
from an existing local object store. It does not fetch dependencies or substitute
the current editable install. These are source integration tests, not native
Lake qualification of main.

The publication uses explicit source/test paths and a private Git index. Its
source audit compares the captured native mapping, current workspace and
prepared main without rewriting unrelated edits. There are 20 superproject
source differences from captured native to prepared main and 565 unexpanded
Git-linked Python paths. Six explicitly bound native dependencies differ,
including the parser/compiler/decompiler and a pre-existing autoencoder edit.
Consequently native results belong to their workspace hashes; prepared-main
integration tests are separate evidence. This change does not publish weights,
upload Hub rows, or promote a checkpoint. The archived seed is unchanged.
All four owned native reservations were released, all 160 historical ledger records
and 61 retained claims were preserved, and the campaign/worker storage caps
remain 80 GB/50 GB. The closeout reads ledger state; it is not a fresh headroom
census.

## Remaining work and opportunity cost

Further throughput studies need repeated representative batches and stable
source bindings through both execution and audit. The actual host's read-only
scheduler snapshot selected seven workers with
12,288 MiB requested memory, eight pending jobs, eight available CPU slots and
64 process slots. Its complete estimate is eight CPU slots, 10,112 MiB and 11
child-process slots. That advisory plan neither acquires a reservation nor
certifies storage headroom.

Serial qualification cost 49.58 seconds in the eight-row baseline. A useful
next experiment is a bounded process pool for that phase, with Lake/Lean CPU,
RAM and process costs reserved independently and the parent retaining DuckDB
ownership. Threads are unsuitable for the current environment-mutating worker
setup. Parallel proof work must preserve per-row source seals, deadlines,
immutable artifacts and failure disposition; otherwise faster dispatch could
weaken the evidence.
Phase-specific CPU reservations are another opportunity: the current complete
group retains its CPU envelope during serial qualification. Releasing idle
worker capacity could help concurrent campaigns, but requires atomic lease
resize/reacquisition and cancellation tests before adoption.

Keep immutable Arrow-backed baselines local to workers and send sparse deltas
through the existing owner/Quack interface. These changes reduce replay overhead
without moving mutable training state into shared DuckDB transactions. Continue
to bind each delta to its exact parent and source, reconcile centrally, and let
qualified publication govern subsequent machines' pulls. Concurrent learning
does not imply arbitrary simultaneous mutation of a DuckDB file.

Shared targets remain opt-in: the preceding four-row experiment cost 23.1
seconds to prepare and saved only 1.4 seconds per consumer. Repeated use with
unchanged bindings can amortize that cost; a fresh tiny batch cannot. Retained
workers and CUDA need new profiles before becoming defaults. Representative
US Code batches and a genuinely untouched validation set are still needed
before claiming training quality or law-scale throughput improvements.

Detailed commands, original failures, measurements, source maps, generated
Lean and test results are in
[`evidence/autoencoder-parallel-20260929`](evidence/autoencoder-parallel-20260929).
