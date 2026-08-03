#!/usr/bin/env bash
# PATLAW-080: Serialized datasets/accelerator upstream synchronization.
#
# Explicit triggers:
#   startup       — fetch both origins (no integration mutation)
#   eight-hour    — fetch both origins (periodic; no integration mutation)
#   twice-daily   — serialized integration on clean branches + pair tests
#   pre-release   — serialized integration on clean branches + pair tests
#   security-fix  — serialized integration on clean branches + pair tests
#
# Hard policy (fail-closed):
#   * dirty or active work aborts WITHOUT mutation
#   * conflicts fail closed
#   * no recursive mutual-submodule chase
#   * accepted receipt binds both SHAs and test receipts
#   * NO PUSH occurs under any path
#
# Usage:
#   scripts/ops/uspto/sync_upstreams.sh --trigger <name> [options]
#   scripts/ops/uspto/sync_upstreams.sh --list-triggers
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${CROSS_REPO_SYNC_REPO_ROOT:-$SCRIPT_DIR/../../..}" && pwd)"
CHECKER="${SCRIPT_DIR}/check_cross_repo_compatibility.py"
PYTHON_BIN="${CROSS_REPO_SYNC_PYTHON:-python3}"

# Defaults — overridable via env or flags.
DATASETS_PATH="${CROSS_REPO_SYNC_DATASETS_PATH:-$REPO_ROOT}"
ACCELERATOR_PATH="${CROSS_REPO_SYNC_ACCELERATOR_PATH:-$REPO_ROOT/ipfs_accelerate_py}"
# HOME may be unset under sealed validation environments (`set -u`).
_HOME="${HOME:-${TMPDIR:-/tmp}}"
_XDG_STATE="${XDG_STATE_HOME:-$_HOME/.local/state}"
STATE_ROOT="${CROSS_REPO_SYNC_STATE_ROOT:-$_XDG_STATE/ipfs_accelerate_py/uspto_submission_assurance/cross_repo_sync}"
LOCK_PATH="${CROSS_REPO_SYNC_LOCK_PATH:-$STATE_ROOT/sync.lock}"
OUTPUT_PATH="${CROSS_REPO_SYNC_OUTPUT_PATH:-$STATE_ROOT/compatibility_manifest.json}"
ACTIVE_MARKER="${CROSS_REPO_SYNC_ACTIVE_MARKER:-}"
TRIGGER=""
DRY_RUN=0
SKIP_FETCH=0
PLAN_ONLY=0
LIST_TRIGGERS=0
JSON_OUT=1
OUTPUT_EXPLICIT=0
LOCK_EXPLICIT=0
# Preserve env-provided lock/output as explicit so --state-root does not clobber.
if [[ -n "${CROSS_REPO_SYNC_OUTPUT_PATH:-}" ]]; then
  OUTPUT_EXPLICIT=1
fi
if [[ -n "${CROSS_REPO_SYNC_LOCK_PATH:-}" ]]; then
  LOCK_EXPLICIT=1
fi

FETCH_ONLY_TRIGGERS=("startup" "eight-hour")
INTEGRATION_TRIGGERS=("twice-daily" "pre-release" "security-fix")
ALL_TRIGGERS=("startup" "eight-hour" "twice-daily" "pre-release" "security-fix")

timestamp() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

log() {
  # Content-free operator log line to stderr.
  echo "$(timestamp) [sync_upstreams] $*" >&2
}

die() {
  log "ERROR: $*"
  exit 2
}

usage() {
  cat <<'EOF'
Usage: sync_upstreams.sh --trigger <trigger> [options]

Triggers (explicit):
  startup        Fetch both origins (no integration mutation)
  eight-hour     Fetch both origins every eight hours (no integration mutation)
  twice-daily    Serialized integration on clean branches + pair tests
  pre-release    Serialized integration for release gate + pair tests
  security-fix   Serialized integration for security fix lane + pair tests

Options:
  --datasets-path PATH       Datasets repository path
  --accelerator-path PATH    Accelerator repository path
  --output PATH              Atomic compatibility manifest output path
  --lock-path PATH           Serialization lock path
  --state-root PATH          Default state directory for lock/output
  --active-marker PATH       If this path exists, abort without mutation
  --repo-root PATH           Repository root for path defaults
  --dry-run                  Plan + synthetic receipts; no network fetch
  --skip-fetch               Do not git fetch
  --plan-only                Print plan JSON and exit (no mutation)
  --list-triggers            Print the explicit trigger set and exit
  -h, --help                 Show this help

Environment:
  CROSS_REPO_SYNC_REPO_ROOT, CROSS_REPO_SYNC_DATASETS_PATH,
  CROSS_REPO_SYNC_ACCELERATOR_PATH, CROSS_REPO_SYNC_STATE_ROOT,
  CROSS_REPO_SYNC_LOCK_PATH, CROSS_REPO_SYNC_OUTPUT_PATH,
  CROSS_REPO_SYNC_ACTIVE_MARKER, CROSS_REPO_SYNC_PYTHON,
  CROSS_REPO_SYNC_FORCE_ACTIVE=1  (test hook: force active-work abort)

Policy: never push; never git submodule update --recursive;
dirty/active work aborts without mutation; conflicts fail closed.
EOF
}

