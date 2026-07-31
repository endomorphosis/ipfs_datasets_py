#!/usr/bin/env bash
# Thin wrapper: LIG multi-lane + merge-train operator status.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${REPO_ROOT:-$SCRIPT_DIR/../../..}" && pwd)"
ACCELERATE_ROOT="$(cd "${ACCELERATE_ROOT:-$REPO_ROOT/../ipfs_accelerate_py}" && pwd)"

export PYTHONPATH="${ACCELERATE_ROOT}:${REPO_ROOT}${PYTHONPATH:+:$PYTHONPATH}"

exec python "$SCRIPT_DIR/status.py" --repo-root "$REPO_ROOT" "$@"
