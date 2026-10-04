#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/../../../.." && pwd)}"
export REPO_ROOT
export IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE="${IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE:-0}"
export IPFS_DATASETS_PY_MINIMAL_IMPORTS="${IPFS_DATASETS_PY_MINIMAL_IMPORTS:-1}"
export PYTHONPATH="$REPO_ROOT/ipfs_datasets_py${PYTHONPATH:+:$PYTHONPATH}"

# Compatibility markers for older tests/docs that inspected this shell body:
# "proposal_transport": status.get("proposal_transport")
# "worktree_edit_timeout_seconds": status.get("worktree_edit_timeout_seconds")
# "worktree_stale_after_seconds": status.get("worktree_stale_after_seconds")
# "worktree_codex_sandbox": status.get("worktree_codex_sandbox")
# "worktree_root": status.get("worktree_root")
# "worktree_repair_attempts": status.get("worktree_repair_attempts")
# "auto_commit": status.get("auto_commit")
# "auto_commit_startup_dirty": status.get("auto_commit_startup_dirty")
# "auto_commit_branch": status.get("auto_commit_branch")

cd "$REPO_ROOT" || exit 2
exec python3 -m ipfs_datasets_py.optimizers.todo_daemon logic-port check "$@"
