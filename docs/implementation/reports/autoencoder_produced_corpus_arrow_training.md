# Source-bound corpus training with mapped Arrow inputs

Implementation milestone, 2026-09-25, following
[native embedding production](autoencoder_native_embedding_production.md) and
the [federal-law training plan](../plans/FEDERAL_LAW_END_TO_END_TRAINING_PLAN.md).

## Implementation and scope

An optional Arrow input artifact stores ordered corpus record IDs and fixed
384-dimensional float32 vectors in one uncompressed IPC record batch. It binds
the exact native producer receipt's hash and length. Sealing and loading
reconcile every vector bit with source-verified corpus records. The loader
checks bounded file structure, closed metadata, dimensions, nulls, row order,
exact membership and mapped buffer addresses before exposing any vector.

The numeric buffers are read-only views of the mapped file. A narrow Sequence
adapter returns ordinary Python floats when arithmetic reads a scalar, keeping
the same arithmetic order and precision as the existing native float32 values
represented in Python lists. Sample construction and adaptive evaluation
preserve this exact adapter type. Other inputs retain their ordinary copying
behavior, and serialization still materializes values deliberately.

Opt-in v7 jobs require the Arrow artifact and inherit v6's producer, source,
frozen-index and explicit validation checks. Existing v1–v6 job serialization,
the v4 default, and schema-less v2 behavior remain separate compatibility
contracts. Both the owner and worker verify the artifact. Worker mappings live
through sample construction and training, then close through the resource
scope. Workers retain private model updates and submit accepted sparse
artifacts to the existing single DuckDB owner for replay and registration.

This does not make all training zero-copy. Job JSON and source manifests still
contain vectors; verification parses them. Python scalar access allocates
scalars, metadata uses Python objects, explicit JSON serialization makes lists,
and Torch conversion allocates its own tensors. The optional mapped feature
weight table remains a separate capability. No SQL query is added to numerical
operations, and no new production DuckLake service is activated.

Read-only mappings assume owner-staged files remain immutable. Hash and file
identity checks detect persistent drift at opening and the final boundary;
they cannot prove no other process temporarily modified and restored the file.
Exported read-only NumPy views retain their backing memory until released;
closing invalidates access through the Sequence adapter. This is a storage
integrity contract, not runtime cryptographic attestation or legal admission.

## Native workload and measurements

The native script is
`scripts/ops/legal_ir/benchmark_produced_corpus_arrow_training.py`. Before target
generation it seals the first three record IDs in the previously frozen
training partition, plus all three frozen validation rows. It never reseeds
the split or substitutes easier rows following a failure. Source authority and
unseen-checkpoint history are not established, and the previously oversized
canary remains excluded.

The comparison uses the read-only restart12 checkpoint, five bridges
(`modal_frame_logic`, `deontic_norms`, `fol_tdfol`, `cec_dcec`,
`external_prover_router`), provers false, metric disk cache 0, sample memory
false, one bridge worker, CPU `python_sparse_batch`, one epoch, one update
family, one line-search attempt, max seconds 180 and temperature 0. Each job
starts in a fresh process. Shared modes reuse six complete sealed targets;
their evaluation timing is not cold target generation. OS cache warmth is
uncontrolled.

The [native receipt](evidence/autoencoder_control_plane_plan/produced-arrow-training-20260925.json)
passed. Complete-job time fell from **87.0047 seconds with fresh targets** to
**22.9321 seconds median with shared targets and JSON inputs**, 73.6% less.
There is one fresh observation and two observations per shared input mode;
these are bounded candidate-job timings, not daemon or full-corpus timings.

| Mode | Jobs | Complete job wall time | Wall time / training span | Initial bridge-on evaluate | Evaluate / validation span |
|---|---:|---:|---:|---:|---:|
| Fresh targets, JSON inputs/weights | 1 | 87.0047 s | 29.0016 s | 38.0530 s | 12.6843 s |
| Shared targets, JSON inputs/weights | 2 | 22.9321 s median | 7.6440 s | 5.9062 s median | 1.9687 s |
| Shared targets, mapped inputs, JSON weights | 2 | 23.0663 s median | 7.6888 s | 5.6221 s median | 1.8740 s |
| Shared targets, mapped inputs and feature weights | 1 | 23.4913 s | 7.8304 s | 5.7808 s | 1.9269 s |

Each job trains on three rows and evaluates three distinct validation rows.
Every before/after evaluation retains three targets, nonempty IR losses and
deontic metrics. All six shared targets are `ready`. Every process began with
an empty process target cache. Shared rows reuse sealed targets and therefore
do not measure cold target generation. Complete-job wall time includes dispatch
and owner durable completion; target loading is included there but excluded
from the evaluate column. Job preparation and one-time artifact creation are
reported separately in the receipt.

The two concurrent mapped-input jobs completed in **25.5073 seconds total**,
or 4.2512 seconds per training span across six processed training rows. Their
individual initial bridge evaluations took 5.6767 and 5.6221 seconds, each for
three validation rows. The two observed sequential mapped jobs totaled
46.1325 seconds. This demonstrates independent candidate throughput through
one owner, not shared-gradient or distributed-data-parallel training.

All eight jobs rejected their one proposed optimizer update. The attempted
`legal_ir_view_global_logits` update increased validation legal-IR view
cross-entropy by 0.2495118647, and the existing acceptance checks rejected it.
No accepted sparse segments were generated. Logical state identities remained
equal to the loaded base, and before/after final metrics were unchanged. This
is a speed qualification of the same rejected trial, not learning progress,
held-out generalization, or a nonempty accepted-patch corpus benchmark. Earlier
gate benchmarks and focused tests retain the accepted-patch evidence.

