#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/../../../.." && pwd)}"
export REPO_ROOT
export IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE="${IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE:-0}"
export PYTHONPATH="$REPO_ROOT/ipfs_datasets_py${PYTHONPATH:+:$PYTHONPATH}"

# Compatibility marker for supervisor maintenance validation:
# pid_has_non_logic_port_daemon_ancestor

cd "$REPO_ROOT" || exit 2
exec python3 -m ipfs_datasets_py.optimizers.todo_daemon.logic_port stop "$@"