is_known_trigger() {
  local t="$1"
  local x
  for x in "${ALL_TRIGGERS[@]}"; do
    if [[ "$x" == "$t" ]]; then
      return 0
    fi
  done
  return 1
}

is_fetch_only() {
  local t="$1"
  local x
  for x in "${FETCH_ONLY_TRIGGERS[@]}"; do
    if [[ "$x" == "$t" ]]; then
      return 0
    fi
  done
  return 1
}

is_integration() {
  local t="$1"
  local x
  for x in "${INTEGRATION_TRIGGERS[@]}"; do
    if [[ "$x" == "$t" ]]; then
      return 0
    fi
  done
  return 1
}

# Refuse any push invocation that might be introduced later in this script.
git_no_push() {
  if [[ "${1:-}" == "push" ]]; then
    die "git push is forbidden by cross-repo sync policy"
  fi
  # Also refuse recursive submodule chase via this wrapper.
  if [[ "${1:-}" == "submodule" ]]; then
    local arg
    for arg in "$@"; do
      if [[ "$arg" == "--recursive" || "$arg" == "--recurse-submodules" || "$arg" == "--recurse" ]]; then
        die "recursive submodule chase is forbidden by cross-repo sync policy"
      fi
    done
  fi
  if [[ "${1:-}" == "fetch" ]]; then
    local arg
    for arg in "$@"; do
      if [[ "$arg" == "--recurse-submodules" || "$arg" == "--recurse-submodules=yes" || "$arg" == "--recurse-submodules=on-demand" ]]; then
        die "recursive submodule chase is forbidden by cross-repo sync policy"
      fi
    done
  fi
  command git "$@"
}

repo_is_dirty() {
  local repo="$1"
  if [[ ! -d "$repo/.git" ]] && ! git -C "$repo" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    return 1
  fi
  local porcelain
  porcelain="$(git -C "$repo" status --porcelain --untracked-files=normal 2>/dev/null || true)"
  [[ -n "$porcelain" ]]
}

repo_has_conflicts() {
  local repo="$1"
  if ! git -C "$repo" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    return 1
  fi
  local unmerged
  unmerged="$(git -C "$repo" diff --name-only --diff-filter=U 2>/dev/null || true)"
  [[ -n "$unmerged" ]]
}

active_work_present() {
  if [[ "${CROSS_REPO_SYNC_FORCE_ACTIVE:-}" == "1" || "${CROSS_REPO_SYNC_FORCE_ACTIVE:-}" == "true" ]]; then
    return 0
  fi
  if [[ -n "$ACTIVE_MARKER" && -e "$ACTIVE_MARKER" ]]; then
    return 0
  fi
  local candidate
  for candidate in \
    "$DATASETS_PATH/.cross_repo_sync_active" \
    "$DATASETS_PATH/.lane_active" \
    "$DATASETS_PATH/ACTIVE_LANE" \
    "$ACCELERATOR_PATH/.cross_repo_sync_active" \
    "$ACCELERATOR_PATH/.lane_active" \
    "$ACCELERATOR_PATH/ACTIVE_LANE"
  do
    if [[ -e "$candidate" ]]; then
      ACTIVE_MARKER="$candidate"
      return 0
    fi
  done
  return 1
}

