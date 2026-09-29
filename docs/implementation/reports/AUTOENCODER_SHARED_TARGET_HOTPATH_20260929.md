# Autoencoder shared targets, proposal bookkeeping, and deadlines

2026-09-29. This change removes repeated work and makes optimizer deadlines
consistent. It does not loosen training acceptance or formalization gates.
The previous eight-cell sweep produced no accepted epochs or sparse updates;
its untouched canary and protected restart12 checkpoint remain unchanged.

## Why all eight configurations stalled

The sweep completed its eight configurations in 18m43s and stopped after the
common first round because none committed a change. This was not eight
independent demonstrations that the learning rate, momentum and refinement
choices were bad. Several requested features never got a chance to operate.

The [row-by-row diagnosis](evidence/autoencoder-shared-target-hotpath-20260929/stall-diagnosis.json)
identifies four interacting causes:

1. Each worker regenerated the same six training and two tuning targets.
   Initial evaluations cost about 101–104 seconds. Four of the six training
   targets were explicit timeout fallbacks, and that repeated cost consumed
   much of each 180-second optimizer budget.
2. Large decoded-embedding proposals inserted 326,571 rows into a fresh
   384-dimensional model. Patch capture, norm accounting and rollback copied
   and traversed speculative state repeatedly. The old profile did not isolate
   every copy; unassigned wall time is not attributed wholly to copying.
3. Seven adaptive decoded proposals hit the cooperative deadline before
   holdout evaluation. Fixed mode historically permitted a later evaluation
   across the same boundary. Observed 239–278-second worker calls therefore
   describe different completed work, not a fair optimizer speed comparison.
   None reached the scheduled combined update. Neither momentum configuration
   acquired a committed step history, and neither refinement configuration
   acquired an accepted starting proposal. Sixteen family-logit trials had
   zero observed objective change with the configured zero readout scales.
4. The fixed decoded proposal that reached holdout improved reconstruction but
   worsened legal-IR metrics. Legal-IR cross-entropy increased from
   **1.589026915 to 1.791759469**, and family cosine-gap loss increased by
   **0.088715505**. Existing guards correctly rejected it despite a positive
   aggregate objective delta.

The last regression has a concrete coupling: the decoded update introduces
additional embedding-map family keys used as candidate IR labels. With the
dedicated IR logits unchanged, a tuning example's label set expands and its
uniform distribution loses probability mass on existing targets. The observed
mean cross-entropy changes from `(ln(4) + ln(6))/2` to `ln(6)`, exactly the
reported 0.202732554 increase. This explains the regression without changing
the definition of success. A better scalar reconstruction metric alone does
not establish a better legal model.

The evidence does not indicate insufficient supervisor prompt context or an
incorrectly strict acceptance threshold. These were native optimizer rejection
and deadline paths. Large accepted patch size remains unmeasured because no
patch was accepted; the existing 64 MiB patch bound was not increased.

## Implementation

The existing complete tagged target bundle is now explicitly handed to every
native diagnostic candidate. It is generated once over the training/tuning
union, with no canary target evaluation. The producer records per-split target
statuses, timeout counts, returned report counts and independent preparation
time. Native and timeout target classes retain their exact losses, view
distributions, document hashes and false admission meaning. Ordinary lossy
metric-cache summaries are still rejected as complete targets.

Each worker checks artifact bytes, requested sample content and embeddings,
ordered bridge names, prover/worker/timeout configuration, dependency identity,
and the full package Python producer manifest. Pool reuse still clears process
target caches before and after every job. Shared-artifact reuse is explicit in
receipts and is never reported as cold target generation. Sample building,
target hydration and pretraining work have separate wall-time observations.

`run_incremental_autoencoders.py` already consumes the producer's
`runner_arguments`, stages the artifact once into the owner's registry and
puts it in each job. A direct coordinator must likewise call
`registry.stage_artifact(target_path, expected_sha256)` and use
`registry.artifact_path(staged)` in `target_snapshot_artifact`; merging the
producer path alone is insufficient for owner verification. See the concrete
[handoff instructions](evidence/autoencoder-shared-target-hotpath-20260929/handoff.md).
Distributed/fleet workers currently set shared targets to `None`; owner policy,
staging and artifact-version transitions still need integration there.

Proposal bookkeeping now discards speculative state without constructing an
unused rollback postimage. Public patch/rollback isolation stays unchanged.
Private owner-checked, field-filtered iteration computes norms by streaming
numeric leaves in the same reduction order, including the prior string-key
collision behavior. Adaptive mode captures one proposal patch and reuses it,
recapturing only if momentum actually changes the proposal.

