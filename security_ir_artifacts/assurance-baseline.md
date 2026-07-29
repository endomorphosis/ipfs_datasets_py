# Crypto Exchange Assurance Baseline

Generated: 2026-07-08T01:46:06Z

## Environment

- Python: `/home/barberb/miniforge3/bin/python`
- Z3 Python bindings: `4.16.0.0`
- Model input: `built-in example`
- Proof report: `security_ir_artifacts/proof-baseline.json`
- Disproof report: `security_ir_artifacts/disproof-baseline.json`

## Proof Coverage

- Total claims: `8`
- Proved: `8`
- Disproved: `0`
- Unknown: `0`
- Not modeled: `0`
- Blocking claims: `3`
- Blocking modeled: `3`
- Blocking proved: `3`

| Claim | Status | Risk | Assumptions |
| --- | --- | --- | --- |
| `no_unauthorized_withdrawal` | `PROVED` | `blocking` | `A3,A4,A5,A8` |
| `no_over_reserved_internal_account` | `PROVED` | `blocking` | `A4,A5` |
| `global_asset_conservation` | `PROVED` | `blocking` | `A4,A10` |
| `no_deposit_before_finality` | `PROVED` | `high` | `A6,A9` |
| `no_signing_request_after_wallet_freeze` | `PROVED` | `high` | `A3,A8` |
| `capability_delegation_no_authority_increase` | `PROVED` | `high` | `A1,A7` |
| `revoked_capability_no_future_authorization` | `PROVED` | `high` | `A10` |
| `audit_event_exists_for_critical_transition` | `PROVED` | `medium` | `A10` |

## Release Gate

- Release ready: `True`
- Blocking accepted: `3/3`
- High accepted: `4/4`
- Medium accepted: `1/1`
- Failures: `0`
- Attention items: `0`

## Assumption Registry

- Assumption evidence ready: `True`
- Required assumptions: `9`
- Owned: `9/9`
- Evidenced: `9/9`
- Current: `9/9`
- Stale: `0`
- Failures: `0`

## Disproof Coverage

- Seed: `7`
- Scenario count: `24`
- Scenario failures: `0`
- Total disproved claims: `27`

## Soundness Boundary

This baseline covers the implemented bounded Z3/IR verifier for the selected model input. It does not prove a production exchange secure unless the input facts are complete, reviewed, and tied to the deployed code and environment.

Treat any future `DISPROVED`, blocking `UNKNOWN`, blocking `NOT_MODELED`, missing Z3, simulated proof dependency, stale model CID, stale assumption evidence, or unreviewed blocking evidence as non-secure.
