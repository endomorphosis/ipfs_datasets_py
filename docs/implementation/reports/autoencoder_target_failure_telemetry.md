# Shared-target failure telemetry and rejected hydration experiment

Continuation of the [shared-target evaluation milestone](autoencoder_shared_target_evaluation.md),
2026-09-25. This milestone preserves evidence about partial bridge results.
It does not change target contents, optimizer acceptance, or legal admission.

Follow-up: the [ontology-observation milestone](autoencoder_ontology_observation.md)
records a later successful native qualification during a stable editing window.
It also corrects the obsolete segmentation test to verify both compiled clauses.
The failed run and assertion documented below remain unchanged historical evidence.

## Receipt-only implementation

`prepare_training_targets` now includes `bridge_report_telemetry`, indexed by
sample ID. Each received multiview report records its attempted, implemented,
failed and accepted bridge counts and names, report acceptance, and exact
failure strings. The producer collects these observations in input order on
the consumer thread, including when generation uses multiple workers.

An outer timeout has no returned report. Its unavailable counts, names and
acceptance are `null`; its concrete exception type and message are recorded
separately. A timeout caught inside an adapter remains the existing returned
partial report, with its original failure string. No timeout or exception
handling policy changed.

The existing `ready` status still means that a returned report produced a
target. It does not mean every bridge accepted the text, and is not a Lean
admit. The receipt now states this explicitly. Telemetry does not enter
`training_target()`, the snapshot format, target hashes, losses or worker job
schemas. Consumers still need the preparation receipt to inspect these new
details; the target alone does not reconstruct historical exception text.

Tests compare complete JSON and bundle artifact bytes with direct legacy
writing under the same bound configuration. Another test triggers the actual
installed SIGALRM handler synchronously inside the real multiview adapter
catch. This verifies the existing nested-timeout behavior without timing races.

## Hydration experiment: rejected

The previous profile suggested reducing Python duplicate-key checks and
recursive primitive decoding. An experimental patch used `dict(items)` plus
a length check during strict JSON parsing, and inlined primitive leaves during
tagged decoding. It preserved duplicate-key rejection, finite numbers, exact
types/order, depth limits and independent mutable results. All 183 experimental
codec tests passed.

Unprofiled wall time did not support keeping the patch:

| Archived target | Expanded bytes | Original parse + decode | Candidate parse + decode |
|---|---:|---:|---:|
| Smallest shard | 14,196,065 | 0.237731 s | 0.265178 s |
| Largest shard, reversed execution order | 65,169,197 | 1.350543 s | 1.374112 s |

Each mode ran in a fresh process with one warmup and three measured iterations.
The table uses medians. The archive, compressed shard and expanded shard hashes
were verified; full target validation and exact canonical re-encoding ran
outside timing. Garbage collection remained enabled, with collection before
each trial. This is archived-format throughput analysis, not a current target
configuration qualification, per-evaluate timing or legal-IR speedup.

The candidate was approximately 11.5% and 1.75% slower respectively. Only these
experimental changes were reverted. `legal_ir_target_snapshot.py` again has
its original SHA-256
`7d0a014c4856826aafbe972534456af72e5b69c737662f8ce93a3e8e1d647c9b`.
The restored snapshot/bundle suites passed 59 tests. Candidate source and
experimental tests are retained outside the package and active test suite in
the [rejection receipt](evidence/autoencoder_control_plane_plan/hydration-codec-rejected-candidate-20260925.json).
The [small-shard receipt](evidence/autoencoder_control_plane_plan/hydration-codec-microbenchmark-20260925.json)
retains the first measurement.

This avoids committing extra codec complexity without a measured gain. Python
profiling overhead is useful for locating work but can overstate savings from
removing function calls. Any subsequent hydration representation needs an
unprofiled, same-target worker comparison before adoption.

## Validation and concurrent work