Fixed and adaptive modes now check the same deadline before a new holdout
evaluation, including the application and prescreen boundaries. An expired
proposal is rolled back; an earlier fully guarded winner remains available.
The limit is cooperative: an operation already in progress can run until its
next check. An unevaluated proposal is not presented as an evaluated loss
regression. New `committed_objective_delta` telemetry reports the actual
before/after committed change separately from legacy proposal diagnostics.

## Verified preparation and focused measurements

The native [preparation receipt](evidence/autoencoder-shared-target-hotpath-20260929/shared-target-preparation-r2.json)
contains **8 targets**: two returned targets plus four timeout fallbacks for
training, and two returned targets for tuning. The artifact is **8,463,071
bytes**. Returned/ready means a report produced a target; it is not semantic
acceptance, a successful round trip, or a proof.

| Preparation wall-time scope | Seconds | Seconds per span, 8 spans |
| --- | ---: | ---: |
| Target generation | 91.716 | 11.464 |
| Preparation including planning and supervision | 107.834 | 13.479 |

This run used `modal_frame_logic`, `deontic_norms`, `fol_tdfol`, `cec_dcec`,
and `external_prover_router`; external provers were false, metric disk cache
was 0, one IR worker ran, and sample memory was false. Both metric and
multiview target caches were bypassed during generation; OS cache warmth is
uncontrolled. Consumers reuse this bundle, so their subsequent evaluations are
shared-target measurements. Generation is not an autoencoder evaluate; native
bridge-on evaluate timings must come from the consumer receipts below.

The controlled [bookkeeping experiment](evidence/autoencoder-shared-target-hotpath-20260929/bookkeeping-profile.json)
preserved the exact norm report on 96 touched existing rows and 128 unrelated
inserted rows of width 384. Median norm time changed from **0.124055 to
0.092058 seconds**; traced peak allocation changed from **16,373,888 to
63,699 bytes**. These measure one synthetic norm operation, not total training
speed, resident memory, convergence or admission.

Focused validation passed **250 unique shared-target/worker/preparation/pool
cases** and **200 final optimizer/transaction cases**, including 57 bookkeeping
cases. The first broader regression pass recorded **1,605 passed, 4 skipped,
1 failed**. That failure compared optional evaluation timing telemetry in two
otherwise matching CPU fallback reports. A test-only correction excludes the
nonobjective timing profile and adds exact state equality; all **4 CUDA
fallback tests passed** afterward. These counts describe their separate runs,
not a new combined all-tests-pass receipt. No CUDA training was enabled.

## Native smoke validation

The first attempt failed before worker execution because the workspace harness
had not staged the target artifact into the owner registry. Its failure and
600 MB retained resource claim remain recorded. R2 corrected the handoff and
completed two native workers against the same prepared target bytes.

The [R2 audit](evidence/autoencoder-shared-target-hotpath-20260929/native-results-r2.json)
passed 51 checks. Both workers preserved the starting weights and committed
zero improvement. All common evaluated proposal metrics and dispositions
matched the earlier sweep exactly; target identity hashes differed because
producer bindings changed.

| Optimizer | Prior training call | R2 training call | R2 seconds per training span | Attempts / evaluated |
| --- | ---: | ---: | ---: | ---: |
| Fixed 0.35 | 277.891 s | 198.606 s | 33.101 | 8 / 7 |
| Productive adaptive 0.35 | 239.608 s | 202.622 s | 33.770 | 8 / 7 |

Each used six training spans and two disjoint repeated-tuning spans, one
attempted epoch, a cooperative 180-second optimizer budget, and all five
bridges listed above. Prior calls attempted seven proposals each; productive
previously evaluated six. This is an observational work/time comparison, not
an equal-work controlled speedup. Neither run reached the combined head.

R2 had 18 bridge-on evaluations with 2 or 6 supplied targets each and zero
native target-generation attempts in workers. Requested IR worker count was 1;
actual target-generation workers used was 0 because targets were supplied.
Two training processes ran concurrently, with a conservative 189.495-second
overlap lower bound. Artifact loading took 5.49 and 5.70 seconds outside each
training call. Initial two-span tuning evaluations took 1.770 and 1.767 seconds
(0.885 and 0.883 seconds per span); the complete per-evaluation list and target
counts are in the audit. These are prepared-target measurements with disk
cache off, not cold native compilation timings.

The stage took 235.922 seconds. Adding the 107.834-second cold preparation
produces **343.756 seconds** for this measured preparation-plus-stage scope.
That excludes launcher/plan overhead and does not establish an end-to-end
speedup for a two-job cold run. Preparation can be amortized across additional
configurations; it must remain included in whole-campaign accounting.

