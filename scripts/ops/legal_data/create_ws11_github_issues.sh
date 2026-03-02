#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
REPO="${REPO:-endomorphosis/ipfs_datasets_py}"

# Default mode is dry-run. Pass --create to open issues.
PYTHONPATH="$ROOT_DIR/src:$ROOT_DIR/ipfs_datasets_py" \
  "$PYTHON_BIN" "$ROOT_DIR/ipfs_datasets_py/scripts/ops/legal_data/create_ws11_github_issues.py" \
  --repo "$REPO" \
  "$@"
