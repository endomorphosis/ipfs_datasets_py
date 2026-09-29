# Training overhead, shared targets, and bounded reconstruction refinement

This change reduces measured owner overhead while preserving qualification.
It also adds an explicit shared-target preparation command and an opt-in
optimizer refinement. Neither a bridge target nor an accepted epoch is an
admission. Actual `lake build Legal` remains the only Lean admit, and the current
renderer proves source-locked numeric minimum-duration patterns. Six syntax
projections do not prove complete legal, temporal, cognitive, or event semantics.
The Constitution remains unformalized.

## Why these changes

The previous four-span route took 111.801 seconds, with 50.108 seconds outside
measured worker dispatch and qualification. Scheduler admission wait was
negligible; the owner consumed substantial CPU between worker waves. A new
owner cProfile run found 27 full package manifests, plus repeated candidate
loading/replay. Its 197.893-second instrumented duration is not a speed baseline.

A full-content manifest prototype took 0.181–0.185 seconds versus 0.598–0.607
seconds for the old traversal, with identical hashes over 7,832 Python files.
The implementation uses directory descriptors instead of repeatedly resolving
all ancestors for each file. It still reads and hashes every source at every
existing guard boundary. There is no stat-based hash cache. Matching symlink
substitution, special files and mutation during reads fail closed. The portable
fallback retains the previous traversal. Neither implementation attests already
loaded bytecode.

Final resource accounting previously scanned the shared roots twice in adjacent
calls. Each read-only scan measured about 3.14 seconds. The new `finalize` method
uses one fresh inventory under the ledger lock, checks the full outstanding
claim before releasing it, verifies the attempt identity and dead process group,
and preserves failed observations and retained claims. Existing release/recovery
APIs remain unchanged. The 80 GB campaign cap and 50 GB worker ceiling remain.

## Hardware and optimizer controls

`--workers` remains the stable logical lane ceiling. The new
`--parallel-workers` independently caps concurrent passes; zero uses existing
CPU, affinity, cgroup, RAM, process-slot, pending-work and storage admission.
Changing this ceiling does not change lane placement or gradient settings.
Fresh workers remain default; earlier whole-route measurements did not support
enabling retained workers by default. No CUDA backend, model download, context
window or temperature change is involved.

`--composed-refinement-attempts 1..3` explicitly enables an additional bounded
search after a strictly accepted candidate. Default zero preserves existing
model calls and archived job/config identities. The refinement starts each trial
from the same selected patch, applies a training-only embedding update, then
requires all existing validation guards, at least the selected validation
objective improvement, and strictly better finite training reconstruction.
There are no validation gradients or lowered qualification thresholds.

The extra budget is separate from ordinary line search, and every phase stays
under the existing time limit. Exceptions and rejected trials roll back. A
completed winner survives a later timeout. The current opt-in requires nonempty
disjoint tuning validation and zero L2; nonzero L2 needs separate validation.
Validation is repeatedly used for selection, not an independent canary.
Training reconstruction measurements used for refinement are explicitly
bridge-off measurements; they must not be reported as legal-IR timings.

The motivating failures already tried all five update families. Pure embedding
updates could not improve an already-perfect validation reconstruction objective;
some instead crossed an existing reconstruction projection boundary and harmed
validation. Increasing line-search count alone would not make a zero-improvement
candidate eligible. The composed search preserves the selected IR update's gain
while testing an additional training improvement. The inherited reconstruction
projection and success metrics are unchanged.

## Shared target command

`python scripts/ops/legal_ir/prepare_shared_autoencoder_targets.py --help`
describes a bounded local producer using the existing target-bundle format.
It accepts training and disjoint validation JSONL, preserves exact normalized
sample identity and source bindings, and emits the existing runner's
`--shared-targets` / `--target-snapshot-id` handoff. It does not produce weights,
train a model or grant admission. Both source changes and incomplete bundles
remain errors in the existing worker verification path.

