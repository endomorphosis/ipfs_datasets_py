# Bounded optimizer screening and hardware-aware candidate qualification

This change screens optional reconstruction refinements before expensive
bridge-on validation and lets completed candidates qualify concurrently within
their existing training reservation. Qualification thresholds, candidate search
rates, sparse updates and proof requirements remain unchanged.

Only `lake build Legal` admits generated Lean. The current renderer checks
source-locked integer minimum-duration patterns; these builds do not prove the
complete legal IR or the autoencoder. Six logic-family projections are checked
for syntax and supported-fragment consistency. They do not establish complete
FOL, deontic FOL, temporal FOL, deontic temporal FOL, DCEC or frame semantics.
The Constitution remains unformalized.

## Implementation

Optional composed refinement now evaluates its necessary strict training
reconstruction improvement first. A rejected training screen skips bridge-on
validation, records `holdout_evaluated: false` and an unmeasured objective as
`null`, and retains its rejection reason. Eligible candidates still execute
the existing validation objective and regression guards. Search rates, attempt
bounds, winner ordering, rollback and timeout handling are preserved. Missing
validation measurements cannot become zero-valued entries in the best-rejected
ranking. The default refinement limit remains zero; the smoke opts into three
attempts. This is a reduction in unnecessary evaluation, not a new loss formula.

The native runner accepts `--parallel-qualification-workers 0` for automatic
admission, `1` for the original owner-process route, or an explicit ceiling up
to 32. This physical execution setting does not change logical lanes, persisted
job identity, training policy or resume identity. Inference rejects a positive
training qualification setting and retains its own execution gate.

Before qualification, resident training workers exit. A spawned qualifier is
budgeted at 1,792 MiB, one CPU and three child-process slots, with owner reserves
of 2,048 MiB, one CPU and two process slots. Existing memory, affinity, cgroup,
CPU, process and scheduler limits can reduce the wave to zero. A four-worker
training reservation permits two qualifiers; seven training workers permit
three. A single qualifier can use the owner under the original 2,048 MiB,
two-CPU, four-process allowance. The callback never creates or enlarges a
reservation. Estimates are cooperative accounting, not kernel quotas.

Workers receive immutable candidate/sample/configuration descriptors and write
their own exclusive proof directories. The parent alone stages evidence,
writes DuckDB, advances lane heads and prepares repair/publication outboxes.
Source and artifact checks surround qualification and parent staging. Completed
workers seal their request, producer and portable proof bytes; resume rehashes
those bytes. A sibling failure does not discard verified completions. Incomplete,
aliased or changed output fails closed. Capacity zero defers new work while
allowing already sealed results to recover. The existing outer process-group
deadline bounds the route; the process pool does not add a separate hard timeout.

## Evidence and optimization limits

Native measurements use eight synthetic minimum-duration spans (20–27 days),
one disjoint 30-day tuning span, mock stable-hash embeddings, the protected
restart12 seed, 32 logical lanes and four concurrent training workers. Each
candidate uses one epoch, one ordinary line-search attempt, all five update
families, three optional refinement attempts and Python sparse batch updates.
The optimizer has a 120-second bound and each Lake invocation a 60-second bound.
Repeated candidate selection uses tuning validation, not an independent canary.

| Same-source run | Training waves | Qualification waves | Wall seconds | Seconds/span | Qualified |
| --- | --- | --- | ---: | ---: | ---: |
| Serial qualification | 4, 4 | 1 × 8 | 129.301 | 16.163 | 7/8 |
| Automatic qualification | 4, 4 | 2 × 4 | 112.968 | 14.121 | 7/8 |

This single sequential pair observed 12.63% lower whole-route wall time.
Qualification waves, including parent evidence staging, fell from 49.485 to
35.455 seconds (28.35%). It is not a repeated scaling benchmark. Background
system work and operating-system cache effects are uncontrolled. Both reserved
five CPUs, 12,288 MiB, eight child-process slots and 750 MB of storage. Sampled
peak group RSS was 4.810 versus 4.664 decimal GB and CPU usage peaked at 4.292
versus 4.305 cores. Polling can miss transient peaks and double-count shared
pages; these observations do not establish a hard maximum.

The serial audit passed 1,060 checks and the parallel audit 1,176. Their
143-check comparison passed with identical producer, lane assignments,
candidate parents, materialized weights, selected updates, losses, gate
outcomes, family artifacts and Lean sources. Each produced 16 successful Lake
builds and 96 syntax artifacts. Seven training rows reported cosine 1 and MSE
0; the 22-day row remained blocked at cosine 0.196116 and MSE 0.377941 against
unchanged thresholds of 0.72 and 0.20. Accepted optimizer steps and numeric
proofs did not bypass that failure.

