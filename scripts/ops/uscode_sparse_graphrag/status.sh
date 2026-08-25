#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
ACCELERATOR_ROOT="${IPFS_ACCELERATE_ROOT:-$(cd "$REPO_ROOT/../ipfs_accelerate_py" 2>/dev/null && pwd)}"
export PYTHONPATH="$ACCELERATOR_ROOT${PYTHONPATH:+:$PYTHONPATH}"

exec python3 -P "$REPO_ROOT/scripts/ops/uscode_sparse_graphrag/status.py" \
  --repo-root "$REPO_ROOT" \
  --config config/agent_supervisor_uscode_sparse_graphrag_scheduler.json \
  "$@"
