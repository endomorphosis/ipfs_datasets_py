# Xaman Testnet Adversarial Fuzzing

Task: `PORTAL-CXTP-148`

The adversarial Testnet fuzzing expansion writes:

- `security_ir_artifacts/corpora/xaman-app/testnet/fuzz/campaign-manifest.json`
- `security_ir_artifacts/corpora/xaman-app/testnet/fuzz/counterexamples/manifest.json`
- `security_ir_artifacts/corpora/xaman-app/testnet/fuzz/counterexamples/*.json`

The generator is `scripts/ops/security_verification/run_xaman_testnet_fuzzing.py`.

## Scope

This is bounded adversarial coverage over the reviewed public-source XRPL Testnet model and the claim/source map from `PORTAL-CXTP-145` plus XRPL transaction coverage from `PORTAL-CXTP-146`. It does not claim exhaustive wallet input coverage, does not prove production runtime behavior, and does not clear native vault, biometric, backend single-use, ledger finality, or RPC trust blockers.

The run binds to:

- `security_ir_artifacts/corpora/xaman-app/testnet/security-model-ir.json`
- `security_ir_artifacts/corpora/xaman-app/testnet/security-model-ir.cid`
- `security_ir_artifacts/corpora/xaman-app/testnet/claim-trace-map.json`

## Registered Domains

The campaign manifest registers exactly these fuzz domains:

- `malformed_payload`
- `replayed_payload`
- `wrong_network`
- `account_import`
- `stale_downgraded_evidence`
- `auth_review_bypass`
- `cancellation_expiry_reconnect_race`
- `transaction_type_mutation`
- `solver_result_tampering`

Each domain lists its bounded input space, target claims, and generated case IDs. Any explicit fuzz domain outside this registry is rejected as `UNMODELED` by `validate_registered_fuzz_domain`; unregistered domains are never silently treated as proof evidence.

## Counterexample Minimization

Every discovered adversarial mutation is written as a minimized counterexample. The minimizer records a single registered fuzz domain, the minimal categorical mutation keys needed to trigger the target claim, the minimized payload digest, and a redaction assertion. Counterexample artifacts retain only categorical markers and digests; they do not retain raw payload JSON, credentials, account material, transaction blobs, signatures, seeds, or addresses.

## Acceptance

The expansion passes only when:

- all registered domains are covered by at least one adversarial case;
- every expected mutation triggers its target claim;
- every counterexample has `minimization.status: minimal`;
- malformed SecurityModelIR inputs are rejected by strict parsing;
- redaction breaches are rejected;
- fuzzer crashes are zero;
- explicit unregistered fuzz domains are rejected as `UNMODELED`.

The current campaign records `overall_status: passed` and keeps the legacy bounded fuzz report available at `security_ir_artifacts/corpora/xaman-app/testnet/fuzz/fuzz-report.json` for existing proof-portfolio consumers.

## Validation

Run:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_testnet_adversarial_fuzzing.py -q
PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/run_xaman_testnet_fuzzing.py --out security_ir_artifacts/corpora/xaman-app/testnet/fuzz/counterexamples/manifest.json
```