acquire_lock() {
  mkdir -p "$(dirname "$LOCK_PATH")"
  # Prefer flock when available; fall back to mkdir lock for portability.
  if command -v flock >/dev/null 2>&1; then
    exec 9>"$LOCK_PATH"
    if ! flock -n 9; then
      die "serialization lock held: $LOCK_PATH (fail closed)"
    fi
    log "lock_acquired path=$LOCK_PATH method=flock"
    return 0
  fi
  local lock_dir="${LOCK_PATH}.d"
  if mkdir "$lock_dir" 2>/dev/null; then
    echo "$$" >"${lock_dir}/pid"
    log "lock_acquired path=$lock_dir method=mkdir"
    # shellcheck disable=SC2064
    trap 'rm -rf "'"$lock_dir"'"' EXIT
    return 0
  fi
  die "serialization lock held: $lock_dir (fail closed)"
}

abort_via_checker() {
  # Produce an aborted receipt without mutating either worktree.
  local reason_note="$1"
  log "abort_without_mutation reason=$reason_note"
  local marker_args=()
  if [[ -n "$ACTIVE_MARKER" ]]; then
    marker_args+=(--active-marker "$ACTIVE_MARKER")
  fi
  # Force active/dirty detection through the checker by setting env when needed.
  local env_force=()
  if [[ "$reason_note" == "active_work" ]]; then
    export CROSS_REPO_SYNC_FORCE_ACTIVE=1
  fi
  "$PYTHON_BIN" "$CHECKER" \
    --run \
    --skip-fetch \
    --trigger "$TRIGGER" \
    --datasets-path "$DATASETS_PATH" \
    --accelerator-path "$ACCELERATOR_PATH" \
    --output "$OUTPUT_PATH" \
    --lock-path "$LOCK_PATH" \
    --repo-root "$REPO_ROOT" \
    "${marker_args[@]}" \
    || true
  # Exit code 3 = aborted (policy).
  exit 3
}

# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------

while [[ $# -gt 0 ]]; do
  case "$1" in
    --trigger)
      TRIGGER="${2:-}"
      shift 2
      ;;
    --datasets-path)
      DATASETS_PATH="${2:-}"
      shift 2
      ;;
    --accelerator-path)
      ACCELERATOR_PATH="${2:-}"
      shift 2
      ;;
    --output)
      OUTPUT_PATH="${2:-}"
      OUTPUT_EXPLICIT=1
      shift 2
      ;;
    --lock-path)
      LOCK_PATH="${2:-}"
      LOCK_EXPLICIT=1
      shift 2
      ;;
    --state-root)
      STATE_ROOT="${2:-}"
      # Only fill defaults when the caller did not set lock/output explicitly.
      if [[ "$LOCK_EXPLICIT" -eq 0 ]]; then
        LOCK_PATH="$STATE_ROOT/sync.lock"
      fi
      if [[ "$OUTPUT_EXPLICIT" -eq 0 ]]; then
        OUTPUT_PATH="$STATE_ROOT/compatibility_manifest.json"
      fi
      shift 2
      ;;
    --active-marker)
      ACTIVE_MARKER="${2:-}"
      shift 2
      ;;
    --repo-root)
      REPO_ROOT="${2:-}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --skip-fetch)
      SKIP_FETCH=1
      shift
      ;;
    --plan-only)
      PLAN_ONLY=1
      shift
      ;;
    --list-triggers)
      LIST_TRIGGERS=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

if [[ "$LIST_TRIGGERS" -eq 1 ]]; then
  "$PYTHON_BIN" - <<'PY'
import json
print(json.dumps({
  "triggers": ["startup", "eight-hour", "twice-daily", "pre-release", "security-fix"],
  "fetch_only_triggers": ["startup", "eight-hour"],
  "integration_triggers": ["twice-daily", "pre-release", "security-fix"],
  "push_allowed": False,
  "recursive_submodules": False,
}, indent=2, sort_keys=True))
PY
  exit 0
fi

if [[ -z "$TRIGGER" ]]; then
  usage >&2
  die "--trigger is required"
fi

if ! is_known_trigger "$TRIGGER"; then
  die "unknown trigger: $TRIGGER (expected: ${ALL_TRIGGERS[*]})"
fi

if [[ ! -f "$CHECKER" ]]; then
  die "checker missing: $CHECKER"
fi

mkdir -p "$(dirname "$OUTPUT_PATH")"
mkdir -p "$(dirname "$LOCK_PATH")"

log "start trigger=$TRIGGER datasets=$DATASETS_PATH accelerator=$ACCELERATOR_PATH dry_run=$DRY_RUN"

# ---------------------------------------------------------------------------
# Fail-closed preflight: dirty / active / conflicts — abort without mutation
# ---------------------------------------------------------------------------

