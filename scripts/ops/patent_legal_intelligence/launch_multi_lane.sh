#!/usr/bin/env bash
# Launch four reviewed, file-disjoint implementation-supervisor lanes.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${PATLAW_REPO_ROOT:-$SCRIPT_DIR/../../..}" && pwd)"
ACCELERATE_ROOT="$(cd "${PATLAW_ACCELERATE_ROOT:-$REPO_ROOT/../ipfs_accelerate_py}" && pwd)"
CONFIG_PATH="${PATLAW_CONFIG_PATH:-$REPO_ROOT/config/agent_supervisor_patent_legal_intelligence.json}"
TODO_PATH="$REPO_ROOT/docs/architecture/patent_legal_intelligence.todo.md"
OBJECTIVE_PATH="$REPO_ROOT/docs/architecture/patent_legal_intelligence.objectives.md"
STATE_BASE="${XDG_STATE_HOME:-${HOME}/.local/state}"
STATE_ROOT="${PATLAW_STATE_ROOT:-$STATE_BASE/ipfs_accelerate_py/patent-legal-intelligence-v1}"
MERGE_QUEUE_DIR="${PATLAW_MERGE_QUEUE_DIR:-$STATE_ROOT/merge_queue}"
MERGE_TARGET_BRANCH="${PATLAW_MERGE_TARGET_BRANCH:-feature/patent-legal-intelligence}"
TASK_PREFIX="PATLAW-"
SHARD_COUNT=4
IMPLEMENT=1
DRY_RUN=0
ONCE=0
FOREGROUND=0

