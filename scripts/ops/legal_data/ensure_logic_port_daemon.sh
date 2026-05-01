#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/../../../.." && pwd)}"
DAEMON_DIR="${DAEMON_DIR:-ipfs_datasets_py/.daemon}"
ENSURE_STATUS_PATH="${ENSURE_STATUS_PATH:-$DAEMON_DIR/logic-port-daemon-ensure.status.json}"
CHECK_LOG_PATH="${CHECK_LOG_PATH:-$DAEMON_DIR/logic-port-daemon-ensure-check.json}"
SUPERVISOR_OUT_PATH="${SUPERVISOR_OUT_PATH:-$DAEMON_DIR/logic-port-daemon-supervisor.out}"

mkdir -p "$REPO_ROOT/$DAEMON_DIR"
cd "$REPO_ROOT" || exit 2

checked_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

if bash ipfs_datasets_py/scripts/ops/legal_data/check_logic_port_daemon.sh > "$CHECK_LOG_PATH" 2>&1; then
  python3 - "$ENSURE_STATUS_PATH" "$checked_at" "$CHECK_LOG_PATH" <<'PY'
import json
import sys

status_path, checked_at, check_path = sys.argv[1:4]
try:
    with open(check_path, "r", encoding="utf-8") as handle:
        check = json.load(handle)
except Exception:
    check = {}
payload = {
    "schema": "ipfs_datasets_py.logic_port_daemon.ensure",
    "status": "already_running",
    "checked_at": checked_at,
    "started_supervisor": False,
    "check": check,
}
with open(status_path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY
  cat "$CHECK_LOG_PATH"
  exit 0
fi

setsid bash ipfs_datasets_py/scripts/ops/legal_data/run_logic_port_daemon.sh \
  </dev/null > "$SUPERVISOR_OUT_PATH" 2>&1 &
started_pid=$!
sleep 3

if bash ipfs_datasets_py/scripts/ops/legal_data/check_logic_port_daemon.sh > "$CHECK_LOG_PATH" 2>&1; then
  ensure_status="started"
  ensure_exit=0
else
  ensure_status="start_attempted_but_unhealthy"
  ensure_exit=1
fi

python3 - "$ENSURE_STATUS_PATH" "$checked_at" "$CHECK_LOG_PATH" "$ensure_status" "$started_pid" <<'PY'
import json
import sys

status_path, checked_at, check_path, ensure_status, started_pid = sys.argv[1:6]
try:
    with open(check_path, "r", encoding="utf-8") as handle:
        check = json.load(handle)
except Exception:
    check = {}
payload = {
    "schema": "ipfs_datasets_py.logic_port_daemon.ensure",
    "status": ensure_status,
    "checked_at": checked_at,
    "started_supervisor": True,
    "started_pid": int(started_pid),
    "check": check,
}
with open(status_path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY

cat "$CHECK_LOG_PATH"
exit "$ensure_exit"
