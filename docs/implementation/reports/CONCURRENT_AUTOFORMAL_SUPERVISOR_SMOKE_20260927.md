The first concurrent autoformalization smoke stopped at native supervisor setup. It did **not** run span conversion, compiler/decompiler checks, autoencoder training, or a legal-IR bridge evaluation. No law was admitted or formalized, and no compiler repair or model promotion occurred.

The current nested `external/ipfs_datasets/ipfs_accelerate_py` supervisor created a real DuckDB task claim, then settled the task as **blocked** with `database Portal attempt parent is unavailable`. Its execution and coordination attempt statuses are `failed`; provider invocations and effects are both zero. The native claim was released. The separate campaign storage reservation remains retained. See the [native supervisor receipt](evidence/concurrent-autoformal-supervisor-smoke-20260927/r1/supervisor/supervisor-receipt.json).

The driver supplied a state path without creating its parent directory. `DatabasePortalExecutionBridge._seal_attempt_directory` requires that existing parent before sealing its attempt directory. The prepared fix creates the new private `runtime/state` directory before constructing the daemon. It preserves the native directory, dependency, validation, scope, and completion checks. All eight R1 preparation files were copied byte-for-byte into a private snapshot before that edit.

| Observation | R1 result |
| --- | ---: |
| Root-owned attempt wall time | 91.832829964 seconds |
| Native supervisor phase wall time | 24.984506400 seconds |
| Peak sampled owned-descendant RSS | 258,248,704 bytes |
| Captured files after database close | 62 |
| Captured apparent bytes after database close | 40,924,463 bytes |
| Campaign reservation retained | 80,000,000 bytes |
| Conversion/training lanes started | 0 |
| Native provider invocations / effects | 0 / 0 |

The earlier 30,449,456-byte usage sample preceded final DuckDB checkpoint growth and is not the final artifact size. The closed task, coordination, and execution databases alone occupy 39,882,752 bytes. All owned children were confirmed dead and reaped; the root child exited with code 1. The [audit receipt](evidence/concurrent-autoformal-supervisor-smoke-20260927/r1/audit-receipt.json), [terminal receipt](evidence/concurrent-autoformal-supervisor-smoke-20260927/r1/child-terminal.json), and [retention receipt](evidence/concurrent-autoformal-supervisor-smoke-20260927/r1/resource-retention.json) retain the failure. Reservation ID: `197b8975b9ef44e5a4950ba88bc52317`.

The post-run campaign census reports 61,930,106,185 bytes charged against the approved 62,000,000,000-byte cap, leaving 69,893,815 bytes. The ledger has 88 records: all 87 pre-existing records are unchanged, plus this retained attempt. No failed claim or artifact was removed to create room.

A fresh R2 is prepared but has **not run**. Its proposed admission remains 80 MB reserved + 80 MB expected growth + 5 MB margin = 165 MB, with two CPUs, 8 GiB memory, and a 600-second outer deadline. The proposed campaign cap increase to **62.2 GB** is awaiting user approval; the cap, ledger, and wrapper assertion have not been changed by this preparation. The 50 GB per-worker limit remains unchanged. A 35 MB retry would be smaller than the already measured database footprint.

The intended R2 uses the real deterministic-only native Portal lifecycle in a new private Git fixture. Its declared pytest plan launches source conversion and bounded native autoencoder training concurrently, then verifies their immutable receipts on subsequent validation passes. Compiler/decompiler behavior is checked through its existing code; it is not described as weight training. Completion would apply only to that smoke task. Lake remains the only Lean admission path, and no Constitution span is marked `roundtrip_ok`.

Receipt SHA-256 values, verified during read-only report preparation:

| Receipt | SHA-256 |
| --- | --- |
| Native supervisor | `0a9b99a3c0df9d24b59502ea811ac55bd58318e1aa3d71dff8ea351f63e6e9fd` |
| Root audit | `da6a1cf9d1059f57bcd7a706aada34eea78a20485ab1d17bf11022dbb05d45c2` |
| Terminal child | `47a0dac07a9f939bb99e1a80cd5c520544237bcad66cca9c7aa14914e894375e` |
| Retained reservation | `91f5fc2e1836617edc3726a1a7d334bf13200797630a15844a31788fe0d1ea77` |
| Child source observations | `7a81f521857468d54c0d161323bc5f2ce2f3c965e96a6f791a60f5782624c72c` |
| Prepared inputs | `1c6456d4295c9dcebbea3595b7d78870293396e71f82105c6c54a832f4d92fdd` |

The [evidence manifest](evidence/concurrent-autoformal-supervisor-smoke-20260927/manifest.json) binds the original R1 harness, exact failure receipts, corrected R2 harness, and unapplied cap proposal. Seven focused tests passed against the proposed resource module, and six migration checks passed on temporary fixtures. The live cap and ledger remain unchanged. The protected restart12 checkpoint still has 25,895,338 bytes and SHA-256 `1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd`.

R2 is configured for all five bridges: `modal_frame_logic`, `deontic_norms`, `fol_tdfol`, `cec_dcec`, and `external_prover_router`. Provers are disabled, metric disk cache is disabled, bridge workers are one, and sample memory is disabled. Three synthetic gate fixtures train one bounded sparse projection epoch; two distinct fixtures serve optimizer acceptance validation, not an untouched canary. The concurrent conversion lane checks the three required semantic gates and preserves gaps from three retained US Code spans. These are planned settings, not completed measurements.
