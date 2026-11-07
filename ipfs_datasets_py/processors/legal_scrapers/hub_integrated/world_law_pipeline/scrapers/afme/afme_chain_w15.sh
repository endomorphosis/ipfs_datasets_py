#!/usr/bin/env bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# afme wave 15 (TN; MA CI CM JO LB skipped, see README_afme.md), one process at a time: live -> archive (CC first, Wayback via breaker, 1 worker) for live misses -> stage.
set -u
export ARCHIVE_LANE=afme AFME_AS_LIMIT_MB=1200
PY=${WORLD_LAW_ROOT}/.venv_afme/bin/python
OUT=${WORLD_LAW_ROOT}/out
LOG=${WORLD_LAW_ROOT}/staging/afme/_logs/chain_w15_$(date -u +%Y%m%dT%H%M%SZ).log
mkdir -p "$(dirname "$LOG")"; cd "$OUT"; echo "log $LOG"
ulimit -v 1228800
guard() {
  # Disk: multi-source confirm via afme_common.disk_check (never stop on one reading).
  mem_mb=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)
  if [ "$mem_mb" -lt 2048 ]; then echo "mem guard: MemAvailable ${mem_mb} MB, stop" | tee -a "$LOG"; exit 4; fi
  if ! $PY -c 'import afme_common as C; C.disk_check()'; then
    echo "disk guard: stop after confirm/retry" | tee -a "$LOG"; exit 3
  fi
  return 0
}
for CC in TN; do
  guard
  echo "== $CC live $(date -u +%FT%TZ)" | tee -a "$LOG"
  $PY afme_live_doh.py "$CC" >>"$LOG" 2>&1 || echo "$CC live exit $?" | tee -a "$LOG"
  guard
  TODO="afme/done/arch_todo_$CC.tsv"
  if [ ! -s "$TODO" ] && [ -s "afme/done/live_$CC.tsv" ]; then
    awk -F'\t' -v p="iso:$CC" '$2=="miss"{print p"\t"$1}' "afme/done/live_$CC.tsv" > "$TODO.tmp" && mv "$TODO.tmp" "$TODO"
    [ -s "$TODO" ] || mv "$TODO" "afme/done/arch_todo_$CC.empty"
  fi
  if [ -s "$TODO" ]; then
    echo "== $CC archive" | tee -a "$LOG"
    $PY afme_arch.py "$CC" --urls-file "$TODO" >>"$LOG" 2>&1 || echo "$CC arch exit $?" | tee -a "$LOG"
  fi
  guard
  echo "== $CC stage" | tee -a "$LOG"
  $PY afme_stage.py "$CC" >>"$LOG" 2>&1 || echo "$CC stage exit $?" | tee -a "$LOG"
done
echo "== chain done $(date -u +%FT%TZ)" | tee -a "$LOG"
