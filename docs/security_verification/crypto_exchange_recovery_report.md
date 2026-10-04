# Crypto Exchange Source Recovery Report

Status: active
Task: `PORTAL-CXTP-056`

## Purpose

The theorem-prover workflow depends on source files under
`ipfs_datasets_py/logic/security_models/crypto_exchange`. If the checkout only
contains bytecode, missing package files, or missing tests, proof results are
not admissible because the model cannot be tied to reviewed source evidence.

`scripts/ops/security_verification/audit_crypto_exchange_source_tree.py`
records the required source files, required tests, discovered Python sources,
bytecode-only risk, and a fail-closed security decision.

## Current Evidence

The current audit artifact is:

`security_ir_artifacts/recovery/crypto-exchange-source-audit.json`

A passing audit has:

- `overall_status: "pass"`
- `proof_acceptance_blocked: false`
- `security_decision: "CRYPTO_EXCHANGE_SOURCE_TREE_PRESENT"`
- no blockers

## Validation

Run from the repository root:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest \
  tests/logic/security_models/crypto_exchange/test_crypto_exchange_source_tree_recovery.py -q

PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/audit_crypto_exchange_source_tree.py \
  --out security_ir_artifacts/recovery/crypto-exchange-source-audit.json
```

The audit blocks proof acceptance when the package root is absent, required
source files are missing, required tests are missing, or the tree appears to be
bytecode-only.
