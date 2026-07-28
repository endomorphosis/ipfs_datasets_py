#!/usr/bin/env bash
# Launch multi-lane implementation supervisor for the unified LIG board.
# Sole active logic-IR board: logic-intent-legal-gate-v1 (IRF absorbed; do not co-launch ir-family-v1).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${REPO_ROOT:-$SCRIPT_DIR/../../..}" && pwd)"
ACCELERATE_ROOT="$(cd "${ACCELERATE_ROOT:-$REPO_ROOT/../ipfs_accelerate_py}" && pwd)"
TODO_PATH="${TODO_PATH:-docs/architecture/logic_intent_legal_gate.todo.md}"
TASK_PREFIX="${TASK_PREFIX:-LIG-}"
SHARD_COUNT="${SHARD_COUNT:-4}"
STATE_ROOT="${STATE_ROOT:-data/agent_supervisor/logic_intent_legal_gate}"
# Land implementations on the program feature branch, not main, unless overridden.
MERGE_TARGET_BRANCH="${MERGE_TARGET_BRANCH:-feature/logic-intent-legal-gate}"
IMPLEMENT="${IMPLEMENT:-1}"
DRY_RUN=0
FOREGROUND=0
ONCE=0

usage() {
  cat <<'EOF'
Usage: launch_multi_lane.sh [--dry-run] [--foreground] [--once] [--help]

  --dry-run      One pass, no implementation (--once --no-implement)
  --foreground   Run a single SHARD in the foreground (requires SHARD=0..N-1)
  --once         One backlog pass then exit (still implements if IMPLEMENT=1)
  --help         This help

Env:
  SHARD_COUNT   default 4
  SHARD         required with --foreground
  REPO_ROOT     datasets repo (default: resolved from script)
  ACCELERATE_ROOT  path to ipfs_accelerate_py (default: ../ipfs_accelerate_py)
  IMPLEMENT     1 (default) or 0
  TODO_PATH     relative todo board path
  STATE_ROOT    relative state root under REPO_ROOT
  MERGE_TARGET_BRANCH  default feature/logic-intent-legal-gate
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; IMPLEMENT=0; ONCE=1; shift ;;
    --foreground) FOREGROUND=1; shift ;;
    --once) ONCE=1; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 2 ;;
  esac
done

cd "$REPO_ROOT"

if [[ ! -f "$TODO_PATH" ]]; then
  echo "Missing todo board: $REPO_ROOT/$TODO_PATH" >&2
  exit 1
fi

if [[ ! -d "$ACCELERATE_ROOT/ipfs_accelerate_py" ]]; then
  echo "ACCELERATE_ROOT does not look like ipfs_accelerate_py: $ACCELERATE_ROOT" >&2
  exit 1
fi

export PYTHONPATH="${ACCELERATE_ROOT}:${REPO_ROOT}${PYTHONPATH:+:$PYTHONPATH}"

# Source shared implementation defaults if present (provider/model); never required.
if [[ -f "${HOME}/.local/share/ipfs_accelerate_py/agent-supervisor/implementation.env" ]]; then
  # shellcheck disable=SC1091
  source "${HOME}/.local/share/ipfs_accelerate_py/agent-supervisor/implementation.env" || true
elif [[ -f "${HOME}/.local/share/ipfs_accelerate_py/agent-supervisor/ir-family-v1/implementation.env" ]]; then
  # shellcheck disable=SC1091
  source "${HOME}/.local/share/ipfs_accelerate_py/agent-supervisor/ir-family-v1/implementation.env" || true
fi

export IPFS_ACCELERATE_AGENT_IMPLEMENTATION_PROVIDER="${IPFS_ACCELERATE_AGENT_IMPLEMENTATION_PROVIDER:-grok}"
export IPFS_ACCELERATE_AGENT_GROK_MODEL="${IPFS_ACCELERATE_AGENT_GROK_MODEL:-grok-4.5}"
export IPFS_ACCELERATE_AGENT_GROK_PERMISSION_MODE="${IPFS_ACCELERATE_AGENT_GROK_PERMISSION_MODE:-bypassPermissions}"
export IPFS_ACCELERATE_AGENT_GROK_BIN="${IPFS_ACCELERATE_AGENT_GROK_BIN:-${HOME}/.local/bin/grok}"
export GROK_CLI_MODEL="${GROK_CLI_MODEL:-grok-4.5}"

