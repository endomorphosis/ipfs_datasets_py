# Cold shared-target preparation profile

Status: diagnostic profiling on six frozen source-bound U.S. Code samples,
2026-09-25. Both coarse and modal-detail runs completed with unchanged package
sources. Every target was ready and each report implemented all five bridges
without an adapter failure or outer timeout. No production implementation or
GC policy changed in this profiling slice.

The main cold-production cost is the modal bridge, particularly decompilation,
F-logic processing and reconstructed-text encoding. Redundant document
serialization and repeated loss-vector calls are too small to prioritize on
this batch. This finding supports retaining shared complete targets across
independent training jobs before expanding Arrow parameter mapping.

The [coarse receipt](evidence/autoencoder_control_plane_plan/cold-target-phase-profile-20260925.json)
comes from [profile_cold_target_preparation.py](../../../scripts/ops/legal_ir/profile_cold_target_preparation.py).
The [modal-detail receipt](evidence/autoencoder_control_plane_plan/modal-target-phase-profile-20260925.json)
uses a [separate extension](../../../scripts/ops/legal_ir/profile_modal_target_preparation.py)
that verifies the frozen coarse harness before adding method wrappers.
These are profiles of the actual `prepare_training_targets` path, not native
speed comparisons or training qualifications. Inclusive phases overlap.

| Measured phase | Coarse run | Modal-detail run |
| --- | ---: | ---: |
| Complete preparation, six samples | 61.7671 s | 60.5270 s |
| Preparation per source span | 10.2945 s | 10.0878 s |
| Target generation, six samples | 51.6810 s | 50.7453 s |
| Generation per source span | 8.6135 s | 8.4576 s |
| Five-bridge multiview evaluation, summed over six spans | — | 50.7254 s |
| Multiview evaluation per span | — | 8.4542 s |
| All adapter evaluations, 30 calls | 51.5801 s | 50.6478 s |
| Modal adapter alone, six calls | 50.8727 s | see nested breakdown below |
| Tagged target encoding, six calls | 5.2977 s | 5.0135 s |
| Target compression, six calls | 1.0590 s | 1.0549 s |
| Target validation, six calls | 0.7226 s | 0.7143 s |
| Sample construction, six calls | 0.2708 s | 0.2720 s |

The two diagnostic runs are not a before/after optimization comparison. Five
autoformal/publication source files changed externally between them, although
each run's complete source manifest remained stable during its own execution.
Their sealed configuration identities and bundle digests differ; neither
receipt licenses reuse under a later producer configuration. Target
generation bypassed target caches in a fresh process. The exact bridge order
was `modal_frame_logic`, `deontic_norms`, `fol_tdfol`, `cec_dcec`,
`external_prover_router`; external prover evaluation was false, metric disk
cache was 0, bridge and adapter workers were each 1, and sample memory was
false. Adapter workers were explicitly set to 1 here; an unset setting in the
earlier native qualification also resolved to 1, but has a different recorded
environment identity. CPU/offline settings were recorded. OS cache and host
contention were uncontrolled. No checkpoint was loaded and no training ran.

| Modal-detail boundary, summed over six samples | Inclusive time | Interpretation |
| --- | ---: | --- |
| Original codec acquisition | 3.4234 s | First call includes lazy imports; all six preserve fresh codec/encoder construction |
| Codec encoding | 46.1997 s | Contains most rows below; 6.6657 s remains exclusive to this boundary |
| Modal document decompilation | 16.6261 s | Largest measured inner phase |
| F-logic evaluation | 7.3733 s | Existing consistency and metadata work remains enabled |
| Reconstructed structural embedding | 5.7536 s | Almost all is the second spaCy encoder pass |
| Both source/reconstructed spaCy passes | 5.8452 s | Twelve calls; source-only calls sum to about 0.1709 s |
| Frame audit helpers | 5.0931 s | Terms 3.8366 s, feature keys 1.1719 s, triple additions 0.0847 s |
| Modal-to-F-logic triples | 2.4183 s | Six calls |
| Graph projection | 1.5416 s | Twelve calls, preserving both pre/post-audit graphs |
| Modal document hashing | 0.3642 s | Eighteen calls; several bind different intermediate documents |
| Final IR envelope | 0.2873 s | Includes serialization and hashing |
| Ontology construction | 0.2262 s | Twelve calls |
| Modal compilation | 0.1058 s | Six calls |
| Ontology export | 0.0436 s | Twelve calls |
| Modal document `to_dict` | 0.0380 s | Thirty calls |

The `modal_graph_to_dict` hook patches the shared `GraphData` class. Despite
its phase name, its 0.0256 seconds across 36 calls covers **all adapters**, not
only modal work. The report deliberately does not attribute that aggregate to
the modal bridge alone.

