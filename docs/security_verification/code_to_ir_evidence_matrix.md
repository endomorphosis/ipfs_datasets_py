# Code-to-IR Evidence Coverage Matrix

Generated: `2026-07-08T05:39:25Z`

- Model: `minimal-btc-exchange`
- Model CID: `bafkreics22k4sezd6maidggz5ohuxu4kkyvazwl62wetygtpe5jeiswbz4`
- Release ready for evidence coverage: `True`
- Failures: `0`

## Domain Coverage

| Domain | Modeled | Records | Claims | Critical Claims | Evidence Refs | Reviewed Refs | Reviewed Path |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `wallets` | `True` | `3` | `1` | `1` | `1` | `1` | `True` |
| `withdrawals` | `True` | `10` | `1` | `1` | `10` | `10` | `True` |
| `deposits` | `True` | `4` | `1` | `1` | `4` | `4` | `True` |
| `ledger` | `True` | `6` | `2` | `2` | `4` | `4` | `True` |
| `capabilities` | `True` | `5` | `2` | `2` | `5` | `5` | `True` |
| `hsm` | `True` | `5` | `1` | `1` | `3` | `3` | `True` |
| `audit` | `True` | `3` | `1` | `0` | `3` | `3` | `True` |
| `assumptions` | `True` | `10` | `0` | `0` | `10` | `10` | `True` |
| `evidence_refs` | `True` | `38` | `0` | `0` | `38` | `38` | `True` |

## Claim Evidence

| Claim | Domain | Risk | Status | Assumptions | Evidence Refs | Reviewed Source | Reviewed Runtime | Reviewed Policy |
| --- | --- | --- | --- | --- | ---: | --- | --- | --- |
| `no_unauthorized_withdrawal` | `withdrawals` | `blocking` | `PROVED` | `A3, A4, A5, A8` | `7` | `True` | `True` | `True` |
| `no_over_reserved_internal_account` | `ledger` | `blocking` | `PROVED` | `A4, A5` | `2` | `True` | `True` | `True` |
| `global_asset_conservation` | `ledger` | `blocking` | `PROVED` | `A4, A10` | `2` | `True` | `True` | `True` |
| `no_deposit_before_finality` | `deposits` | `high` | `PROVED` | `A6, A9` | `4` | `True` | `True` | `True` |
| `no_signing_request_after_wallet_freeze` | `hsm` | `high` | `PROVED` | `A3, A8` | `3` | `True` | `True` | `True` |
| `capability_delegation_no_authority_increase` | `capabilities` | `high` | `PROVED` | `A1, A7` | `2` | `True` | `True` | `True` |
| `revoked_capability_no_future_authorization` | `capabilities` | `high` | `PROVED` | `A10` | `4` | `True` | `True` | `True` |
| `audit_event_exists_for_critical_transition` | `audit` | `medium` | `PROVED` | `A10` | `14` | `True` | `True` | `True` |

## Assumptions

- Assumption evidence ready: `True`
- Required assumptions: `9`
- Owned: `9`
- Evidenced: `9`
- Current: `9`

## Evidence References

- Total refs: `38`
- Reviewed refs: `38`
- By kind: `{"manual_review": 10, "test_fixture": 28}`
- By review status: `{"trusted_fixture": 38}`

## Fail-Closed Rule

Any blocking or high-risk claim without at least one `human_reviewed` or `trusted_fixture` source, runtime, or policy evidence path fails this audit.
