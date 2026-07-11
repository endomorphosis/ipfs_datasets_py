# Xaman Testnet SecurityModelIR Review

Task: `PORTAL-CXTP-131`

The reviewed Testnet transaction lifecycle trace is projected into:

- `security_ir_artifacts/corpora/xaman-app/testnet/security-model-ir.json`
- `security_ir_artifacts/corpora/xaman-app/testnet/security-model-ir.cid`
- `security_ir_artifacts/corpora/xaman-app/testnet/claim-trace-map.json`
- `security_ir_artifacts/corpora/xaman-app/testnet/assumptions.json`

Model CID:

`sha256:4edaad61130b6851220b6a75fa86a52b17e1baf33a8631def2879b0464366b43`

## Source Evidence

The projection binds to reviewed dependency artifacts from `PORTAL-CXTP-121`, `PORTAL-CXTP-125`, `PORTAL-CXTP-126`, and `PORTAL-CXTP-130`:

- `security_ir_artifacts/corpora/xaman-app/runtime/testnet-transaction-lifecycle-evidence.json`
- `security_ir_artifacts/corpora/xaman-app/runtime/testnet-transaction-trial-report.json`
- `security_ir_artifacts/corpora/xaman-app/runtime/testnet-network-selection-report.json`
- `security_ir_artifacts/corpora/xaman-app/runtime/testnet-device-trial-report.json`
- `security_ir_artifacts/corpora/xaman-app/runtime/native-firebase-boundary-report.json`

The source commit remains `942f43876265a7af44f233288ad2b1d00841d5fa`.

## Projection Rules

Every reviewed lifecycle event is mapped to a typed Testnet model fact, a source line range, one or more claims, one or more assumptions, and the retained redaction digest. Duplicate action names, duplicate ordinals, non-reviewed UI source kinds, raw-material records, stale dependency artifact CIDs, or mismatched lifecycle evidence hashes are rejected by `scripts/ops/security_verification/project_xaman_testnet_security_model.py`.

No unreviewed source-derived fact is admitted. All IR evidence refs are `manual_review` with `human_reviewed` status.

## Claim Coverage

The Testnet claim set covers:

- network binding;
- account provenance;
- review/auth sequence;
- signing decision;
- submission UI attempt/result;
- refusal;
- replay;
- expiry;
- cancellation;
- payload boundary;
- broadcast boundary;
- audit/redaction boundary.

Observed claims remain Testnet-scoped and proof-pending. Gap claims are explicitly `NOT_MODELED`.

## NOT_MODELED Boundaries

The trace map and model metadata retain explicit `NOT_MODELED` records for payload, signing, network, replay, cancellation, expiry, broadcast, and refusal behavior not represented by reviewed evidence.

These records block production or secure-result acceptance until reviewed replacement evidence exists:

- raw payload JSON, semantic validation, and digest-to-signed-byte binding;
- raw signatures, signed transaction blobs, and native vault cryptographic correctness;
- production runtime equivalence and endpoint-authenticity claims beyond the Testnet verifier run;
- replay, duplicate submit, backend atomic single-use, conflict handling, and expiry enforcement;
- cancellation and refusal/decline runtime paths;
- XRPL broadcast request material, mempool/queue behavior, validated-ledger inclusion, and finality.

## Release Boundary

The model is public-Testnet verifier evidence only. It keeps `production_release_blocked: true`, `runtime_equivalence_status: not_proved`, and the native Firebase packaging boundary. It cannot approve production Xaman behavior or replace the baseline Xaman source model.

## Validation

Run:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_testnet_model.py -q
```
