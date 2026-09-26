# Shared-target evaluation: compiled patterns and native target inspection

Implementation milestone, 2026-09-25, following the
[produced-corpus Arrow benchmark](autoencoder_produced_corpus_arrow_training.md).
This changes repeated evaluation work inside existing source-bound workers;
model storage, source selection and optimizer acceptance rules stay the same.

Follow-up: [failure telemetry and the hydration experiment](autoencoder_target_failure_telemetry.md)
adds receipt-only adapter diagnostics. Its proposed codec fast paths were
rejected after unprofiled measurements showed no combined benefit.

## Profile and provenance

The first diagnostic correctly refused the old bundle. Its complete producer
manifest found a changed `logic/autoformal/autoencoder_router.py`, even though
the prior receipt's smaller explicit source list was unchanged. The
[drift receipt](evidence/autoencoder_control_plane_plan/shared-target-provenance-drift-20260925.json)
identifies the one native-runtime difference. An initial virtualenv diagnostic
also had a different package inventory; the original training interpreter did
not. No target compatibility check was bypassed, and no source was restored.

The same frozen three training and three validation records were regenerated
under current provenance. The
[baseline profile](evidence/autoencoder_control_plane_plan/warm-target-profile-20260925-r2.json)
passed, with identical model outcomes and all prior evaluation fields except
timestamp-bearing target hashes. Profiling overhead makes its 43.78-second
training duration unsuitable as a wall-speed baseline.

The profile attributed 37.22 cumulative seconds to ontology capture, including
35.53 seconds converting modal IR to full frame-logic triples. Repeated regex
compilation accounted for 283,784 calls and 23.68 cumulative seconds. These
overlapping cumulative times must not be added. Target grammar inspection also
serialized native summaries 18 times across nine sample evaluations, costing
0.79 profiled seconds. This evidence prioritized compiled-pattern reuse over
broader Arrow mapping, CUDA, or a new prepared-target representation.

## Implementation

Two modal decompiler helpers now use a private 2,048-entry LRU of compiled regex
programs. All 242 affected search calls preserve their pattern expressions,
flags, input strings, branches, iteration order and output order. Only compiled
programs are retained; text, matches, triples and semantic results are not
cached. DEBUG and unusual argument types continue through Python's standard
search implementation. AST comparison against the saved original functions
confirms that only search dispatch changed.

Native `LegalIRTrainingTarget` summaries cannot contain grammar candidates.
After checking explicit grammar validation, the autoencoder now skips the two
summary serializations for the exact native class and original method. It
retains generic handling for subclasses, instance/class overrides and rich
targets, including custom serializers whose second call returns different
data. The payload still reads current losses and view distributions and hashes
the current document. Nested mutations remain observable; frozen outer
dataclasses are not treated as deeply immutable. Module lookup avoids a new
eager bridge import.

## Qualification method

The ordinary native benchmark uses the existing single DuckDB owner and
source-bound v6/v7 jobs, including shared targets, accepted-patch capture,
optional Arrow inputs/feature weights, two independent concurrent candidates,
owner restart and unchanged branch-head checks. Each job uses three training
rows and three distinct validation rows from the same frozen selection. These
rows do not establish unseen-checkpoint lineage or qualify a held-out canary.

The separate diagnostic benchmark replaces the three changed helpers with
their verbatim saved historical implementations in reference processes. Both
modes load the same final-source target bundle through normal verification;
the bundle's configuration is never relabeled. The receipt explicitly records
the runtime substitution, so reference runs are not presented as unmodified
native workers or owner-qualified jobs. Each observation uses a fresh process,
with alternating reference/native order. Both modes pre-import the same modal
modules before the worker timer. Their worker times exclude owner dispatch and
the later full-triple check. Diagnostic dispatch times include that extra check
and are not complete training-job measurements.

Full evaluation dictionaries, training reports except `projection_profile` and
`elapsed_seconds`, state
identities and materialized checkpoint identities are compared exactly.
Ontology captures need an additional check: they live in
`last_ontology_captures`, outside ordinary evaluation serialization. An equal
observer in both diagnostic modes retains every capture for comparison after
timing, including recipient/procedure records and all false admission flags.
The six full ordered triple lists are separately hashed after timed work,
covering content beyond the capture's 32-triple limit. This extra projection
does not warm the timed workload.