The producer uses all five bridges (`modal_frame_logic`, `deontic_norms`,
`fol_tdfol`, `cec_dcec`, `external_prover_router`), provers false, disk cache 0,
one target worker and no sample memory. It uses an owned resource reservation,
a child deadline, bounded inputs/output files, and failure retention. `--plan`
performs no target build or reservation. End-to-end comparisons must include
preparation, source checks, worker hydration and qualification. A warm consumer
alone is not a cold legal-IR result.

## Evidence scope

Native examples use the protected restart12 checkpoint and synthetic
minimum-duration sentences with mock stable-hash embeddings. These are pipeline
and optimizer experiments, not evidence that federal laws generalize or that the
Constitution is formalized. Successful numeric Lake builds apply only to their
sealed generated sources, not the checkpoint or the complete IR.

The final workspace readiness suite passed 828 tests. The independent concurrency
ceiling also passed 25 focused CLI tests. Actual native measurements and their source
bindings are retained separately under the dated evidence directory. Package
changes require new native source bindings; results are never silently relabeled
as belonging to another source tree or clean main checkout.

## Native comparison

All runs use four synthetic training spans, one disjoint but repeatedly used
30-day tuning span, the same protected 25,895,338-byte checkpoint, 32 stable
logical lanes, one epoch, one ordinary line-search attempt, all five update
families, Python sparse batch updates and a 120-second optimizer deadline.
The earlier 111.801-second route used different logical lanes; it motivated
profiling but is not the baseline for the speed claims below.

| Run | Concurrent passes | Full wall seconds | Wall seconds/span | Qualified spans | Sampled peak group RSS, decimal GB |
| --- | ---: | ---: | ---: | ---: | ---: |
| Old traversal and adjacent accounting | 2 | 97.799 | 24.450 | 2/4 | 3.30 |
| Full-content traversal and atomic accounting | 2 | 84.454 | 21.114 | 2/4 | 3.27 |
| Same optimized path, higher concurrency ceiling | 4 | 71.785 | 17.946 | 2/4 | 4.79 |
| Four passes with three optional refinement trials | 4 | 76.139 | 19.035 | 3/4 | 4.82 |

The overhead changes saved 13.6% in the two-pass comparison. Raising the ceiling
from two to four saved a further 15.0%, for 26.6% versus the original comparison.
These are single sequential runs on this host, not a repeated benchmark or a
promise of linear scaling. Both parity audits passed all 74 checks, including
exact parent and candidate weights, selected updates, losses, qualification
outcomes, logic artifacts and generated Lean sources. The scheduler still
limits actual dispatch by hardware and resource reservations.

The first bridge-on evaluation in each fresh worker handled the one repeated
30-day tuning sample and produced one legal-IR target. Ranges were 4.400–4.660 seconds for baseline,
4.526–4.583 for optimized, 4.627–4.679 for four-pass scaled, and 4.597–5.108 for
refined. Every run used `modal_frame_logic`, `deontic_norms`, `fol_tdfol`,
`cec_dcec`, `external_prover_router`; provers false, disk cache 0, one bridge
worker, and sample memory false. These evaluations were process-cold with a
native target build; operating-system caches were uncontrolled. Later in-process
target reuse is identified separately in the receipts. The observed speed gain
comes from owner overhead and concurrency, not a cheaper bridge measurement.

The optional refinement fixed the recorded reconstruction gate on the 23-day
fixture without sacrificing the selected validation objective gain. All four
parents and comparison settings matched the default run. It added about 4.35
seconds at four-way concurrency. The 22-day fixture remains blocked: the largest
nudge regressed validation, while smaller nudges produced no training improvement.
The two initially passing fixtures correctly rejected unnecessary refinement.
These discontinuous cosine/MSE changes arise from the inherited target-aware
reconstruction projection, so they are not evidence of generalization or an
independent semantic improvement. The default remains zero refinement attempts.

Each completed run produced eight successful `lake build Legal` receipts and
48 syntax artifacts across FOL, deontic FOL, temporal FOL, deontic temporal FOL,
DCEC and frame logic, covering training and tuning rows. Those numeric proofs
and syntax checks did not override reconstruction failures. Source-locked
threshold proofs and typed temporal fields remain distinct from complete
semantics for each projected family.

