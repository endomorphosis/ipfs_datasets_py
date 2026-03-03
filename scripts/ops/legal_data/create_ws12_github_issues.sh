#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT_DIR"

# Ensure user-space GitHub CLI install is discoverable.
export PATH="$HOME/.local/bin:$PATH"

if [[ -z "${PYTHON_BIN:-}" ]]; then
  if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
  elif [[ -x "$ROOT_DIR/../.venv/bin/python" ]]; then
    PYTHON_BIN="$ROOT_DIR/../.venv/bin/python"
  elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
  else
    echo "[error] No Python interpreter found. Set PYTHON_BIN explicitly." >&2
    exit 127
  fi
fi

REPO="${REPO:-endomorphosis/ipfs_datasets_py}"

# Default mode is dry-run. Pass --create to open issues.
PYTHONPATH="$ROOT_DIR/src:$ROOT_DIR" \
  "$PYTHON_BIN" "$ROOT_DIR/scripts/ops/legal_data/create_ws12_github_issues.py" \
  --repo "$REPO" \
  "$@"
