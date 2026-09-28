# Native inference and training route smoke — 2026-09-28

Two controlled minimum-duration fixtures (20 and 25 days), with a disjoint 30-day tuning-validation fixture, ran through separate inference and training routes on one host. These are qualification fixtures, not US Code or Constitution provisions.

- Inference: two qualified immutable-checkpoint passes, no optimizer, model registry, weight outputs, or uploads; 30.631 seconds for the full route (15.316 seconds per input, amortized).
- Training: two concurrent native worker jobs, one accepted epoch each, followed by exact-candidate qualification; 48.066 seconds for the full route (24.033 seconds per input, amortized).
- Initial cold bridge-on evaluate: 5.168 and 5.431 seconds, each one sample and one target, all five named bridges, prover calls off, metric disk cache disabled, bridge workers 1. Process caches warmed within each job; subsequent line-search evaluates averaged approximately 0.103 seconds and are not cold results.
- Eight actual `lake build Legal` invocations succeeded, alongside unchanged embedding metrics, semantic roundtrip checks, and six syntax-family checks. Lake proves source-locked numeric threshold boundaries for these fixtures; this is not full federal-law formalization or evidence that the autoencoder generates formal text.
- Both routes resumed on the same state with CPU affinity reduced to one core: planned concurrency dropped from two to one and no completed inference or optimizer pass repeated. Logical training topology stayed at 32 lanes.
- Four owned reservations (initial runs and resumes) were released durably; all 133 pre-80GB reservation records remain exactly unchanged. The campaign cap remains 80GB.

`native-summary.json` records exact candidates, metrics, cold/warm timing scopes, capacity plans, and sampled CPU-progress intervals. Process observations support overlapping worker activity, but do not establish simultaneous optimizer and inference math kernels. No controlled speedup comparison was performed. Tuning validation is repeatedly selected and is not an independent held-out canary. The Constitution remains unformalized.

All copied files are byte-identical to their workspace originals according to `artifact-manifest.json`. Full weights, sparse weight payloads, database files, credentials, compiled Lean output, and caches are excluded. Source hashes in native receipts delimit the tested implementation; `source-scope.json` identifies native workspace dependencies that differ from the scoped planned publication. Later regression checks do not expand the native proof scope.
