# Xaman Runtime Trace Assumptions

Task: `PORTAL-CXTP-074`

The runtime trace report is `security_ir_artifacts/corpora/xaman-app/runtime-trace-report.json`.

## Purpose

The ingestor converts the pinned Xaman e2e feature inventory and reviewed source-model artifacts into monitor facts for:

- payload intake;
- review;
- auth;
- signing;
- rejection;
- expiration;
- network binding;
- broadcast;
- runtime equivalence.

The monitor facts are useful for proof obligations, but they are not production runtime evidence by themselves.

## Inputs

- Source manifest: `security_ir_artifacts/corpora/xaman-app/source-manifest.json`
- Environment probe: `security_ir_artifacts/corpora/xaman-app/environment-probe.json`
- Payload lifecycle model: `security_ir_artifacts/corpora/xaman-app/payload-lifecycle-facts.json`
- XRPL transaction model: `security_ir_artifacts/corpora/xaman-app/xrpl-transaction-facts.json`
- Wallet auth model: `security_ir_artifacts/corpora/xaman-app/wallet-auth-facts.json`
- Optional real-device trace directory passed with `--trace-dir`
- Optional DuckDB Firebase-mock database and run identifier passed together with `--firebase-mock-database` and `--firebase-mock-run-id`

## DuckDB Firebase-Mock Input

`XamanRuntimeTraceIngestor` can read the loopback-only Firebase mock created by `xaman_firebase_disabled_testnet.py`. It consumes only the mock's `xaman_firebase_mock_runs`, `xaman_firebase_mock_events`, and `xaman_firebase_mock_rejections` tables in read-only mode.

The adapter verifies the pinned Xaman commit, Testnet network label, declared versus observed event counts, and any redaction rejections. It reports only aggregate categorical event names, outcomes, and counts. It does not read event attributes or infer wallet, signing, account, payload, transaction, or XRPL network activity from Firebase telemetry.

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  -m ipfs_datasets_py.logic.security_models.crypto_exchange.extractors.xaman_runtime_trace_ingestor \
  --firebase-mock-database /home/barberb/.local/share/ipfs-datasets-xaman-testnet-verifier/testnet-firebase-mock.duckdb \
  --firebase-mock-run-id xaman-testnet-firebase-mock-001 \
  --out security_ir_artifacts/corpora/xaman-app/runtime/runtime-trace-with-firebase-mock.json
```

Library callers can use `XamanRuntimeTraceIngestor().ingest(...)` with the same `firebase_mock_database_path` and `firebase_mock_run_id` arguments. The report records this input as the supplemental `firebase_mock` monitor category with `wallet_or_xrpl_events_inferred: false`.

## Fail-Closed Runtime Policy

When no real-device trace bundle is supplied, the ingestor must keep the report blocked with:

- `REAL_DEVICE_TRACE_BUNDLE_MISSING`
- `RUNTIME_EQUIVALENCE_NOT_PROVED`

These blockers mean the package has monitor specifications and reviewed source evidence, but it has not proved that the deployed runtime executes the reviewed flows.

The Firebase mock cannot clear either blocker. It is only evidence that the replacement JavaScript boundary emitted redacted events to local DuckDB.

## NOT_MODELED Runtime Evidence

The report marks runtime equivalence as `NOT_MODELED` until real-device traces are supplied for the required categories. A sufficient trace bundle must contain reviewed events for payload intake, review display, auth gate, signing, rejection, expiration, network binding, and broadcast or no-broadcast outcome.

The trace bundle must also bind:

- Xaman source commit;
- device or simulator identity;
- app build provenance;
- environment probe;
- ledger endpoint or network configuration;
- timestamp and monotonic event order;
- signed payload or transaction identifiers when present;
- rejection or expiration result when applicable.

## Validation

Run:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_runtime_trace_ingestor.py -q
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m ipfs_datasets_py.logic.security_models.crypto_exchange.extractors.xaman_runtime_trace_ingestor --out security_ir_artifacts/corpora/xaman-app/runtime-trace-report.json
```

The expected current state is blocked until real-device traces are provided.
