#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$ROOT_DIR"

PROOF_STORE_PATH="${PROOF_STORE_PATH:-artifacts/formal_logic_tmp_verify/federal/proofs.json}"
PROOF_CERT_AUDIT_PATH="${PROOF_CERT_AUDIT_PATH:-artifacts/formal_logic_tmp_verify/federal/proof_certificate_audit.json}"

echo "[proof-cert-audit 1/1] Exporting certificate audit artifact..."
PYTHONPATH=src:ipfs_datasets_py .venv/bin/python \
  ipfs_datasets_py/scripts/ops/legal_data/export_proof_certificates_audit.py \
  --proof-store "$PROOF_STORE_PATH" \
  --output "$PROOF_CERT_AUDIT_PATH"

echo "[proof-cert-audit] Complete. Artifact: $PROOF_CERT_AUDIT_PATH"