Every timing uses all five bridges: `modal_frame_logic`, `deontic_norms`,
`fol_tdfol`, `cec_dcec`, `external_prover_router`. Provers are false, metric disk
cache is 0, sample memory is false, bridge workers are 1, temperature is 0,
and CPU `python_sparse_batch` uses one epoch, one update family, one line-search
attempt and max seconds 180. Shared timings reuse complete sealed targets and
are not cold target-generation timings. The compiled-pattern cache warms
within each new process; OS cache warmth is uncontrolled.

## Target growth and native results

The [new native receipt](evidence/autoencoder_control_plane_plan/shared-target-native-20260925.json)
passed all eight jobs, restart checks and unchanged-head checks. All proposed
updates were rejected under the existing rules. The checkpoint remained
unchanged, and all shared modes produced identical complete evaluation
dictionaries and materialized candidate identities. Fresh versus shared
evaluation matched except timestamp-bearing target hashes, as separately
disclosed in the receipt.

| Native mode | Complete job wall time | Wall / training span | Initial bridge-on evaluate | Evaluate / validation span |
|---|---:|---:|---:|---:|
| Fresh targets, JSON inputs/weights | 65.0613 s | 21.6871 s | 29.5588 s | 9.8529 s |
| Shared targets, JSON inputs/weights, two-run median | 22.6213 s | 7.5404 s | 4.0093 s | 1.3364 s |
| Shared targets, mapped inputs, two-run median | 23.1457 s | 7.7152 s | 3.9449 s | 1.3150 s |
| Shared targets, mapped inputs and feature weights | 23.7020 s | 7.9007 s | 3.9856 s | 1.3285 s |

Two concurrent mapped jobs completed in 25.4142 seconds, or 4.2357 seconds per
training span across six processed training rows. Their individual initial
evaluations took 3.8851 and 4.0051 seconds for three targets each. The observed
sequential mapped total was 46.2914 seconds. This is independent candidate
throughput through one owner, not synchronous gradient training. Mapping did
not improve complete-job time and remains opt-in.

Historical before/after timing is **not an exact target comparison**. The
[target-growth audit](evidence/autoencoder_control_plane_plan/shared-target-growth-20260925.json)
found three larger shards. Total expanded target bytes increased from
70,139,177 to 212,314,592; artifact bytes increased from 5,043,217 in the
refreshed baseline to 12,843,316. For the decoded 38 U.S.C. 102 pair, the old
target recorded a modal bridge failure and omitted its views. The new target
contains 12 modal formulas, 26,312 triples, 1,408 graph nodes and 26,312
relationships. Twelve canonical losses and the view distribution also changed.
This is additional generated content, not a storage-code inflation or an
accepted weight improvement.

The original exception text was discarded by `training_target()`, so its cause
cannot be proven from the retained target. A swallowed timeout is a supported
inference: the deadline exception derives from `RuntimeError`, the multiview
adapter boundary catches `Exception`, and preparation marks a returned target
`ready` even when one adapter failed. No deadline or catch behavior was changed
in this milestone. **`ready` indicates a serialized target, not success of all
bridges.** Bridge acceptance and failure losses remain evidence fields; even a
zero proof-failure metric with provers disabled is not a proof.

The larger targets explain why native complete-job time stayed near the older
22.93-second shared JSON median despite faster evaluation. The first new JSON
job spent 7.03 seconds hydrating targets, versus 2.02 previously. Native
preparation took 60.1461 seconds, including 50.5627 seconds generating six
targets, or 8.4271 seconds/span. These changed targets make a historical
cold-generation speed ratio inappropriate. The controlled same-bundle
comparison below isolates execution performance.

The [final diagnostic profile](evidence/autoencoder_control_plane_plan/warm-target-profile-20260925-r3.json)
passes exact parity with the new native job. It confirms that native summary
serialization disappeared and only 15 document-hash calls remain, versus 33 in
the earlier diagnostic. Compiled regex calls fell to 25,762; the private cache
compiled 746 distinct programs within its 2,048-entry bound. Profiler timings
are diagnostic, not wall-speed claims. Ontology conversion and full target
hydration remain larger costs than the approximately 0.073-second projection
update.

## Controlled same-bundle result and interrupted replication

The [completed-pair analysis](evidence/autoencoder_control_plane_plan/shared-target-completed-pair-20260925.json)
records one fully completed reference/native pair with exact parity on every
listed check, including the complete ordered triples, ontology captures,
optimizer decisions and final candidate identities. It uses the same
12,843,316-byte target bundle and the settings stated above. This is one
observation per mode, not a multi-run median or a full-corpus forecast.

