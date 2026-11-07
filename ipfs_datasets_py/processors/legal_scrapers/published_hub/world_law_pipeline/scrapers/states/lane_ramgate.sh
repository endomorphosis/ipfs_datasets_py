#!/bin/bash
# lane_ramgate.sh (2026-10-25): source me.
#   ramgate_run EST_MB LOGFILE cmd args...   waits until states-lane python RSS + EST_MB <= RAMGATE_CAP_MB (1000)
#   and disk free >= 11 GB, starts cmd (stdout/stderr appended to LOGFILE), keeps the shared gate lock for 120 s so
#   the new process's RSS is visible before another gated queue decides, then waits for cmd and returns its rc.
LANE_DIR=/workspace/world_law/pipeline/scrapers/states
GATE_LOCK=/workspace/world_law/staging/states/_state/ramgate.lock
lane_rss_mb() {
  local t=0 p r
  for p in $(pgrep -f python); do
    [ "$(readlink /proc/$p/cwd 2>/dev/null)" = "$LANE_DIR" ] || continue
    r=$(awk '/VmRSS/{print $2}' /proc/$p/status 2>/dev/null); t=$((t + ${r:-0}))
  done
  echo $((t / 1024))
}
ramgate_run() {
  local est=$1 log=$2; shift 2
  local cap=${RAMGATE_CAP_MB:-1000} cur dfree pid
  exec 9>"$GATE_LOCK"
  while true; do
    flock 9
    cur=$(lane_rss_mb); dfree=$(df -BG --output=avail /workspace | tail -1 | tr -dc 0-9)
    if [ $((cur + est)) -le "$cap" ] && [ "${dfree:-0}" -ge 11 ]; then break; fi
    flock -u 9; sleep 120
  done
  echo "$(date '+%F %T') ramgate open (lane ${cur} MB + est ${est} MB <= ${cap}; disk ${dfree}G): $*"
  "$@" >> "$log" 2>&1 9>&- &
  pid=$!
  echo "$(date '+%F %T') started pid $pid"
  sleep 120; flock -u 9; exec 9>&-
  wait $pid
}
