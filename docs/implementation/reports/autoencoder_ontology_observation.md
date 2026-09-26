# Ontology capture observations in training receipts

Implementation continuation, 2026-09-25, of the
[capture reuse design](autoencoder_ontology_capture_reuse_design.md).
Native workers now retain bounded diagnostics about capture work. Capture
reuse remains disabled: the new evidence distinguishes several failure paths
but does not establish that all transitive dependencies completed without error.

Later source/test update: current capture also includes an actor stage. The
[reserved-window investigation](../../../workspace/test-logs/federal-corpus-audits/reserved-validation-20260925/observation-investigation/investigation.json)
found eight stale test-reference comparisons against the earlier pre-actor
behavior. A test-only change retains that historical literal and adds a
separately versioned actor-aware uninstrumented reference; exact observer-on/off
checks now pass. The combined current semantic/capture/report suite passes 248
checks under stable package sources. These are regression checks, not a repeat
of the historical native qualification below. A separate actor-import fallback
defect is recorded and remains unfixed; capture reuse is still unqualified.

## What changed

A standard-library-only context collector records capture and record scopes,
stage times, suppressed and escaping exception classes, and explicit converter
result statuses/counts. The existing frame-triple, fallback projection,
recipient and procedure paths report what happened without changing their
returned records or exception policies. The optimizer wrapper retains its
existing import-error and capture-error fallbacks to an empty list.

`ConversionResult` can report failure without raising. Recipient extraction can
then return a regex fallback, and procedure extraction can return an ordinary
empty record. Both helpers now observe exact native result metadata before
continuing their existing logic. Unknown/custom results and malformed metadata
remain uninspected or explicitly unsupported. The collector does not call
custom stringification, read diagnostic message contents, or retain conversion
outputs and exception instances.

The worker installs the collector only around its training call and writes
`ontology_capture_observation` in the complete worker receipt. Existing owner
receipt-artifact staging makes that document durable; job schemas, candidate
patches and coordinator summary fields are unchanged. Ordinary direct evaluator
calls have no active collector unless one is explicitly installed.

Nested contexts restore their enclosing collector and active scope. Snapshots
detach all retained data. Default limits are 128 capture scopes, 4,096 records,
32,768 stages/conversions and 4,096 error observations, with bounded labels and
producer-label JSON. Overflow and unsupported observations set
`observations_complete=false`. These are retained-row limits, not a measured
Python heap-byte guarantee. No sample text, IR graph or captured record is kept
in this diagnostic collector.

The scope tree matters. An inner batch can emit a record, later abort, and be
discarded when the optimizer wrapper returns its existing empty-list fallback.
Emitted-record counts are not final output counts. Nested scopes can observe
the same escaping exception; error observations are not unique root causes.
Stage timings are inclusive and must not be added across ancestors.

## Remaining limits on reuse

Every observation says `reuse_qualified=false`. A
`returned_without_observed_error` outcome means only that no instrumented
boundary reported an error. `observations_complete=true` means the collector
retained its observed events without truncation or unsupported metadata; it
does not prove complete dependency coverage.

In particular, parser repair-clearance and deterministic repair-resolution
helpers can suppress import/formula errors while the converter reports success.
Reachable modal projection helpers also default some malformed numeric, JSON
and iterability inputs. These branches were audited but not rewritten or
instrumented by this change. Result reuse needs explicit treatment of those
paths, exact ordered inputs and mutable dependency guards, followed by an
end-to-end comparison that includes guard/copy costs.

The previously observed schedule is validation, training, then validation:
nine captures across six distinct records. It offers three repeated captures,
not six. The first six computations, target hydration and projection work would
remain even with qualified reuse. Moving additional numeric tables to Arrow
addresses different costs and remains a separate measured decision.

## Native owner qualification

The user reserved a stable source-editing window. The
[native receipt](evidence/autoencoder_control_plane_plan/ontology-observation-native-20260925.json)
passes fresh target preparation, a single ordinary owner-dispatched combined
Arrow job, immutable receipt staging, restart durability, and unchanged-head
checks. The complete producer binding stayed unchanged. The earlier failed
attempt remains historical evidence; it was not overwritten or relabeled.

This uses the same frozen three training and three validation U.S. Code source
records, with all five bridges: `modal_frame_logic`, `deontic_norms`,
`fol_tdfol`, `cec_dcec`, `external_prover_router`. Provers are false, metric disk
cache is 0, bridge workers and training workers are each 1, sample memory is
false, temperature is 0, and CPU `python_sparse_batch` uses one epoch, one
update family, one line-search attempt and max seconds 180. The preparation
process bypasses metric and multiview caches. The worker reuses the newly
sealed complete bundle; its evaluation is not cold target generation. OS cache
warmth is uncontrolled. Quack transport and production DuckLake were not
exercised by this local-owner qualification.

