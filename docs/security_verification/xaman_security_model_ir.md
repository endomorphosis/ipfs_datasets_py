# Xaman SecurityModelIR Baseline

Task: `PORTAL-CXTP-068`

The baseline IR is `security_ir_artifacts/corpora/xaman-app/security-model-ir.json`.

The deterministic CID is `security_ir_artifacts/corpora/xaman-app/security-model-ir.cid`.

## Bound Corpus

- Repository: `https://github.com/XRPL-Labs/Xaman-App`
- Commit: `942f43876265a7af44f233288ad2b1d00841d5fa`
- Source manifest: `security_ir_artifacts/corpora/xaman-app/source-manifest.json`

## Bound Artifacts

The IR binds:

- environment probe;
- wallet auth facts;
- payload lifecycle facts;
- XRPL transaction facts;
- security claims and blocking assumptions;
- runtime trace monitor report;
- optional solver install/probe report.

## Proof State

The IR includes proof obligations and disproof vectors for every Xaman claim. Obligations are intentionally `UNKNOWN` or `NOT_MODELED` until solver tasks run.

The release decision remains:

`BLOCK_SECURITY_CLAIMS_PENDING_PROOFS_AND_ASSUMPTIONS`

## Blocking Boundaries

The IR does not prove:

- native vault cryptographic correctness;
- backend payload API authorization, expiration, and atomic single-use;
- XRPL consensus, node honesty, queue, mempool, or finality;
- deployed runtime equivalence;
- transaction classes with TODO validation functions;
- proof-consumer receipt kernel correctness.

## Validation

Run:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_security_model_ir.py -q
```
