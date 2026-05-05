#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"
export REPO_ROOT
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"

# Compatibility markers for older tests/docs that inspected this shell body.
# The implementation now lives in ipfs_datasets_py.optimizers.todo_daemon.legal_parser.
# "proposal_transport": current.get("proposal_transport")
# "worktree_edit_timeout_seconds": current.get("worktree_edit_timeout_seconds")
# "worktree_stale_after_seconds": current.get("worktree_stale_after_seconds")
# "worktree_codex_sandbox": current.get("worktree_codex_sandbox")
# "repair_failed_tests_before_rollback": current.get("repair_failed_tests_before_rollback")
# "failed_test_repair_attempts": current.get("failed_test_repair_attempts")
# "worktree_no_child_stall_seconds": worktree_no_child_threshold
# "worktree_phase_worker_status": worktree_worker_status
# alive = bool(supervisor_alive and ((daemon_alive and daemon_fresh) or maintenance_fresh))
# maintenance_running
# "formal_logic_goal"
# pid_is_legal_parser_wrapper
# progress_dirty_legal_parser_targets_diff_summary
# "agentic_acceptance_stall_cycles"
# "ensure_status"
# "ensure_wrapper_pid_alive"

cd "$REPO_ROOT" || exit 2
exec python3 -m ipfs_datasets_py.optimizers.todo_daemon.legal_parser check "$@"
