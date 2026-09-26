# Native frame-predicate prefix dispatch

The frame selector now uses native tuple-prefix checks in four hot predicates,
while preserving the original per-prefix path for custom values and replaced
prefix collections. In two counterbalanced cold-preparation pairs, median
six-sample preparation fell from **61.13 to 59.90 seconds (2.0%)**. Target
generation fell from **8.54 to 8.31 seconds per source span (2.8%)**. This is a
small producer improvement; it does not establish a training-loop speedup or
additional formalization.

The [four-run comparison](evidence/autoencoder_control_plane_plan/frame-prefix-native-comparison-20260925.json)
binds the [uninstrumented harness](../../../scripts/ops/legal_ir/benchmark_cold_target_preparation.py)
and the fixed six source-bound U.S. Code inputs. The sequence was
reference/candidate/candidate/reference, each in a fresh process. All package
sources remained stable inside each run, and the only source difference across
the successful reference and candidate runs was
`optimizers/logic_theorem_optimizer/frame_bm25_selector.py`.

| Native cold measurement | Reference | Candidate |
| --- | ---: | ---: |
| Pair 1 preparation | 61.163553 s | 59.641548 s |
| Pair 2 preparation, reversed order | 61.103963 s | 60.152088 s |
| Median preparation, six spans | 61.133758 s | 59.896818 s |
| Median preparation per span | 10.188960 s | 9.982803 s |
| Median target generation, six spans | 51.262797 s | 49.851390 s |
| Median target generation per span | 8.543799 s | 8.308565 s |

The bridges were `modal_frame_logic`, `deontic_norms`, `fol_tdfol`, `cec_dcec`,
and `external_prover_router`, in that order. External prover evaluation was
false, metric disk cache 0, bridge workers 1, adapter workers explicitly 1,
sample memory false, and CPU/offline settings unchanged. The original
15-second per-target timeout stayed enabled. Each run had six targets and six
complete five-bridge reports, with no bridge failures or timeouts. The original
codec's F-logic consistency and metadata processing remained enabled.

These are cold target-generation runs with no preceding generation in each
process; OS cache and host contention were uncontrolled. No internal profiling
wrapper, GC callback or cProfile hook ran. The preparation entry point's own
timing includes sample construction, target generation, validation, encoding,
compression and its configuration checks. Whole-process startup, input
verification and the harness's later artifact audit are outside that interval.
Two pairs on one six-row selection qualify this bounded comparison, not
corpus-wide runtime, concurrency capacity or a held-out model improvement.

No checkpoint evaluation or training ran in this comparison. Target generation
includes cold multiview bridge evaluation and construction of the complete
target; it is not `AdaptiveModalAutoencoder.evaluate`. The last separately
qualified [shared-target training measurement](autoencoder_target_hydration_gc.md)
reported roughly four seconds for three validation targets, on its explicitly
recorded earlier sources. That is historical context, not a new measurement
of this prefix change.

The [first-pair content audit](evidence/autoencoder_control_plane_plan/frame-prefix-native-target-parity-confirmed-20260925.json)
and [second-pair audit](evidence/autoencoder_control_plane_plan/frame-prefix-native-target-parity-pair2-20260925.json)
verify artifact/shard hashes and compare complete ordered tagged target
structures. Fresh graph creation produces two timestamp differences in each
target: `document.views["deontic_norms.deontic_graph"].payload.metadata.created_at`
and `last_updated`. The audit retains both values and permits only those exact
leaf paths. Every other typed value, mapping order, array order and numeric
target output must match. No artifact is rewritten and no generic timestamp
stripping occurs. **Raw bytes, document hashes and artifact identities are
different**, and their ordinary production checks remain intact.

`DeonticGraph` creates and updates these values with the UTC wall clock and
exports them unchanged. Native deontic numeric losses use separate graph
counts, and multiview weights use view names/counts/selected sequence lengths.
The native autoencoder target path consumes the numeric losses and view
distribution; the timestamp values affect the canonical hashes retained in
target and cached summaries. The content audit therefore establishes equality of the
remaining recorded target structure and numeric outputs, not interchangeable
producer configurations or unrestricted metadata equivalence.

