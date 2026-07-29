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

## Fail-Closed Runtime Policy

When no real-device trace bundle is supplied, the ingestor must keep the report blocked with:

- `REAL_DEVICE_TRACE_BUNDLE_MISSING`
- `RUNTIME_EQUIVALENCE_NOT_PROVED`

These blockers mean the package has monitor specifications and reviewed source evidence, but it has not proved that the deployed runtime executes the reviewed flows.

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
