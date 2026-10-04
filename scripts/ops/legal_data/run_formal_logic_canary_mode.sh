#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$ROOT_DIR"

RISK_LEVEL="${RISK_LEVEL:-low}"
REQUIRE_SHADOW_READY="${REQUIRE_SHADOW_READY:-1}"
RUN_SHADOW_FIRST="${RUN_SHADOW_FIRST:-1}"
LIMIT_SEGMENTS="${LIMIT_SEGMENTS:-50}"
RUN_PROOF_AUDIT_IF_REQUIRED="${RUN_PROOF_AUDIT_IF_REQUIRED:-1}"
PROOF_STORE_PATH="${PROOF_STORE_PATH:-artifacts/formal_logic_tmp_verify/federal/proofs.json}"
PROOF_CERT_AUDIT_PATH="${PROOF_CERT_AUDIT_PATH:-artifacts/formal_logic_tmp_verify/federal/proof_certificate_audit.json}"

SHADOW_AUDIT_PATH="${SHADOW_AUDIT_PATH:-artifacts/formal_logic_tmp_verify/federal/shadow_mode_audit.json}"
CANARY_DECISION_PATH="${CANARY_DECISION_PATH:-artifacts/formal_logic_tmp_verify/federal/canary_mode_decision.json}"

if [[ "$RUN_SHADOW_FIRST" == "1" ]]; then
  echo "[canary 1/3] Refreshing shadow audit..."
  LIMIT_SEGMENTS="$LIMIT_SEGMENTS" \
    bash ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_shadow_mode.sh
fi

echo "[canary 2/3] Selecting canary route from audit..."
CANARY_ARGS=(
  --audit "$SHADOW_AUDIT_PATH"
  --risk-level "$RISK_LEVEL"
  --output "$CANARY_DECISION_PATH"
)
if [[ "$REQUIRE_SHADOW_READY" != "1" ]]; then
  CANARY_ARGS+=(--allow-without-shadow-ready)
fi
PYTHONPATH=src:ipfs_datasets_py .venv/bin/python \
  ipfs_datasets_py/scripts/ops/legal_data/select_formal_logic_canary_mode.py \
  "${CANARY_ARGS[@]}"

ROUTE=$(PYTHONPATH=src:ipfs_datasets_py .venv/bin/python - <<'PY' "$CANARY_DECISION_PATH"
import json
from pathlib import Path
p=Path(__import__('sys').argv[1])
print((json.loads(p.read_text(encoding='utf-8'))).get('route','baseline'))
PY
)

PROOF_AUDIT_REQUIRED=$(PYTHONPATH=src:ipfs_datasets_py .venv/bin/python - <<'PY' "$CANARY_DECISION_PATH"
import json
from pathlib import Path
p=Path(__import__('sys').argv[1])
v=(json.loads(p.read_text(encoding='utf-8'))).get('proof_audit_required', False)
print('1' if bool(v) else '0')
PY
)

echo "[canary 3/3] Executing selected route: $ROUTE"
if [[ "$ROUTE" == "hybrid" ]]; then
  LIMIT_SEGMENTS="$LIMIT_SEGMENTS" \
    bash ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_regression_check_hybrid.sh
else
  LIMIT_SEGMENTS="$LIMIT_SEGMENTS" \
    bash ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_regression_check_baseline.sh
fi

if [[ "$ROUTE" == "hybrid" && "$PROOF_AUDIT_REQUIRED" == "1" && "$RUN_PROOF_AUDIT_IF_REQUIRED" == "1" ]]; then
  if [[ -f "$PROOF_STORE_PATH" ]]; then
    echo "[canary post] proof_audit_required=true; exporting proof certificate audit artifact..."
    PROOF_STORE_PATH="$PROOF_STORE_PATH" \
      PROOF_CERT_AUDIT_PATH="$PROOF_CERT_AUDIT_PATH" \
      bash ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_proof_certificate_audit.sh
  else
    echo "[warn] proof_audit_required=true but proof store not found: $PROOF_STORE_PATH"
    echo "[warn] Skipping proof certificate audit export."
  fi
fi

echo "[canary] Complete. Decision: $CANARY_DECISION_PATH"
