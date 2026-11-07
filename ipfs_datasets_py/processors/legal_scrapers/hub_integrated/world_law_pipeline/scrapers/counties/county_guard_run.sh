: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-11-01 19:30 PST: guard_run for county chains (source after county_chain_guard.sh). Floors: disk GUARD_MIN_MIB (free on /workspace),
# RAM GUARD_MIN_RAM_MIB (MemAvailable). Checked before each step and every 30 s while it runs; on breach the step's private
# GUARD_STOPFILE is touched (pdf_list_fetch.py stops cleanly), then killed after 120 s; guard_run returns 99.
: "${GUARD_MIN_MIB:=10240}"  # 2026-11-02: disk floor 10 GB fleet floor per Benjamin (was 20 GB)
: "${GUARD_MIN_RAM_MIB:=1536}"
avail_mib() { awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo; }
floors_ok() { [ "$(free_mib)" -ge "$GUARD_MIN_MIB" ] && [ "$(avail_mib)" -ge "$GUARD_MIN_RAM_MIB" ]; }
guard_run() {
  local name=$1; shift
  export GUARD_STOPFILE=${WORLD_LAW_ROOT}/staging/counties/_logs/.stop_${name}_$$; rm -f "$GUARD_STOPFILE"
  if ! floors_ok; then echo "$(date) GUARD $name not started: disk $(free_mib) MiB, ram $(avail_mib) MiB"; return 99; fi
  echo "$(date) GUARD start $name"; "$@" & local p=$! br=0
  while kill -0 $p 2>/dev/null; do
    sleep 30
    if [ $br -eq 0 ] && ! floors_ok; then br=1; echo "$(date) GUARD breach $name: disk $(free_mib) MiB, ram $(avail_mib) MiB -> stop"; touch "$GUARD_STOPFILE"; local t=0
      while kill -0 $p 2>/dev/null && [ $t -lt 120 ]; do sleep 5; t=$((t+5)); done; kill $p 2>/dev/null; fi
  done
  wait $p; local rc=$?; rm -f "$GUARD_STOPFILE"; echo "$(date) GUARD end $name rc=$rc"
  [ $br -eq 1 ] && return 99; return $rc
}
# 2026-11-02 19:20 PST: wait-and-retry wrapper. guard_retry runs guard_run; on rc 99 (floor breach / not started) it sleeps
# GUARD_WAIT_S (300 s) and rechecks floors, retrying for up to GUARD_WAIT_MAX_S (7200 s) of cumulative waiting before giving up (99).
# Steps must be resumable (pdf_list_fetch.py done ledger; archive_retry.py skips already-got URLs).
: "${GUARD_WAIT_S:=300}"; : "${GUARD_WAIT_MAX_S:=7200}"
guard_retry() {
  local waited=0 rc
  while :; do
    guard_run "$@"; rc=$?
    [ $rc -ne 99 ] && return $rc
    [ $waited -ge $GUARD_WAIT_MAX_S ] && { echo "$(date) GUARD $1 gave up after ${waited}s waiting"; return 99; }
    echo "$(date) GUARD $1 floors low (disk $(free_mib) MiB, ram $(avail_mib) MiB) -> wait ${GUARD_WAIT_S}s (waited ${waited}s)"
    sleep $GUARD_WAIT_S; waited=$((waited+GUARD_WAIT_S))
    floors_ok && waited=0 2>/dev/null; floors_ok || continue
  done
}