The other four adapters together took approximately 0.7074 seconds in the
coarse run. Repeated `training_target`, `loss_vector` and
`canonical_loss_vector` operations took only milliseconds. Eliminating their
duplicate calls would add compatibility work with little measured payoff.
Likewise, the final envelope serializes its completed modal document twice,
and ontology export renders frames twice, but those operations are small in
this profile. Earlier modal hashes bind different intermediate documents and
cannot simply be shared.

GC callbacks attributed 4.3013 of the coarse run's 5.2977 encoding seconds to
collection, compared with approximately 1.5169 seconds across adapter work.
The [qualified hydration policy](autoencoder_target_hydration_gc.md) cannot be
copied wholesale into the producer: the public writer consumes arbitrary
iterators and accepts generic mappings, and its encoded-byte bound is checked
after serialization. The separate [archived encoding experiment](autoencoder_target_encoding_gc_diagnostic.md)
now records two counterbalanced pairs: cleanup-inclusive encoding fell from a
4.1803-second median to 1.8986 seconds, with exact bytes and similar process
memory. Its hydrated inputs and pre-encoding full collection differ from the
producer's post-generation state. It does not qualify a production writer
policy or combine with these profiles into a forecast. Pausing GC across
target generation or an unconstrained writer remains unjustified.

The subsequent [targeted profile](evidence/autoencoder_control_plane_plan/frame-ontology-target-profile-20260925.json)
uses a [third standalone extension](../../../scripts/ops/legal_ir/profile_frame_ontology_target_preparation.py).
It enables cProfile only inside frame-audit terms and F-logic frame metadata,
and adds three coarse decompiler boundaries. Source guards and instrumentation
restoration passed. Profiling overhead caused **three modal adapter timeouts**
under the unchanged 15-second budget. All six rows were still `ready`, because
they contained targets from the surviving bridges; they were not six complete
five-bridge reports. This directly illustrates why `ready` or positive target
counts cannot replace bridge-failure accounting. No failed row was retried or
reselected, and these partial targets are not a native comparison baseline.

Within the profiled calls, `normalize_frame_ontology_term` consumed about 8.4%
of frame-audit time and 7.0% of F-logic metadata time. An early-stop token scan
therefore remains lower priority. Contextual predicate dispatch made
1,120,566 calls and accumulated 5.8577 profiled seconds; its Python prefix
generators alone executed about 15.1 million times. Across the two profiles,
`str.startswith` appeared over 41 million times. These are profiled call counts
and attribution, not uninstrumented savings estimates. A native tuple-prefix
check, with a fallback preserving overridden/custom behavior, is a smaller
candidate than an ontology-result cache or broad token-normalization rewrite.
Keep the complete-target parity gate and compare fresh native preparation
before making a speed claim.

The resulting [four-predicate implementation](autoencoder_frame_prefix_dispatch.md)
now has two counterbalanced native preparation pairs and 210 passing focused
checks. Median preparation fell 2.0%, with all five bridges retained; the
content audits explicitly retain the two existing per-target graph timestamp
differences and compare every remaining ordered value. This is a bounded
producer improvement, not an additional training or formalization result.

The added coarse decompiler boundaries measured 6.5960 seconds in 58 target
reconstruction-slot calls, including 1.6280 seconds in 628 target surface-profile
calls. Frame-ontology phrase generation itself took only 0.0076 seconds.
Surface profiles are recomputed within a reconstruction invocation, but any
reuse must preserve ordered phrase evidence and dynamic metadata/helper
behavior. This is a separate candidate; the current evidence does not justify
sharing hashes from different documents or caching mutable IR outputs.

Instrumentation preserves return values and exception propagation, restores
method bindings and GC callbacks, and leaves the existing main-thread
SIGALRM/ITIMER_REAL target timeout enabled. No signal sampler, background
thread or cProfile was used in these two runs. The observer keeps bounded
primitive phase records and at most six detached failure-telemetry outcomes;
it does not retain targets. Complete package hashes are checked before imports
and after preparation, and ordinary producer configuration checks remain in
place. Added clocks/callbacks still cost time and could affect a wall-time
timeout; `passed` describes diagnostic execution/provenance integrity, not
proof or native training qualification.

The broader [federal-law plan](../plans/FEDERAL_LAW_END_TO_END_TRAINING_PLAN.md)
still requires full source inventory and split qualification, accepted
corpus-training improvements, production DuckLake integration, and sealed
Hugging Face releases. Local DuckDB/Quack ownership and sparse updates keep
remote weight queries out of the training loop; they do not remove parser or
semantic costs. The Constitution remains unformalized. No Constitution span
is marked `roundtrip_ok`; only `lake build <Lib>` constitutes a Lean admit.
