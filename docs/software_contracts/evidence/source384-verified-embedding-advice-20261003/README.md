# Verified embedding file advice, 2026-10-03

The shared cached-GTE verifier accepts an explicit `release_verified_pages=False` option. Default callers keep ordinary verification. Source384 opts in and records `verified_snapshot_dontneed_best_effort@1` in its inference key, alongside an explicit hash of the verifier source.

The opt-in holds the nine asset descriptors until every pinned byte count, SHA-256 and descriptor identity passes. It then requests `POSIX_FADV_DONTNEED` on those same descriptors and closes them without another body read. Unsupported advice is best effort. Native `TimeoutError` is propagated, and all held descriptors are closed on failures. In-cache Hugging Face blob links remain supported; external targets are rejected.

Current on-disk qualification is **47 distinct passing tests**: 23 authored advice/context controls plus17 existing embedding-runtime controls, and7 native Source384 source-map/checkpoint/inference/cold-replay controls. The earlier40 overlay controls are retained separately and are not additional coverage. The native fixture used the unchanged real checkpoint/GTE assets, produced four unverified candidates and one token deferral from five functions, and replayed after reopening the registry without inference. Existing source mutation and tampered map/output checks remain active.

The native test process selected the existing shared ledger through its canonical configured-client API:16 CPU slots,99688MiB memory,24922MiB headroom and the native resource sampler. It did not reset the ledger, change thresholds, or qualify default host startup. These values differ from older qualification environments. The before/after source-free receipts preserve the actual profile.

This component evidence does **not** demonstrate memory reclamation, Docker admission, a complete supervisor run or benchmark reward. The verifier necessarily reads67691071 bytes; actual cache refill and freed memory were not measured. Advice may partly succeed before a later hint fails. No weights, benchmark source, database, private credentials or raw scheduler capabilities are included. The source hashes and requested policy deliberately produce new Source384 inference keys; old receipts remain historical. Numerical checkpoint architecture and weights are unchanged.

The source review was completed before the native7 run and accurately records that run as pending at review time. `qualification.json`, final XML and commands record its subsequent success. All advice experiments retain the original native resource and time bounds.