The [selector change](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/frame_bm25_selector.py)
adds three identity anchors and changes only
`_is_contextual_frame_ontology_predicate`, `_is_slot_frame_ontology_predicate`,
`_predicate_allows_numeric_ontology_tokens`, and
`_predicate_allows_single_character_alpha_tokens`. The native branch requires
an exact string and the original immutable prefix tuple. Normalization,
aliases, count suffixes, explicit memberships and early returns retain their
order. Custom normalized strings, replacement lists/iterators and their
exceptions use the original generator. No results, texts or mutable IR are
cached. Source SHA after restoration is
`feb8d74a8a87783408025f1a341500b734a396b99c757f1e65026e4abb26b437`.

All **210 focused checks passed**: 60 new
[prefix compatibility tests](../../../tests/unit/optimizers/logic_theorem_optimizer/test_frame_ontology_prefix_dispatch.py),
133 existing selector tests, and the 17
[semantic gates](../../../tests/unit/logic/test_autoformal_speed_semantics.py).
They cover every declared prefix, unusual inputs, custom normalization/aliases,
iterator failures and short-circuit behavior, numeric citations, suffixes and
modal stopwords. The semantic gates retain parser-supplied string atoms,
empty-vocabulary abstention, temporal wording and Lean-rendering restrictions.
The [focused receipt](../../../workspace/test-logs/federal-corpus-audits/frame-prefix-dispatch-20260925/focused-validation.json)
records the exact production/test hashes. Two initial new-test expectations
used the wrong existing numeric-predicate name; only those expectations were
corrected, and both test logs are preserved. The separate
[semantic XML](../../../workspace/test-logs/federal-corpus-audits/frame-prefix-dispatch-20260925/semantics.xml)
records all 17 passing gates.

The initial [reference attempt](evidence/autoencoder_control_plane_plan/frame-prefix-reference-20260925.json)
was rejected after an external edit to `processors/legal_data/legacy_migration.py`.
It remains a failed receipt and contributes no successful timing. A new process
completed the reference under the new stable source manifest. For the reversed
pair, only this change's selector edits were temporarily undone and then
restored at the same canonical path, with exact before/after SHA guards and
[durable transition records](../../../workspace/test-logs/federal-corpus-audits/frame-prefix-dispatch-20260925/source-transitions.jsonl).
The tested candidate is the final workspace version. HACC and `hallucinate_app`
were not changed or selected.

An external edit to `logic/autoformal/supervisor_queue.py` occurred after the
successful comparisons. The recorded historical pairs remain valid, but their
sealed producer configurations are not the later working tree's configuration.
Ordinary target compatibility guards remain unchanged; regenerate targets
before training against that later tree. The
[final validation inventory](evidence/autoencoder_control_plane_plan/frame-prefix-final-validation-20260925.json)
records this difference, the restored implementation, test/evidence hashes,
unchanged pinned checkpoint and named-root storage observation.

The [cold profiles](autoencoder_cold_target_profile.md) explain the opportunity
cost. Repeated predicate prefix dispatch was measurable; full-document
serialization and loss-vector duplication were small. Broader token
normalization, decompiler-profile reuse and a producer GC policy would need
additional compatibility work. The separate
[encoding GC experiment](autoencoder_target_encoding_gc_diagnostic.md) found a
larger isolated codec opportunity but did not qualify a production writer.
Shared targets still amortize the larger generation cost across candidates,
and the [federal-law plan](../plans/FEDERAL_LAW_END_TO_END_TRAINING_PLAN.md)
keeps sparse owner-controlled updates and optional Arrow mapping on that path.

No model weights, checkpoint, context window, temperature, target format,
admission rule or production GC policy changed. No DuckLake activation or
Hugging Face publication occurred. The Constitution remains unformalized and
no Constitution span is marked `roundtrip_ok`. Only `lake build <Lib>`
constitutes a Lean admit.