PROTECTED=(
  --implementation-protected-path docs/architecture/LOGIC_INTENT_LEGAL_GATE_PLAN.md
  --implementation-protected-path docs/architecture/INTENT_IR_ATTESTED_AUTHORIZATION_PLAN.md
  --implementation-protected-path docs/architecture/logic_intent_legal_gate.objectives.md
  --implementation-protected-path docs/architecture/logic_intent_legal_gate.todo.md
)

run_shard() {
  local shard="$1"
  local state_dir="${STATE_ROOT}/shards/${shard}/state"
  local worktree_root="${STATE_ROOT}/shards/${shard}/worktrees"
  local log_dir="${STATE_ROOT}/shards/${shard}/logs"
  mkdir -p "$state_dir" "$worktree_root" "$log_dir"

  local -a cmd=(
    python -m ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_supervisor
    --task-prefix "$TASK_PREFIX"
    --task-shard-count "$SHARD_COUNT"
    --task-shard-index "$shard"
    --todo-path "$TODO_PATH"
    --state-dir "$state_dir"
    --worktree-root "$worktree_root"
    --state-prefix "lig_shard_${shard}"
    --merge-target-branch "$MERGE_TARGET_BRANCH"
    "${PROTECTED[@]}"
  )

  if [[ "$IMPLEMENT" == "1" && "$DRY_RUN" == "0" ]]; then
    cmd+=(--implement)
  else
    cmd+=(--no-implement)
  fi

  if [[ "$ONCE" == "1" || "$DRY_RUN" == "1" ]]; then
    cmd+=(--once)
  fi

  echo "[lig] shard=${shard}/${SHARD_COUNT} implement=${IMPLEMENT} dry_run=${DRY_RUN} state=${state_dir}"
  if [[ "$FOREGROUND" == "1" ]]; then
    exec "${cmd[@]}"
  fi
  nohup "${cmd[@]}" >"${log_dir}/supervisor.log" 2>&1 &
  local pid=$!
  echo "$pid" >"${STATE_ROOT}/shards/${shard}/supervisor.pid"
  echo "[lig] shard=${shard} pid=${pid} log=${log_dir}/supervisor.log"
}

echo "[lig] REPO_ROOT=$REPO_ROOT"
echo "[lig] ACCELERATE_ROOT=$ACCELERATE_ROOT"
echo "[lig] board=$TODO_PATH prefix=$TASK_PREFIX shards=$SHARD_COUNT merge_target=$MERGE_TARGET_BRANCH"

# Soft warning if IRF supervisors appear live (contention risk).
# Match only the IRF todo path / state namespace — avoid false positives from other boards.
if pgrep -af 'ir_family_refactor_intent_ir\.todo|agent-supervisor/ir-family-v1' 2>/dev/null \
  | grep -E 'implementation_supervisor|implementation_daemon' >/dev/null 2>&1; then
  echo "[lig] WARNING: live ir-family-v1 implementation process detected; stop it to avoid logic/** contention" >&2
fi

if [[ "$FOREGROUND" == "1" ]]; then
  if [[ -z "${SHARD:-}" ]]; then
    echo "SHARD must be set with --foreground" >&2
    exit 2
  fi
  run_shard "$SHARD"
fi

for ((s = 0; s < SHARD_COUNT; s++)); do
  run_shard "$s"
done

echo "[lig] launched ${SHARD_COUNT} shard(s). Tail logs under ${STATE_ROOT}/shards/*/logs/"
echo "[lig] stop: for p in ${STATE_ROOT}/shards/*/supervisor.pid; do kill \$(cat \$p) 2>/dev/null || true; done"
