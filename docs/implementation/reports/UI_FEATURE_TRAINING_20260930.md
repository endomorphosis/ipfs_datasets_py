# UI DOM/IDL feature training and projections — 2026-09-30

The local UI route now accepts explicit DOM/ARIA snapshots, verified MCP-IDL
descriptors and component-to-method bindings. It prepares native structural
targets, trains/registers a private DuckDB candidate, resumes its exact parent
and optimizer, and performs separate feature inference. The
[guide](../../autoencoders/ui_datasets_and_bindings.md) contains commands,
[authored fixtures](../../../examples/ui_ux_ir/training/README.md), source schemas,
HF dataset research and the remaining object-broker integration work.

## Implemented behavior

- Five requested views: `ui_ux_ir:flogic`, `ui_ux_ir:event_calculus`,
  `ui_ux_ir:tdfol`, `ui_ux_ir:dcec`, `ui_ux_ir:interface_bindings`. The last is
  a structural frame view of explicit verified method contracts, not another
  logic family or a parser-checked frame-logic formula.
- Bounded local JSONL inputs; closed source rows; actual descriptor CID checks;
  inline, locally supported JSON Schema drafts. References, unknown drafts,
  schema normalization drift, ambiguous bindings and streaming are rejected.
- Training/tuning group and source-record exclusions, including cumulative
  training history. Test/canary rows cannot silently become tuning examples.
  Supplied source/group labels are trusted metadata; near-duplicate detection
  remains an importer responsibility.
- Training-only structural vocabulary, fixed tuning identity, per-view
  reconstruction/cosine-loss regression checks, exact Adam resume, immutable
  parent artifacts and candidate-only registration. Selected source/dependency
  fingerprints bind compatibility; this is not a full frozen runtime capsule.
- Separate inference without optimization or candidate registration. Registry
  access remains serialized and exclusive, including inference.
- One owned CPU worker with one numerical thread; real process-group accounting,
  an independent 50 ms RSS/deadline watchdog, retained failure claims and durable
  success closeout. Memory enforcement is sampled, not a kernel quota.
- Pure mediated request/result projections check schemas and current correlation,
  including argument-bound request digests. They do not execute transport,
  authenticate a backend or apply UI state changes.

## Validation

**175 tests passed** across new inputs, training/resume, resource supervision,
request/result checks, existing native numerical training, and UI compiler,
roundtrip, mediator and MCP adapter tests. Resource regressions include a short
80 MB allocation during a deliberately slow disk census, memory/deadline
termination during that census, and descendant cleanup.

Four owned CLI attempts succeeded on the canonical tree. Inputs were six
authored rows: two initial training rows, one incremental training row, two fixed
tuning rows and one inference row. The third training attempt revisited the
incremental row to verify the revised watchdog. These fixtures declare synthetic
events and application behavior; they are not real HF examples or human traces.

| Attempt | Train/tuning rows | Attempted / cumulative selected epochs | Tuning objective before → after | Target preparation | Numerical training |
| --- | --- | --- | --- | --- | --- |
| Initial | 2 / 2 | 3 / 3 | 0.263801 → 0.089572 | 0.302 s | 0.663 s |
| Resume, new row | 1 / 2 | 1 / 4 | 0.089572 → 0.065245 | 0.279 s | 0.610 s |
| Resume, watchdog verification | 1 / 2 | 1 / 5 | 0.065245 → 0.045217 | 0.281 s | 0.614 s |

All five views remained populated. Preparation averages were approximately
0.075–0.094 seconds per input row, counting training and tuning rows together.
Every attempt prepared fresh targets with no target cache. This native UI route
uses no legal metric bridges, external provers, pretrained weights or GPU.
These are structural tuning metrics, not held-out semantic quality or legal-IR
speed measurements. The feature basis reports out-of-vocabulary tuning atoms;
it does not silently learn its vocabulary from tuning data. `cosine` in the
per-view receipts denotes cosine **loss**, so lower is better.

The complete CLI wall times were 43.55 seconds for the first resume, 46.43
seconds for watchdog verification and 45.86 seconds for inference. Initial CLI
wall time was not separately captured. Worker-supervision wall times were 14.54,
14.59, 17.45 and 16.82 seconds respectively; these include blocking accounting
checks and are not optimizer-only durations. Repeated global resource censuses
dominate these tiny jobs. Numerical throughput alone therefore cannot predict
end-to-end corpus throughput; batching more rows per admitted job is the next
measurement to make before optimizing the census.

The final training/inference watchdogs observed 764,907,520 / 638,312,448 bytes
of group RSS over 92 / 81 samples. The first two runs used only census-paced
sampling, which missed their short compute peaks; their recorded ~25 MB readings
must not be interpreted as model memory requirements. Each attempt requested
128 MB storage, 4,096 MiB memory, one CPU slot and one child slot against the
existing ledger. All four reservations released after durable closeout. The
campaign cap was unchanged.

Inference returned one row, performed no optimizer update and left all three
artifact files byte-identical. Two local IDL smokes checked a catalog fixture
and the same delete binding present in a training source row. Invalid arguments,
invalid results, mismatched correlation and denied policy were rejected. The
fixture's confirmation/policy values were authored test inputs, never real-world
execution grants. No backend operation ran.

## Evidence and remaining scope

- [Test validation and exact file hashes](evidence/ui-training-wiring-20260930/validation.json)
- [Training, resume, inference, timings and resource summaries](evidence/ui-training-wiring-20260930/native-smoke.json)
- [Local IDL boundary checks](evidence/ui-training-wiring-20260930/idl-smoke.json)
- [Training-row binding through mediated request/result projection](evidence/ui-training-wiring-20260930/bound-idl-smoke.json)

No dataset or model weights were downloaded, and no HF upload occurred. The HF
research recommends UI/action sources separately from typed-call sources; no
reviewed corpus supplied the complete UI-to-backend evidence join. A real
application capture/importer, authenticated executor, response-to-state mapping,
native distributed/Arrow/Hub codec and independent semantic qualification remain
separate work. Existing legal transport cannot accept this native codec merely
by changing a modality name.

All candidates retain `qualified=false`, `admitted=false`, `formalized=false`
and `promotion_performed=false`. UI compiler structure and numerical improvement
do not confer syntax/proof qualification. Legal admission remains the actual
source-locked `lake build <Lib>` path. The protected restart12 checkpoint retained
SHA-256 `1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd`.
No Constitution span was formalized.
