# Xaman Testnet SMT Worker

Task: `PORTAL-CXTP-132`

The Testnet SMT worker is locked by:

- `security_ir_artifacts/corpora/xaman-app/testnet/proof-worker-lock.json`
- `security_ir_artifacts/corpora/xaman-app/testnet/cvc5-runner-report.json`
- `security_ir_artifacts/corpora/xaman-app/testnet/smtlib/`

The worker is bound to exactly one Testnet SecurityModelIR CID:

`sha256:4edaad61130b6851220b6a75fa86a52b17e1baf33a8631def2879b0464366b43`

## Contract

The lock admits only the `PORTAL-CXTP-131` Testnet model at `security_ir_artifacts/corpora/xaman-app/testnet/security-model-ir.json`. The claim scope is every blocking or high Testnet claim in that model. Each claim is compiled to deterministic SMT-LIB2 using `QF_LIA` and the `xaman_blocking_acceptance_satisfiability` query contract.

The selected proof lanes are:

- Z3 through the Python SMT-LIB parser;
- CVC5 through the CLI runner.

`UNKNOWN`, timeout, unavailable solver, parser error, unsupported theory, generic solver error, or a Z3/CVC5 disagreement is a Testnet assurance blocker. The worker records these as `solver_blocked` and does not downgrade them.

## Current Result

The checked-in `cvc5-runner-report.json` covers all 12 locked Testnet claims. Z3 and CVC5 agree on the current SMT-LIB corpus with no timeout, no unsupported theory, and no Z3/CVC5 disagreement.

The report still has:

- `overall_status: blocked_by_unresolved_assumptions`
- `security_decision: BLOCK_TESTNET_ASSURANCE_UNRESOLVED_ASSUMPTIONS`

This is expected for the reviewed Testnet model because the claims retain explicit blocking assumptions and `NOT_MODELED` boundaries for production runtime equivalence, native vault/signing behavior, raw payload and transaction material, XRPL broadcast/finality, replay, expiry, cancellation, and refusal paths.

## Regeneration

Run:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/lock_xaman_testnet_smt_worker.py
```

Validate:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_testnet_smt_worker.py -q
test -f security_ir_artifacts/corpora/xaman-app/testnet/proof-worker-lock.json
test -f security_ir_artifacts/corpora/xaman-app/testnet/cvc5-runner-report.json
```