| Observed operation | Wall seconds | Seconds / applicable span |
|---|---:|---:|
| Target generation, six samples | 51.5164 | 8.5861 |
| Complete preparation, six samples | 61.0899 | 10.1816 |
| Owner dispatch through durable completion, three training samples | 23.7628 | 7.9209 |
| Worker execution, three training samples | 19.8445 | 6.6148 |
| Initial bridge-on evaluate, three validation samples | 4.0269 | 1.3423 |

These are one-run observations, not a speedup claim. The owner time excludes
one-time preparation and staging. The worker spent 7.1306 seconds hydrating
targets and 8.4025 seconds in training. Before/after evaluation each retained
three targets and nonempty legal-IR losses. All six preparation reports had
five implemented bridges, no reported bridge failures, and report acceptance.
That is bridge evidence, not proof or compiler/formalization coverage.

The optimizer accepted zero epochs and emitted zero sparse-patch bytes. The
logical model state, pinned checkpoint and branch head stayed unchanged. The
exact preparation receipt and its bundle association survived owner restart;
the complete worker receipt, including capture observations, also survived.
The isolated run retained 64,732,825 artifact bytes.

## Native capture costs and parity

The worker recorded nine capture records, eighteen successful converter-result
observations, thirty-nine stage observations and no direct error observations.
The collector did not truncate data. Reuse remained unqualified and disabled.
Its three outer capture calls took 1.6234, 1.0989 and 1.4878 seconds, for a total
of 4.2101 seconds. Within those calls, nonoverlapping named projection stages
totaled 3.6306 seconds; recipient stages totaled 0.3410 and procedure stages
0.1710 seconds. The nested outer/inner scope durations are not added twice.

The repeated final validation capture costs about 1.49 seconds here. Eliminating
that entire call would save at most about 6.3% of this observed owner-job time
before paying for identity checks, dependency guards, detached replay and cache
management. This is an opportunity bound for this schedule, not an implemented
gain or a forecast for more epochs. Hydration remains the larger individual
cost; the previous failed hydration shortcut must not be revived on profiler
call counts alone.

The [capture-only diagnostic](evidence/autoencoder_control_plane_plan/ontology-observation-capture-parity-20260925.json)
compares saved original wrapper/capture/conversion helpers with observed
helpers on the same validation/training/validation schedule in fresh processes.
All nine complete serialized records match exactly, as do the ordered source
IDs and complete source/runtime configuration. Reference mode explicitly
substitutes saved functions in memory and is not an unmodified native worker.
No model weights, bridge evaluation or training are involved in this diagnostic.

One reference run took 6.3901 seconds (0.7100/capture); one observed run took
6.1601 seconds (0.6845/capture). This pair supports exact output parity and shows
no observed overhead regression in that run. It does not establish a speed
benefit or a statistical overhead estimate. Its import/cache/timing scope
differs from capture inside a full training job, so the two scopes are not
combined into a speed ratio.

## Validation

The [combined focused suite](evidence/autoencoder_control_plane_plan/ontology-observation-tests-20260925.xml)
passed **262 tests**. It covers capture output/getter/exception parity against
the saved original helpers, caught and escaping failures, conversion failure
followed by recovery, malformed metadata, bounds, detached snapshots, context
isolation, worker artifact/state behavior, target preparation, native target
grammar inspection and the required semantic gates.

Two injected-worker tests specifically exercise a second-row failure after a
first record was emitted, followed by a successful recovery batch. The wrapper
still returns zero records for the failed batch. Complete trainer reports and
candidate checkpoint hashes match the corresponding fixture without capture
calls. A trainer exception restores the enclosing observation context and
leaves no completed receipt. These are isolation tests, not native training or
speed measurements. Their [focused receipt](evidence/autoencoder_control_plane_plan/worker-ontology-observation-focused-20260925.json)
retains that scope.

The previous segmentation assertion assumed that only the first clause was
compiled. Current production already compiles both. The test now verifies
exactly two ordered rows, their independent parser vocabularies, prohibition
and obligation modalities, exact joined rendering, and false admission flags.
It explicitly rejects whole-span vocabulary leaking into either clause. No
production semantics were changed to repair the test. The
[17-case gate receipt](evidence/autoencoder_control_plane_plan/speed-semantics-clause-vocabulary-20260925.json)
records the independently passing correction before integration.

Only `lake build <Lib>` can provide a Lean admit. This milestone creates no
admit, Constitution `roundtrip_ok`, model promotion or publication. The pinned
restart12 checkpoint remains the required read-only base.

The [final validation receipt](evidence/autoencoder_control_plane_plan/ontology-observation-final-validation-20260925.json)
binds the retained sources, 262 passing checks, native owner/restart result,
exact capture parity and unchanged checkpoint. At that final check, the complete
package source manifest still matched the new target bundle. Named storage
roots totaled 32,514,217,969 bytes against the 50,000,000,000-byte ceiling; this
is not a global filesystem census and includes unrelated shared pytest scratch.