| Controlled diagnostic | Historical helpers | Optimized helpers |
|---|---:|---:|
| Worker execution, with equal pre-imports and observer | 26.1112 s | 18.5940 s |
| Worker execution / training span | 8.7037 s | 6.1980 s |
| Initial bridge-on evaluate, three targets | 5.2444 s | 2.5591 s |
| Evaluate / validation span | 1.7481 s | 0.8530 s |

Worker execution decreased 28.8%; initial bridge evaluation decreased 51.2%.
Reference mode retained zero programs in the new private regex cache; native
mode recorded 746 misses and 220,955 hits. Every search still ran, and the
resulting ordered outputs matched. Both optimizer attempts were rejected; this
does not establish a weight improvement.

The [four-job diagnostic attempt](evidence/autoencoder_control_plane_plan/shared-target-ablation-20260925.json)
**did not pass as a whole**. After the first pair, another native worker
completed, but the final reference worker rejected producer drift at its end
boundary. `logic/autoformal/autoencoder_router.py` changed from
`5b8e82ff76949f84fc47288d903c6f819805271abf3b5a95fe45eb86c6007930`
to `179e273df2dd0166b227bbf6ba574034f193bf1dc5fac5cf126271ddb304e0f7`
during the run. The three optimization files stayed unchanged. The failed
receipt and partial artifacts are retained; the analysis above extracts only
the previously completed exact-parity pair. It does not relabel the complete
attempt as successful or average the incomplete reverse-order pair.

The eight-job native benchmark and the final profile completed before this
later edit. Their evidence remains bound to their recorded sources. The target
bundle is now incompatible with current producer provenance and must be
regenerated before another normal training run. Benchmarks require a stable
producer revision throughout preparation and execution; bypassing that check
would invalidate the comparison.

## Validation

The [semantic check receipt](evidence/autoencoder_control_plane_plan/shared-target-semantic-checks-20260925.json)
records 182 passing focused tests: 71 native-grammar/snapshot/bundle tests,
35 compiled-pattern tests and 76 ontology/recipient/procedure/gate/modal-slot
tests. Thirteen modal-slot cases were skipped by the repository's existing
compiler/registry-drift policy; they are not counted as passes. Both production
patches were frozen before the final 76-test suite. The grammar tests preceded
the separate regex change; their final source hashes were rechecked.

The [five-case pilot](evidence/autoencoder_control_plane_plan/shared-target-semantic-pilot-20260925.json)
retains forward 0.915 and cycle 1.000. The three required gates preserve
obligation/deadline/exception semantics, prohibition, the integer minimum
duration, empty-vocabulary abstention and the deadline's non-renderability.

The [final validation receipt](evidence/autoencoder_control_plane_plan/shared-target-final-validation-20260925.json)
binds the unchanged optimization sources, original checkpoint, test evidence,
successful native benchmark and separately failed replication attempt. Named
storage roots totaled 32,443,829,952 apparent bytes, below the 50-billion-byte
ceiling; the shared pytest root includes unrelated artifacts, and this is not
a global filesystem census. No protected artifacts were deleted.

## Scope and next decisions

These changes do not introduce remote SQL into numerical operations. The
existing immutable artifacts, private worker updates, sparse candidate
submission and single DuckDB owner continue to avoid concurrent database
writers. Arrow remains optional until a larger workload shows a complete-job
or memory-concurrency benefit. Full numeric mapping would not remove the
ontology work identified here.

Before scaling target reuse, retain adapter failure reasons and distinguish
partial bridge output from fully completed bridge output in telemetry. Do not
retroactively relabel old targets or infer proof from their `ready` status.
Keep the same acceptance rules and preserve the actual partial target bytes.

Broader prepared-target reuse remains possible, but requires sealed complete
bytes and exact sample/configuration bindings; caching mutable hydrated objects
by identity would be incorrect. Follow the measured residual cost before adding
that representation. Source-complete inventory, qualified long-input handling,
accepted corpus-training progress, source-aware Constitution training and a
reviewable HF release remain outstanding in the
[federal-law plan](../plans/FEDERAL_LAW_END_TO_END_TRAINING_PLAN.md).

The Constitution remains unformalized. No checkpoint promotion, HF publication
or Lean admission occurs in this milestone. Only `lake build <Lib>` is a Lean
admit; neither target reuse, loss parity, a database row nor captured triples
changes that rule.
