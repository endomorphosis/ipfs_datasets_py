#!/usr/bin/env bash
# afme wave 13. ML always. SN+MG are owned by afme_superv_mgsn.py when its ACTIVE
# flag is present (hourly w13 watch must not overlap those targets). Without ACTIVE,
# this chain still runs SN -> MG -> ML for manual/legacy use.
# Disk: multi-source confirm via afme_common.disk_check (never stop on one reading).
set -u
export ARCHIVE_LANE=afme AFME_AS_LIMIT_MB=1200
PY=/workspace/world_law/.venv_afme/bin/python
OUT=/workspace/world_law/out
LOG=/workspace/world_law/staging/afme/_logs/chain_w13_$(date -u +%Y%m%dT%H%M%SZ).log
SUPERV_ACTIVE=/workspace/world_law/staging/afme/_state/superv_mgsn/ACTIVE
mkdir -p "$(dirname "$LOG")"; cd "$OUT"; echo "log $LOG"
ulimit -v 1228800
guard() {
  mem_mb=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)
  if [ "$mem_mb" -lt 2048 ]; then echo "mem guard: MemAvailable ${mem_mb} MB, stop" | tee -a "$LOG"; exit 4; fi
  if ! $PY -c 'import afme_common as C; C.disk_check()'; then
    echo "disk guard: stop after confirm/retry" | tee -a "$LOG"; exit 3
  fi
  return 0
}
if [ -f "$SUPERV_ACTIVE" ]; then
  CCS="ML"
  echo "superv_mgsn ACTIVE -> SN/MG skipped (supervisor owns them); ML only" | tee -a "$LOG"
else
  CCS="SN MG ML"
fi
for CC in $CCS; do
  guard
  echo "== $CC live $(date -u +%FT%TZ)" | tee -a "$LOG"
  if [ "$CC" = MG ]; then $PY -u afme_mg_cnlegis.py >>"$LOG" 2>&1 || echo "$CC live exit $?" | tee -a "$LOG"
  else $PY -u afme_live.py "$CC" >>"$LOG" 2>&1 || echo "$CC live exit $?" | tee -a "$LOG"; fi
  if [ -s "afme/done/arch_todo_$CC.tsv" ]; then
    echo "== $CC archive" | tee -a "$LOG"
    $PY -u afme_arch.py "$CC" --urls-file "afme/done/arch_todo_$CC.tsv" >>"$LOG" 2>&1 || echo "$CC arch exit $?" | tee -a "$LOG"
  fi
  echo "== $CC stage" | tee -a "$LOG"
  $PY -u afme_stage.py "$CC" >>"$LOG" 2>&1 || echo "$CC stage exit $?" | tee -a "$LOG"
done
echo "== chain done $(date -u +%FT%TZ)" | tee -a "$LOG"