All shared modes produced identical complete evaluation dictionaries and
materialized candidate identities, including the combined mapped-weight mode
and both parallel workers. Fresh-versus-shared comparison preserves every
evaluation field except `legal_ir_target_hashes`; generated graph identities
include timestamps, and those hashes differed. Fresh graph payloads were not
byte-compared in this run. Materialized candidate bytes and all other evaluation
fields matched. The pinned archive itself retained its original SHA-256 and
25,895,338-byte length; materialized serialization is a separate identity.

Both immutable variant bindings and all eight completed runs survived DuckDB
restart. The branch head stayed on the base. Workers wrote sparse manifests
of 810–822 bytes and zero patch bytes, without full candidate JSON files. This
does not measure bytes saved for an accepted update. Retained benchmark files
totaled 62,231,984 bytes, including staged base, targets, feature weights,
database, sources, jobs and receipts; this is not physical-device write volume.

One-time target preparation took **72.9941 seconds**, including 68.5265 seconds
generating six targets (11.4211 seconds/span) and 0.2694 seconds constructing
samples. It produced a 5,043,216-byte bundle containing 70,139,177 expanded
target bytes, with no whole-target duplicates. Against the observed 64.0726
seconds saved per shared JSON job, preparation pays back at approximately two
equivalent jobs; this small-workload estimate excludes additional orchestration
costs and is not a corpus forecast.

The Arrow input artifact is 11,082 bytes with 9,216 mapped numeric bytes; sealing
and source verification took 0.2022 seconds. Each mapped run retained exactly
six row views and recorded 707,328 scalar accesses through training. JSON
verification took about 0.078 seconds, versus 0.289 seconds for the first
mapped-input job, including its additional binding checks. Mapped inputs were
0.6% slower in complete-job medians; there is no qualified speed improvement
from mapping these small inputs.

The existing feature-weight artifact is 6,656,154 bytes and took 0.2062 seconds
to materialize. It maps 3,337,088 numeric bytes plus offsets. The combined run
read 3,291 additional mapped rows during training without materializing feature
rows; the attempted update family did not modify feature weights. Its observed
after-training PSS was 1,139,270 KiB, versus 1,154,185–1,155,464 KiB in the two
shared JSON jobs. These snapshots and one combined run do not establish a
parallel-memory saving. Neither input nor feature-weight mapping becomes the
default on this evidence.

## Validation

The focused suites passed 246 worker/coordinator tests, 22 Arrow codec tests,
6 mapped sample/autoencoder adapter tests, 66 semantic/router tests and 9
existing sample/autoencoder regressions. Coverage includes exact float bits and
negative zero, Python and Torch float64 behavior, no-copy sample/evaluation
identity, compressed/oversized IPC rejection before decode, source and receipt
substitution, mapped-file drift, failure cleanup, owner reconciliation, and the
three required semantic gates. The initial development tests exposed a
signed-byte memoryview framing comparison; that was fixed before the passing
codec/adapter runs and native measurement.

The [semantic receipt](evidence/autoencoder_control_plane_plan/arrow-input-semantic-tests-20260925.json)
and [archived-job receipt](evidence/autoencoder_control_plane_plan/arrow-input-archived-jobs-20260925.json)
retain detailed evidence. All 39 prior v1–v4 job identities and both native v5
and both native v6 jobs remain unchanged on round-trip. The
[final validation receipt](evidence/autoencoder_control_plane_plan/produced-arrow-training-tests-20260925.json)
binds the final source hashes and native result to the test observations.

## Opportunity cost and next work

Input vectors in this bounded workload occupy only 9,216 numeric bytes before
IPC metadata. Mapping can avoid repeated list materialization and share those
pages across processes, but its integrity checks add work. This is not enough
to justify changing the default or extrapolating a full-corpus memory saving.
Measure complete jobs and owner persistence, not only a cheap vector lookup.

The measured larger opportunity remains amortizing complete target generation across
candidate jobs, bounding target hydration, and persisting accepted sparse
updates without rewriting the full checkpoint each epoch. The existing target
bundle and sparse version contracts provide these paths. This native comparison
now establishes exact shared-mode outcomes on actual source-bound corpus
records as well as the earlier public gates; it does not yet establish an
accepted weight improvement on the new corpus split.

Next profile the remaining shared-target evaluation/hydration work before
expanding numeric mapping. Projection updates took about 0.073 seconds in the
fresh job, versus 38.053 seconds for its initial evaluation and 38.903 seconds
priming training targets. This provides no reason to switch to CUDA. A broader
fixed training selection and qualified candidate families may improve learning;
acceptance thresholds and validation membership must remain intact.
Arrow-backed vector references in the job transport can remove remaining JSON
duplication; additional weight tables
need exact update/rollback parity; an index of bounded target bundles can scale
preparation without retaining whole-corpus graphs. Whole-source inventory,
explicit coverage for long inputs, source-aware Constitution training,
reviewed semantic support, Lake receipts and qualified HF publication remain
separate requirements. The Constitution is not formalized. Only an actual
`lake build <Lib>` is a Lean admit.

Follow-up: the [shared-target evaluation milestone](autoencoder_shared_target_evaluation.md)
profiles and optimizes repeated regex compilation and native target summary
serialization. It also clarifies that a target marked `ready` can retain an
adapter failure: the complete serialized object does not establish that every
bridge succeeded. Regenerated targets include additional bridge content, so
that report uses a same-bundle controlled comparison and preserves the failed
replication caused by a concurrent source edit.
