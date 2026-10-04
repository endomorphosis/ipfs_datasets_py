#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "${ROOT_DIR}"

export PYTHONPATH="${ROOT_DIR}"
export IPFS_DATASETS_PY_MINIMAL_IMPORTS="${IPFS_DATASETS_PY_MINIMAL_IMPORTS:-1}"
export IPFS_DATASETS_AUTO_INSTALL="${IPFS_DATASETS_AUTO_INSTALL:-0}"
export IPFS_KIT_AUTO_INSTALL_DEPS="${IPFS_KIT_AUTO_INSTALL_DEPS:-0}"

python -m pytest tests/logic/security_models/crypto_exchange -v --tb=short
python scripts/ops/security_verification/run_security_ir_proof_suite.py \
  --example \
  --fail-on disproof \
  --require-real-ergoai \
  --forbid-simulated-zkp \
  --out "${1:-security_ir_proof_report.json}"
python scripts/ops/security_verification/run_security_ir_disproof_suite.py \
  --example \
  --fuzz-rounds 3 \
  --out "${2:-security_ir_disproof_report.json}"
