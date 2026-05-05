#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"
export REPO_ROOT
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"

# Compatibility markers for older tests/docs that inspected this shell body.
# The implementation now lives in ipfs_datasets_py.optimizers.todo_daemon.legal_parser.
# legal_parser_daemon_ensure.status.json
# legal_parser_daemon_supervisor_wrapper.pid
# check_legal_parser_optimizer_daemon.sh
# run_legal_parser_optimizer_daemon.sh
# ENSURE_LAUNCH_MODE="${ENSURE_LAUNCH_MODE:-nohup_loop}"
# while true; do MODEL_NAME=
# legal-parser supervisor exited with code
# cleanup_stale_supervisor_artifacts()
# pid_is_legal_parser_supervisor()
# pid_is_legal_parser_wrapper()
# wrapper_alive()
# pid_is_legal_parser_wrapper "$pid"
# wrapped_existing_supervisor
# wrapper_recovered_supervisor
# SUPERVISOR_LOCK_PATH
# tmux new-session
# wait_for_supervisor
# "schema": "ipfs_datasets_py.legal_parser_daemon.ensure"
# "supervisor_pid_alive"
# "wrapper_pid_alive"

cd "$REPO_ROOT" || exit 2
exec python3 -m ipfs_datasets_py.optimizers.todo_daemon legal-parser ensure "$@"