Each run made 24 bounded refinement trials: seven accepted trials and 17
training-screen rejections which skipped bridge validation. Both recorded 63
bridge-on evaluations, 16 newly built native targets, 47 in-process cache hits
and zero disk-cache hits. Cold first bridge-on evaluations, each over one tuning
sample with one legal-IR target, ranged from 4.202–4.470 seconds serial and
4.182–4.513 seconds parallel. See the per-row phase and loss observations in
[the performance receipt](evidence/autoencoder-search-20260929/native-performance-summary.json).

All bridge timings use `modal_frame_logic`, `deontic_norms`, `fol_tdfol`,
`cec_dcec` and `external_prover_router`, external provers false, metric disk
cache 0, target workers 1 and sample memory false. First evaluations are
process-cold with the disk cache disabled; operating-system caches are
uncontrolled. Later in-process target reuse is reported separately. A bridge-off
reconstruction screen is never counted as a faster legal-IR evaluation.

The family artifacts retain typed minimum-duration predicates. These particular
fixtures contain zero temporal operators and zero event/cognitive atoms; the
FOL and temporal-FOL projections explicitly omit modality. Their passing syntax
checks must not be described as full temporal or cognitive semantic coverage.

The earlier refinement baseline took 138.793 seconds and qualified seven of
eight spans. It is a standalone observation: changing the model source hash
changes the batch identity and lane placement, and its 22-day span inherited
the 27-day candidate instead of the protected seed. An unrelated meta-ontology
edit also separates those producer bindings. Old-to-new whole-route speed and
exact-result parity claims are therefore disabled. The final serial/parallel
comparison uses the same producer, lane assignment and candidate parents.

The reconstruction projection is target-aware and discontinuous: one branch
returns a supplied target when alignment is positive. Low in-sample loss does
not demonstrate learned textual generalization, a globally minimal objective,
or formalization of federal law. Optimization here means reaching the best
observed eligible candidate within the existing finite search and resource
bounds. A separate untouched federal-law canary and richer semantic coverage
are needed before broader promotion claims.

## Validation and publication scope

The combined workspace suite executed 764 passing tests, but its producer guard
failed because `logic/autoformal/meta_ontology.py` changed concurrently. That
failed provenance receipt remains visible. After the small capacity-override
hardening, 82 capacity/CLI tests passed. Focused optimizer tests passed 229
cases and qualification tests passed 62. Tests cover non-finite or unchanged
training screens, rollback, earlier winners, validation guards, contradictory
capacity costs, owner-only writes, sealed recovery, source drift, changed proof
bytes, directory aliases and stable completion order.

The exact prepared-main integration suite passed **876 tests across 26 files**
in 63.58 seconds, with zero failures, errors or skips. Exported source and
dependency hashes, module origins, sibling statement-lock bytes and live
checkout/index preservation all passed. Its accelerator dependency is the
exact prepared Gitlink `5306d49957bba7444a31639584e26378f3e3fb19`, exported from
local Git objects without a download. These tests do not constitute native
Lake qualification of main.

The first isolated run also executed 876 passing tests, but the wrapper failed
because this report was edited during execution. The failed wrapper and an
assessment showing the report was the only changed publication file are
retained. The final run kept documentation unchanged. An earlier publication
preparation also stopped when the pre-run source map differed from both native
bindings; the exact map was recaptured and matched both stable native producers.
The intervening meta-ontology edit and original failed preparation are recorded.

The obligation/deadline/exception, prohibition and minimum-duration gates pass
with parser-supplied string atoms. Empty vocabulary still abstains and
within-duration remains non-renderable. The historical five-case pilot remains
green at forward 0.920 and cycle 1.000. No compiler, decompiler or parser source
change is included in this publication.

Publication uses an explicit file list and private Git index. Only this task's
reviewed modal-autoencoder delta is applied to main; a pre-existing workspace
worker-budget change is excluded. Native evidence belongs to its canonical
workspace hashes. Exact prepared-main source tests are separate evidence;
source-scope receipts identify the remaining workspace/main differences.
There are 21 superproject source differences, six mismatched explicitly bound
dependencies, and 565 unexpanded Git-linked Python paths. Consequently these
native Lake receipts do not qualify the prepared-main tree retroactively.
Portable receipts and Lean inputs are committed, with model weights and Lake
build binaries excluded. Protected checkpoint bytes and retained resource
claims remain unchanged; this change does not promote a checkpoint or upload
Hub rows.

The read-only resource closeout verifies all 164 prior reservation records
unchanged, plus exactly three new owned records, all released after completion.
The 61 retained claims, 80 GB campaign cap, 50 GB per-worker cap and protected
25,895,338-byte checkpoint remain intact. Existing accounting timestamps are
preserved; this closeout is not a fresh headroom estimate.
