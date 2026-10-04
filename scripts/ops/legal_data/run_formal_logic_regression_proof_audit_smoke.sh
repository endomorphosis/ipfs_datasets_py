#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$ROOT_DIR"

TMP_DIR="${TMP_DIR:-/tmp/formal_logic_regression_proof_audit_smoke}"
mkdir -p "$TMP_DIR"

RUN_PROOF_CERT_AUDIT_AFTER_RUN="${RUN_PROOF_CERT_AUDIT_AFTER_RUN:-1}"
PROOF_STORE_PATH="${PROOF_STORE_PATH:-$TMP_DIR/proofs.smoke.json}"
PROOF_CERT_AUDIT_PATH="${PROOF_CERT_AUDIT_PATH:-$TMP_DIR/proof_certificate_audit.smoke.json}"

cat > "$PROOF_STORE_PATH" <<'JSON'
{
  "proofs": {
    "proof:smoke:regression": {
      "proof_id": "proof:smoke:regression",
      "query": {"type": "compliance"},
      "root_conclusion": "ok",
      "steps": [],
      "status": "proved",
      "schema_version": "1.0",
      "proof_hash": "smokehash",
      "certificates": [
        {
          "certificate_id": "cert:smoke:regression",
          "backend": "mock-smt",
          "format": "smt2-proof",
          "theorem": "ok",
          "assumptions": [],
          "payload": {},
          "normalized_hash": "smokehashnorm"
        }
      ],
      "certificate_trace_map": {
        "cert:smoke:regression": [{"kind": "norm", "id": "nrm:smoke"}]
      }
    }
  }
}
JSON

if [[ "$RUN_PROOF_CERT_AUDIT_AFTER_RUN" != "1" ]]; then
  echo "[smoke] Expected RUN_PROOF_CERT_AUDIT_AFTER_RUN=1 for hook-path validation"
  exit 1
fi

if [[ ! -f "$PROOF_STORE_PATH" ]]; then
  echo "[smoke] Expected proof store at $PROOF_STORE_PATH"
  exit 1
fi

echo "[smoke] Regression hook contract satisfied; exporting proof certificate audit artifact..."
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
print('[smoke] regression proof-audit hook validation passed')
print(f'[smoke] artifact={p}')
PY