All three deterministic source fixtures passed their compiler/decompiler and
logic-family checks. One installed `lake build Legal` passed for the supported
minimum-duration numeric theorem. The other fixtures stayed non-renderable.
No real-corpus row passed model qualification or acquired a Lake admission.
The eight-hour training gate therefore remains closed.

R2 exposed an additional avoidable cost after an update exhausted its budget:
proposal capture could still begin. The final patch adds checks before capture,
adaptive preparation, momentum recapture, fixed prescreen-to-capture, and
candidate evaluation. Missing snapshots fail closed; deferred prescreen ranking
preserves timeout reasons and null unevaluated holdout deltas. Mandatory rollback
still runs and earlier guarded winners are preserved. The budget remains
cooperative inside an individual update or rollback operation.

The final R3 smoke completed under the frozen final producer manifest. It
rebuilt eight targets in **107.059 seconds** and reused them in two concurrent
workers. Fixed training took **196.336 seconds (32.723 s/training span)**;
productive training took **199.621 seconds (33.270 s/training span)**. Both
attempted eight proposals, evaluated seven, and committed **zero** epochs,
objective improvement, or sparse patch bytes. In each final timeout, capture
started before expiry and completed after it; the new guard discarded the
snapshot and skipped further candidate preparation/evaluation. Mandatory
rollback and serialization explain why the cooperative calls exceed 180 seconds.

| Final prepared-target bridge-on evaluate | Target/sample count | Fixed seconds | Productive seconds |
| --- | ---: | ---: | ---: |
| Initial tuning evaluation | 2 | 1.695 | 1.744 |
| Training target prime | 6 | 7.400 | 7.708 |
| Candidate tuning evaluation, mean of 7 | 2 each | 1.591 | 1.638 |

All five bridge names, false prover flag, disk cache 0, IR worker request 1,
false sample memory, and the fixed six-training/two-tuning sample set are
unchanged. Each evaluation contains its supplied targets; none is bridge-off.
Targets remain four native reports and four explicit timeout fallbacks, with
zero repeated native generation inside workers. Artifact hydration is charged
separately. The two-span rows above average 0.847/0.872 seconds per span initially
and 0.796/0.819 seconds per span during candidate evaluation; the six-span prime
costs 1.233/1.285 seconds per span.

The final stage took **234.559 seconds**; cold preparation plus stage was
**341.618 seconds**, excluding launcher/plan overhead. This still does not prove
an end-to-end two-job cold speedup. Compared with the original sweep, workers
completed additional proposal work, while cold preparation moved outside their
optimizer budgets. R3 repeated all three semantic fixtures and the one supported
numeric Lake build successfully; both real-corpus candidate qualification gates
still failed. No eight-hour run or publication of model weights was launched.

The [final native audit](evidence/autoencoder-shared-target-hotpath-20260929/native-results-r3.json)
records all per-evaluation timings, bindings, comparisons and dispositions.
R2 receipts remain immutable evidence of their earlier source version. Final
isolated release checks passed 529 tests before the last timeout-disposition
edge fix, then 200 impacted tests against the final exact publication blobs;
these are separately recorded runs, not a combined test-count claim.

Native measurements use the canonical workspace tree, with compiler, decompiler,
parser and producer hashes recorded in each receipt. Separate compatibility unit
tests use an isolated origin/main source snapshot plus the scoped publication
patch. They are not performance evidence. Unrelated existing parser and automatic
worker-budget edits are preserved in the live workspace and excluded from this
scoped change.

## What productive training needs next

Preserve explicit fallback status while addressing the four training-target
timeouts in a separately measured preparation experiment. Complete native
supervision matters independently of optimizer speed. Then use the same frozen
training and tuning rows to test a bounded combined proposal that updates reconstructed
embeddings and the affected IR logits together. This directly addresses the
observed candidate-label coupling. Keep the baseline metric definitions and
full Pareto/family guards unchanged, and measure which scheduled heads actually
execute before comparing learning rates, momentum or refinement. Do not use
the independent canary to tune the proposal.

Only a candidate with an actual committed improvement and all existing
qualification gates may advance to the conditional longer run. Syntax checks,
IR targets, loss reductions, decompiled sentences and database rows are not
admissions. The relevant supported Lean unit must pass actual `lake build
Legal`. No Mathlib, downloaded weights, increased context, temperature change,
or alternate HACC parser tree was introduced. The Constitution remains
unformalized; no Constitution span is marked `roundtrip_ok`. Nothing here
establishes convergence to a global minimum.