The combined preparation/semantic test run recorded 38 passes and one failure:
all 22 preparation tests and the three required individual semantic gates,
including empty-vocabulary abstention, pass. An additional segmentation test
expects only the first clause's row, while concurrently edited `compile_span`
now compiles both clauses and ends with the second row. The existing test and
that production code were left unchanged; this run is not reported as fully
green. Its [JUnit result](evidence/autoencoder_control_plane_plan/target-telemetry-tests-20260925.xml)
retains the assertion.
After the later source-drift abort, a
[second semantic check](evidence/autoencoder_control_plane_plan/target-telemetry-current-gates-20260925.xml)
again passed 16 cases, including the required gates, and failed the same
segmentation assertion. Repeated passes are not added to the unique test count.

The [source-drift inventory](evidence/autoencoder_control_plane_plan/target-telemetry-source-drift-20260925.json)
compares the digest-verified previous native bundle's complete source manifest
with the current tree. Besides this milestone's preparation change, it records
changes to autoformalization, the router, ontology capture, the parser and
Constitution inventory, plus a new repeal fixture. These are not attributed to
the telemetry patch. Old target configurations remain invalid for new normal
training; no provenance field is relabeled to make them load.

## Native qualification attempt: stopped on source drift

The new `qualify_target_preparation_telemetry.py` harness fixes the same three
training and three validation source records used by the passing historical
combined Arrow job. It prepares new targets, then intends to stage the exact
preparation receipt separately from the target bundle, bind both in immutable
run metadata, dispatch one normal owner-managed job, and verify receipt bytes,
bundle association and unchanged head after restart. This keeps diagnostics
durable without adding fields to the worker job schema. The harness exercises
the local DuckDB owner; it does not exercise Quack or production DuckLake.

The [native attempt](evidence/autoencoder_control_plane_plan/target-telemetry-native-20260925.json)
failed closed after 62.2120 seconds during target preparation. The resident
producer check found changed source/configuration. Comparing the captured
source list shows `logic/autoformal/__init__.py` and
`logic/deontic/utils/deontic_parser.py` changed during this attempt. Only the
frozen selection file remained in its artifact directory. No target bundle or
preparation receipt was published, and no owner training job was dispatched.
The intended owner/restart checks therefore remain unexecuted, not passed.

There is no new per-span training time or bridge-on evaluation time from this
attempt. The 62.2120 seconds are failed-attempt wall time, not a six-target
generation measurement. The intended recipe retains all five bridges
(`modal_frame_logic`, `deontic_norms`, `fol_tdfol`, `cec_dcec`,
`external_prover_router`), provers false, metric disk cache 0, one bridge worker,
one training worker, sample memory false, temperature 0, and bounded CPU
`python_sparse_batch`. Preparation bypasses metric and multiview caches; the
planned worker would reuse its sealed bundle. OS cache warmth is uncontrolled.

Rerun this bounded qualification during a stable editing window on the pinned
workspace tree. Do not switch trees, restore another process's edits or weaken
the complete producer binding. The prior eight-job native result remains
historical evidence under its recorded sources; it does not qualify this
changed tree.

## Next implementation boundary

Continue with bounded, worker-scoped ontology reuse only after making partial
extraction failures observable. Preserve raw IR ordering, exact scalar types,
mutable registry identity, and detached outputs. The
[ontology reuse design](autoencoder_ontology_capture_reuse_design.md) specifies
these guards and the measurement needed to decide whether reuse pays for its
own key construction and copying.

Keep Arrow input/feature-weight mapping optional until a complete-job or
memory measurement establishes its benefit. Continue using immutable local
snapshots and private sparse updates; do not move weight lookups into Quack.
Full numeric-table mapping, production DuckLake ingestion and qualified Hugging
Face publication remain separate steps in the
[federal-law plan](../plans/FEDERAL_LAW_END_TO_END_TRAINING_PLAN.md).

The Constitution remains unformalized. No `roundtrip_ok`, model promotion,
publication or Lean admission is created by this milestone. Only
`lake build <Lib>` can provide a Lean admit.

The [final validation receipt](evidence/autoencoder_control_plane_plan/target-telemetry-final-validation-20260925.json)
binds the retained code, 97 unique passing checks and one failing segmentation
check, exact codec restoration, failed native attempt, unchanged pinned
checkpoint and storage observation. It deliberately has no aggregate success
claim for end-to-end qualification.
