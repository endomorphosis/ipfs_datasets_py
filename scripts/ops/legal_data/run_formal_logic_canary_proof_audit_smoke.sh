#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$ROOT_DIR"

TMP_DIR="${TMP_DIR:-/tmp/formal_logic_canary_proof_audit_smoke}"
mkdir -p "$TMP_DIR"

CANARY_DECISION_PATH="${CANARY_DECISION_PATH:-$TMP_DIR/canary_mode_decision.smoke.json}"
PROOF_STORE_PATH="${PROOF_STORE_PATH:-$TMP_DIR/proofs.smoke.json}"
PROOF_CERT_AUDIT_PATH="${PROOF_CERT_AUDIT_PATH:-$TMP_DIR/proof_certificate_audit.smoke.json}"

cat > "$CANARY_DECISION_PATH" <<'JSON'
{
  "route": "hybrid",
  "hybrid_enabled": true,
  "reason": "smoke",
  "proof_audit_required": true
}
JSON

cat > "$PROOF_STORE_PATH" <<'JSON'
{
  "proofs": {
    "proof:smoke:canary": {
      "proof_id": "proof:smoke:canary",
      "query": {"type": "compliance"},
      "root_conclusion": "ok",
      "steps": [],
      "status": "proved",
      "schema_version": "1.0",
      "proof_hash": "smokehash",
      "certificates": [
        {
          "certificate_id": "cert:smoke:canary",
          "backend": "mock-smt",
          "format": "smt2-proof",
          "theorem": "ok",
          "assumptions": [],
          "payload": {},
          "normalized_hash": "smokehashnorm"
        }
      ],
      "certificate_trace_map": {
        "cert:smoke:canary": [{"kind": "norm", "id": "nrm:smoke"}]
      }
    }
  }
}
JSON

ROUTE=$(PYTHONPATH=src:ipfs_datasets_py .venv/bin/python - <<'PY' "$CANARY_DECISION_PATH"
import json
import sys
from pathlib import Path
p = Path(sys.argv[1])
print((json.loads(p.read_text(encoding='utf-8'))).get('route', 'baseline'))
PY
)

PROOF_AUDIT_REQUIRED=$(PYTHONPATH=src:ipfs_datasets_py .venv/bin/python - <<'PY' "$CANARY_DECISION_PATH"
import json
import sys
from pathlib import Path
p = Path(sys.argv[1])
print('1' if bool((json.loads(p.read_text(encoding='utf-8'))).get('proof_audit_required', False)) else '0')
PY
)

if [[ "$ROUTE" != "hybrid" || "$PROOF_AUDIT_REQUIRED" != "1" ]]; then
  echo "[smoke] Unexpected canary decision contract. route=$ROUTE proof_audit_required=$PROOF_AUDIT_REQUIRED"
  exit 1
fi

echo "[smoke] Contract satisfied; exporting proof certificate audit artifact..."
PROOF_STORE_PATH="$PROOF_STORE_PATH" \
  PROOF_CERT_AUDIT_PATH="$PROOF_CERT_AUDIT_PATH" \
  bash ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_proof_certificate_audit.sh

PYTHONPATH=src:ipfs_datasets_py .venv/bin/python - <<'PY' "$PROOF_CERT_AUDIT_PATH"
import json
import sys
from pathlib import Path
p = Path(sys.argv[1])
d = json.loads(p.read_text(encoding='utf-8'))
assert d['summary']['proof_count'] == 1
assert d['summary']['certificate_count'] == 1
assert d['summary']['missing_trace_map_count'] == 0
print('[smoke] canary proof-audit hook validation passed')
print(f'[smoke] artifact={p}')
PY