usage() {
  cat <<'EOF'
Usage: launch_multi_lane.sh [--dry-run] [--once] [--foreground] [--help]

  --dry-run      Validate and run every lane once without implementation.
  --once         Run one implementation pass and exit.
  --foreground   Run only PATLAW_SHARD (0..3) in the foreground.
  --help         Show this message.

Environment:
  PATLAW_REPO_ROOT           ipfs_datasets_py feature worktree.
  PATLAW_ACCELERATE_ROOT     compatible ipfs_accelerate_py worktree.
  PATLAW_STATE_ROOT          external runtime state root.
  PATLAW_MERGE_QUEUE_DIR     shared target-scoped merge queue.
  PATLAW_MERGE_TARGET_BRANCH default feature/patent-legal-intelligence.
  PATLAW_SHARD               required with --foreground.

Provider mode is `auto`: authenticated Grok/grok-4.5 is primary and
Codex/gpt-5.6-terra is backup only in a distinct clean attempt at the same
base. Runtime state belongs outside git. Stop only this program by sending TERM
to the PIDs listed under PATLAW_STATE_ROOT/shards/*/supervisor.pid.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; IMPLEMENT=0; ONCE=1; shift ;;
    --once) ONCE=1; shift ;;
    --foreground) FOREGROUND=1; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

cd "$REPO_ROOT"

if [[ ! -d "$ACCELERATE_ROOT/ipfs_accelerate_py/agent_supervisor" ]]; then
  echo "Incompatible accelerator worktree: $ACCELERATE_ROOT" >&2
  exit 1
fi
if [[ ! -f "$CONFIG_PATH" || ! -f "$TODO_PATH" || ! -f "$OBJECTIVE_PATH" ]]; then
  echo "Missing reviewed program input; run the board validator for details." >&2
  exit 1
fi
if [[ -e "$REPO_ROOT/.git/MERGE_HEAD" || -e "$(git rev-parse --git-path MERGE_HEAD)" ]]; then
  echo "Repository has a merge in progress; refusing to launch." >&2
  exit 1
fi
if ! git rev-parse --verify --quiet "$MERGE_TARGET_BRANCH" >/dev/null; then
  echo "Merge target branch does not exist: $MERGE_TARGET_BRANCH" >&2
  exit 1
fi

export PYTHONPATH="$ACCELERATE_ROOT:$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"
export IPFS_ACCELERATE_AGENT_IMPLEMENTATION_PROVIDER="${PATLAW_IMPLEMENTATION_PROVIDER:-auto}"
export IPFS_ACCELERATE_AGENT_GROK_MODEL="${IPFS_ACCELERATE_AGENT_GROK_MODEL:-grok-4.5}"
export IPFS_ACCELERATE_AGENT_GROK_PERMISSION_MODE="${IPFS_ACCELERATE_AGENT_GROK_PERMISSION_MODE:-bypassPermissions}"
export IPFS_ACCELERATE_AGENT_GROK_BIN="${IPFS_ACCELERATE_AGENT_GROK_BIN:-${HOME}/.local/bin/grok}"
export IPFS_ACCELERATE_AGENT_CODEX_MODEL="gpt-5.6-terra"
export IPFS_ACCELERATE_AGENT_CODEX_REASONING_EFFORT="high"
export IPFS_ACCELERATE_AGENT_AUTO_PROVIDER_CLEAN_FALLBACK="1"

python3 "$REPO_ROOT/scripts/validate_patent_legal_intelligence_board.py" \
  --repo-root "$REPO_ROOT" --config "$CONFIG_PATH"
python3 "$REPO_ROOT/scripts/ops/patent_legal_intelligence/preflight.py" \
  --repo-root "$REPO_ROOT" --accelerate-root "$ACCELERATE_ROOT"

PROTECTED_PATHS=(
  "docs/architecture/PATENT_LEGAL_INTELLIGENCE_PLAN.md"
  "docs/architecture/patent_legal_intelligence.objectives.md"
  "docs/architecture/patent_legal_intelligence.todo.md"
  "config/agent_supervisor_patent_legal_intelligence.json"
  "scripts/validate_patent_legal_intelligence_board.py"
  "scripts/ops/patent_legal_intelligence/preflight.py"
  "scripts/ops/patent_legal_intelligence/launch_multi_lane.sh"
  "scripts/ops/patent_legal_intelligence/status.py"
  "scripts/ops/patent_legal_intelligence/status.sh"
  "scripts/ops/patent_legal_intelligence/README.md"
  "data/agent_supervisor/patent_legal_intelligence/bundles/lane_matrix.json"
  "data/agent_supervisor/patent_legal_intelligence/bundles/launch_recipe.json"
  "data/agent_supervisor/patent_legal_intelligence/bundles/private_boundary_policy.json"
  "data/agent_supervisor/patent_legal_intelligence/bundles/protected_paths.json"
  "data/agent_supervisor/patent_legal_intelligence/bundles/source_authority_policy.json"
)

lane_task_ids() {
  local shard="$1"
  python3 - "$CONFIG_PATH" "$shard" <<'PY'
import json
import sys
from pathlib import Path

config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for task_id in config["lane_slices"][sys.argv[2]]:
    print(task_id)
PY
}

pid_is_alive() {
  local pid_file="$1"
  [[ -f "$pid_file" ]] || return 1
  local pid
  pid="$(awk 'NR==1 {print $1}' "$pid_file" 2>/dev/null || true)"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" 2>/dev/null
}

run_shard() {
  local shard="$1"
  local mode="${2:-launch}"
  local shard_root="$STATE_ROOT/shards/$shard"
  local state_dir="$shard_root/state"
  local worktree_root="$shard_root/worktrees"
  local log_dir="$shard_root/logs"
  local pid_file="$shard_root/supervisor.pid"

  if pid_is_alive "$pid_file"; then
    echo "Shard $shard already has a live supervisor PID in $pid_file" >&2
    return 1
  fi
  mkdir -p "$state_dir" "$worktree_root" "$log_dir" "$MERGE_QUEUE_DIR"

  local -a command=(
    python3 -P -m ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_supervisor
    --todo-path "$TODO_PATH"
    --objective-path "$OBJECTIVE_PATH"
    --task-prefix "$TASK_PREFIX"
    --task-shard-count "$SHARD_COUNT"
    --task-shard-index "$shard"
    --strict-task-sharding
    --state-dir "$state_dir"
    --state-prefix "patlaw_shard_${shard}"
    --worktree-root "$worktree_root"
    --merge-target-branch "$MERGE_TARGET_BRANCH"
    --merge-queue-dir "$MERGE_QUEUE_DIR"
    --daemon-interval 45
    --check-interval 20
    --stale-seconds 900
    --watchdog-startup-grace-seconds 300
    --implementation-timeout 7200
    --implementation-max-timeout 14400
    --implementation-log-stall-seconds 600
    --max-restarts 0
    --max-task-attempts 4
    --merge-reconciliation-max-merges 1
    --no-retry-budget-guardrail
    --no-dependency-guardrail
    --no-reconciliation-guardrail
    --no-objective-task-janitor
    --no-objective-goal-refinement
    --no-objective-goal-completion-reconcile
    --no-objective-goal-migration
  )

  local protected_path
  for protected_path in "${PROTECTED_PATHS[@]}"; do
    command+=(--implementation-protected-path "$protected_path")
  done
  local task_id
  while IFS= read -r task_id; do
    [[ -n "$task_id" ]] && command+=(--execution-slice-task-id "$task_id")
  done < <(lane_task_ids "$shard")

  if [[ "$mode" == "reconcile" ]]; then
    echo "[patlaw] reconciliation preflight shard=$shard/$SHARD_COUNT"
    "${command[@]}" \
      --reconciliation-only \
      --worktree-reconciliation-dry-run \
      --fail-on-reconciliation-error \
      --no-implement \
      --once
    return
  fi

  if [[ "$IMPLEMENT" == "1" ]]; then
    command+=(--implement)
  else
    command+=(--no-implement --worktree-reconciliation-dry-run)
  fi
  if [[ "$ONCE" == "1" ]]; then
    command+=(--once)
  fi

  echo "[patlaw] shard=$shard/$SHARD_COUNT implement=$IMPLEMENT state=$state_dir"
  if [[ "$FOREGROUND" == "1" || "$DRY_RUN" == "1" ]]; then
    "${command[@]}"
    return
  fi
  setsid "${command[@]}" </dev/null >"$log_dir/supervisor.log" 2>&1 &
  local launched_pid=$!
  echo "$launched_pid" >"$pid_file"
  # A printed PID is not launch evidence.  Give the detached process enough
  # time to import the supervisor and fail closed if it did not survive.
  sleep 1
  if ! kill -0 "$launched_pid" 2>/dev/null; then
    echo "Shard $shard supervisor exited during startup; tail follows:" >&2
    tail -n 40 "$log_dir/supervisor.log" >&2 || true
    return 1
  fi
  echo "[patlaw] shard=$shard pid=$launched_pid log=$log_dir/supervisor.log"
}

echo "[patlaw] repo=$REPO_ROOT"
echo "[patlaw] accelerator=$ACCELERATE_ROOT"
echo "[patlaw] board=$TODO_PATH target=$MERGE_TARGET_BRANCH state=$STATE_ROOT"
echo "[patlaw] provider=auto primary=grok/grok-4.5 backup=codex/gpt-5.6-terra shards=$SHARD_COUNT"

if [[ "$FOREGROUND" == "1" ]]; then
  if [[ ! "${PATLAW_SHARD:-}" =~ ^[0-3]$ ]]; then
    echo "PATLAW_SHARD must be one of 0, 1, 2, or 3 with --foreground." >&2
    exit 2
  fi
  run_shard "$PATLAW_SHARD" reconcile
  run_shard "$PATLAW_SHARD"
  exit $?
fi

for shard in 0 1 2 3; do
  run_shard "$shard" reconcile
done
for shard in 0 1 2 3; do
  run_shard "$shard"
done

if [[ "$DRY_RUN" == "1" ]]; then
  echo "[patlaw] all four reviewed slices passed no-implementation preflight."
else
  echo "[patlaw] launched four supervisors; inspect with:"
  echo "  PATLAW_STATE_ROOT=$STATE_ROOT python3 scripts/ops/patent_legal_intelligence/status.py"
fi