if active_work_present; then
  log "active_work_detected marker=${ACTIVE_MARKER:-forced}"
  abort_via_checker "active_work"
fi

# Conflicts before dirty: unmerged paths also appear dirty.
if repo_has_conflicts "$DATASETS_PATH" || repo_has_conflicts "$ACCELERATOR_PATH"; then
  log "merge_conflict_detected"
  abort_via_checker "merge_conflict"
fi

if repo_is_dirty "$DATASETS_PATH" || repo_is_dirty "$ACCELERATOR_PATH"; then
  log "dirty_worktree_detected"
  abort_via_checker "dirty_worktree"
fi

# ---------------------------------------------------------------------------
# Serialization for integration triggers (and for any non-plan run)
# ---------------------------------------------------------------------------

if [[ "$PLAN_ONLY" -eq 0 ]]; then
  acquire_lock
fi

if [[ "$PLAN_ONLY" -eq 1 ]]; then
  marker_args=()
  if [[ -n "$ACTIVE_MARKER" ]]; then
    marker_args+=(--active-marker "$ACTIVE_MARKER")
  fi
  exec "$PYTHON_BIN" "$CHECKER" \
    --plan-only \
    --trigger "$TRIGGER" \
    --datasets-path "$DATASETS_PATH" \
    --accelerator-path "$ACCELERATOR_PATH" \
    --repo-root "$REPO_ROOT" \
    "${marker_args[@]}"
fi

# ---------------------------------------------------------------------------
# Optional direct fetch (non-recursive). Checker also fetches unless skipped.
# Shell-level fetch documents the no-recurse policy explicitly for operators.
# ---------------------------------------------------------------------------

if [[ "$DRY_RUN" -eq 0 && "$SKIP_FETCH" -eq 0 ]]; then
  for repo in "$DATASETS_PATH" "$ACCELERATOR_PATH"; do
    if git -C "$repo" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
      log "fetch_begin repo=$repo recurse_submodules=false"
      # Explicit: never --recurse-submodules.
      if ! git_no_push -C "$repo" fetch origin --no-recurse-submodules; then
        log "fetch_soft_fail repo=$repo (fail closed only if integration requires it)"
      else
        log "fetch_ok repo=$repo"
      fi
    else
      log "fetch_skip repo=$repo reason=not_a_git_repo"
    fi
  done
fi

# Re-check dirty after fetch — fetch of remote-tracking refs must not dirty;
# if the tree became dirty, abort without further mutation.
if repo_is_dirty "$DATASETS_PATH" || repo_is_dirty "$ACCELERATOR_PATH"; then
  log "dirty_after_fetch_abort"
  abort_via_checker "dirty_worktree"
fi

if repo_has_conflicts "$DATASETS_PATH" || repo_has_conflicts "$ACCELERATOR_PATH"; then
  log "conflict_after_fetch_abort"
  abort_via_checker "merge_conflict"
fi

# ---------------------------------------------------------------------------
# Delegate receipt production, SHA binding, and pair tests to the checker.
# Integration triggers run pair tests; fetch-only binds SHAs when available.
# Never push. Never recursive submodule update.
# ---------------------------------------------------------------------------

checker_args=(
  --run
  --trigger "$TRIGGER"
  --datasets-path "$DATASETS_PATH"
  --accelerator-path "$ACCELERATOR_PATH"
  --output "$OUTPUT_PATH"
  --lock-path "$LOCK_PATH"
  --repo-root "$REPO_ROOT"
  --skip-fetch
)

if [[ "$DRY_RUN" -eq 1 ]]; then
  checker_args+=(--dry-run)
fi
if [[ -n "$ACTIVE_MARKER" ]]; then
  checker_args+=(--active-marker "$ACTIVE_MARKER")
fi

log "checker_begin output=$OUTPUT_PATH"
set +e
"$PYTHON_BIN" "$CHECKER" "${checker_args[@]}"
rc=$?
set -e

if [[ ! -f "$OUTPUT_PATH" ]]; then
  die "compatibility manifest was not written: $OUTPUT_PATH"
fi

log "checker_done exit=$rc manifest=$OUTPUT_PATH push_attempted=false recursive_submodule_chase=false"

# Final hard guarantees for operators inspecting the script contract.
# These greppable tokens document the permanent policy in process logs.
log "policy push_allowed=false recursive_submodules=false fail_closed_on_conflict=true"
log "triggers_explicit startup,eight-hour,twice-daily,pre-release,security-fix"

exit "$rc"
