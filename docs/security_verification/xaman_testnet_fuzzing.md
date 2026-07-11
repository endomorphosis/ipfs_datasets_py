# Xaman Testnet Fuzzing

Task: `PORTAL-CXTP-138`

The deterministic Testnet fuzz campaign writes:

- `security_ir_artifacts/corpora/xaman-app/testnet/fuzz/fuzz-report.json`
- `security_ir_artifacts/corpora/xaman-app/testnet/fuzz/counterexamples/`

The generator is `scripts/ops/security_verification/run_xaman_testnet_fuzzing.py`.

## Scope

This is bounded generated coverage over the reviewed XRPL Testnet transaction lifecycle model from `PORTAL-CXTP-131`. It is not all possible wallet inputs, does not prove production runtime behavior, and does not clear any `NOT_MODELED` boundary from the Testnet SecurityModelIR.

The campaign binds to:

- `security_ir_artifacts/corpora/xaman-app/testnet/security-model-ir.json`
- `security_ir_artifacts/corpora/xaman-app/testnet/security-model-ir.cid`
- `security_ir_artifacts/corpora/xaman-app/testnet/claim-trace-map.json`

## Campaigns

The fuzz report contains three deterministic campaign lanes.

`trace-mutation-campaign` mutates the reviewed lifecycle trace and requires rejection for duplicate actions, duplicate ordinals, reordered signing/auth events, unreviewed source-derived facts, raw-material retention, redaction breach fields, missing coverage gaps, wrong network scope, production/imported account scope, and changed submit-result outcomes.

`malformed-security-ir-parser-campaign` feeds malformed SecurityModelIR payloads through strict untrusted parsing. Unknown top-level fields, missing required top-level fields, wrong collection types, non-mapping records, duplicate claim IDs, unknown domains, forged proof statuses, invalid solver results, unsupported prover targets, and unknown runtime trace event references must be rejected.

`expected-attack-mutation-campaign` applies categorical attack mutations for payload material, signing material, auth ordering, wrong network, imported production account provenance, replay, decline/cancel/expiry gap promotion, forged broadcast/finality proof, and submit-result removal. Each mutation must trigger its target Testnet claim.

## Acceptance Gates

The run fails closed if any of these occurs:

- fuzzer crash;
- redaction breach accepted;
- malformed security IR accepted by the parser;
- expected attack mutation does not trigger its target claim.

The current report has `overall_status: passed` and `security_decision: TESTNET_FUZZ_CAMPAIGNS_PASSED_BOUNDED_GENERATED_COVERAGE`.

## Counterexamples

Every expected attack mutation writes a counterexample JSON file under `security_ir_artifacts/corpora/xaman-app/testnet/fuzz/counterexamples/` plus `manifest.json`. These artifacts retain categorical mutation markers, payload digests, target claims, and triggered claims only. They do not record raw payload JSON, credentials, account material, transaction blobs, signatures, seeds, or addresses.

## Validation

Run:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_testnet_fuzzing.py -q
test -f security_ir_artifacts/corpora/xaman-app/testnet/fuzz/fuzz-report.json
test -d security_ir_artifacts/corpora/xaman-app/testnet/fuzz/counterexamples
```