## Shared targets and remaining opportunity cost

The fresh producer built all five unique targets (four training rows plus the
validation row) in 23.067 seconds including process startup, source guards,
bundle verification and final accounting: 4.613 seconds per unique span. Native
target calls took 9.309 seconds within that route. The artifact was 2,299,411
bytes. All bridges, prover/cache flags, target-worker count and sample-memory
settings matched the private-target route.

The four-worker shared consumer took 70.374 seconds (17.594 seconds/training
span), with 4.43 GB sampled peak group RSS and the same 2/4 qualifications. Its
first one-row bridge-on evaluations took 2.404–2.477 seconds, each with one legal-IR
target hydrated from the bundle and zero native target builds. These are warm
target evaluations in fresh processes, not cold compiler timings. Across workers,
hydration summed to 0.856 seconds; concurrent phase sums are not route wall time.

Preparation plus one consumer cost 93.441 seconds, 30.2% slower than the matched
private-target route. The consumer saving was only 1.411 seconds. At those
single-run rates, preparation first amortizes on the seventeenth full four-row
reuse with unchanged source/input bindings. That estimate is especially sensitive
to noise and is not a claim for production-sized batches. Shared targets remain
an explicit option for repeated work; they should not become the tiny-batch
default. Source changes still invalidate their producer binding.

The remaining owner costs include source verification, candidate loading and
sparse replay, and strict storage accounting. Further work should profile those
costs on representative law batches before adding retained model state or a CUDA
backend. Immutable shared targets can reduce repeated CPU work across machines,
but distributed reuse needs durable provenance and the existing receipt checks.
The current change keeps DuckDB ownership, sparse candidate publication, resume,
Arrow storage and inference/training separation intact.

## Publication and reproducibility

Evidence and exact commands are under
[`evidence/autoencoder-optimizer-20260929`](evidence/autoencoder-optimizer-20260929).
Among explicitly bound native dependencies, the pinned workspace differs from
prepared main in six files: compiler, decompiler, parser, two formula/decompiler helpers and a
preexisting autoencoder worker-budget edit. The publication applies only the new
autoencoder refinement delta on top of main and preserves other concurrent source
edits. Native results belong to their captured workspace hashes; prepared-main
unit tests are separate evidence. Git-linked Python contents are identified as
unexpanded in the source audit, not silently treated as deleted. Across the full
package mapping, the audit records 16 superproject content differences and 565
unexpanded Git-linked Python paths; all are listed explicitly.

No checkpoint weights or target bundle is included in the Git evidence. The
protected seed remains unchanged. All seven reservations created by this work
were released, all 153 historical ledger records (including 61 retained claims)
were preserved, and the cap remains 80 GB. Publication uses a private Git index
and leaves the live shared checkouts and indexes intact.

The initial isolated test harness needed normal installed dependencies and the
expected `external/ipfs_datasets` / sibling `JevOps` layout. A legacy CLI test
also imported a workspace-only worker-budget helper that the runner no longer
uses. It was replaced with a test of actual CLI capacity delegation, retaining
stable logical lanes and the existing resource-deferral checks. No production
source or qualification criterion changed to resolve these test issues; the
initial failure artifacts are retained with descriptive suffixes.

The final isolated prepared-main suite passed **544 tests**, with no failures,
errors or skips. Loaded-module origins, the exact parity-policy resource and the
external statement-lock hash were checked. The final replacement CLI test suite
passed **25 tests**; the earlier broad workspace run passed **828 tests** before
that test-only replacement. Native package and runner source hashes did not change.

For normal hardware admission, leave `--workers 0 --parallel-workers 0` (both
defaults). This retains 32 logical lanes while choosing each actual dispatch from
the available resources and pending work. Use `--parallel-workers 4` to cap
concurrency without changing those lane identities. The optional
`--composed-refinement-attempts 3` requires training mode and disjoint
`--validation-jsonl`; omission preserves the prior optimizer behavior. Exact
bounded comparison commands and all five bridge settings are in the receipts.
