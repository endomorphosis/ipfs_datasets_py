# Crypto Exchange Taskboard Preflight CI

Task: `PORTAL-CXTP-087`

The preflight script is `scripts/ops/security_verification/preflight_crypto_exchange_taskboard.py`.

## What It Checks

The preflight fails closed when:

- the taskboard has no parseable `PORTAL-CXTP-*` tasks;
- a task status is invalid;
- a completed task has no completion evidence;
- a completed task declares an output artifact that is missing;
- supervisor state task counts or statuses contradict the taskboard;
- production blocker tasks `PORTAL-CXTP-077` through `PORTAL-CXTP-084` are incomplete while a production report claims release acceptance.

Blocked production evidence is allowed only when the report keeps `production_release_blocked: true` or uses a `BLOCK*` security decision.

## CI Entry Point

`.github/workflows/crypto-exchange-security-verification.yml` runs:

```bash
PYTHONPATH=. python scripts/ops/security_verification/preflight_crypto_exchange_taskboard.py \
  --taskboard docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md \
  --state data/crypto_exchange_theorem_prover/state/cxtp_task_state.json \
  --out security_ir_artifacts/recovery/taskboard-preflight-report.json

PYTHONPATH=. python -m pytest tests/logic/security_models/crypto_exchange/test_taskboard_preflight.py -q
```

## Current Expected Behavior

If recovered source or evidence artifacts disappear, the script must fail. That is intentional: the supervisor should not continue proof or production-release work from a contradictory board.

The generated report records `BLOCK_TASKBOARD_PREFLIGHT` when blockers are found and `TASKBOARD_PREFLIGHT_READY` only when no blockers remain.
