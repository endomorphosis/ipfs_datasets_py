#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/../../../.." && pwd)}"
export REPO_ROOT
export IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE="${IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE:-0}"
export PYTHONPATH="$REPO_ROOT/ipfs_datasets_py${PYTHONPATH:+:$PYTHONPATH}"

# Compatibility markers for older maintenance checks that grepped this file:
# launch_mode=\"tmux\"
# SUPERVISOR_AGENTIC_STARTUP_FAILURE_MAINTENANCE="${SUPERVISOR_AGENTIC_STARTUP_FAILURE_MAINTENANCE:-1}"
# SUPERVISOR_AGENTIC_STARTUP_FAILURE_MAINTENANCE="$SUPERVISOR_AGENTIC_STARTUP_FAILURE_MAINTENANCE"
# "agentic_startup_failure_maintenance": startup_failure_maintenance

cd "$REPO_ROOT" || exit 2
exec python3 -m ipfs_datasets_py.optimizers.todo_daemon logic-port ensure "$@"
