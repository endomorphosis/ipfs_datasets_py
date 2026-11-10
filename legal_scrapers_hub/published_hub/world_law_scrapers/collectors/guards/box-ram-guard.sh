#!/usr/bin/env bash
# Continuous RAM guard (no swap). Every ~45s.
set -u
LOG=/workspace/logs/box-ram-guard.log
PIDFILE=/workspace/logs/box-ram-guard.pid
mkdir -p /workspace/logs
echo $$ > "$PIDFILE"
MAX_COLLECTORS=6
WARN_MB=3500
CRIT_MB=2200
EMERGENCY_MB=1200
SHED=/workspace/scripts/box_shed_collectors.py

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" | tee -a "$LOG" >/dev/null; }
mem_avail() { awk '/MemAvailable:/ {printf "%d", $2/1024}' /proc/meminfo; }

stop_csnaps() {
  if pgrep -x csnaps >/dev/null 2>&1; then
    pkill -x csnaps 2>/dev/null || true
    sleep 1
    pkill -9 -x csnaps 2>/dev/null || true
    rm -rf /var/lib/sand/telemetry/codebase/roots/workspace-* 2>/dev/null || true
    log "stopped_csnaps"
  fi
}

ensure_shed() {
  if [ -x /workspace/venv/bin/python ]; then
    /workspace/venv/bin/python "$SHED" "$1" >>"$LOG" 2>&1 || python3 "$SHED" "$1" >>"$LOG" 2>&1 || true
  else
    python3 "$SHED" "$1" >>"$LOG" 2>&1 || true
  fi
}

log "ram-guard start pid=$$ max_collectors=$MAX_COLLECTORS"
while true; do
  AVAIL=$(mem_avail)
  if [ -f /workspace/logs/disable-csnaps ] || [ -d /workspace/legal-corpora ]; then
    stop_csnaps
  fi
  N_COLLECT=$(ps -eo args= 2>/dev/null | grep -E '/venv/bin/python.* -u collect_[a-z0-9_]+\.py' | grep -v grep | wc -l | tr -d ' ')
  N_DEEPEN=$(ps -eo args= 2>/dev/null | grep -E '/venv/bin/python.* -u .*/(it_deepen|at_deepen)[^ ]*' | grep -v grep | wc -l | tr -d ' ')
  N_WORKERS=$(( ${N_COLLECT:-0} + ${N_DEEPEN:-0} ))

  if [ "$AVAIL" -lt "$EMERGENCY_MB" ]; then
    log "EMERGENCY avail=${AVAIL}MB workers=${N_WORKERS} (collect=${N_COLLECT} deepen=${N_DEEPEN})"
    stop_csnaps
    ensure_shed 2
    pkill -f 'chrome.*--type=renderer' 2>/dev/null || true
    pkill -f 'pip install sentence-transformers' 2>/dev/null || true
    pkill -f 'pip install torch' 2>/dev/null || true
  elif [ "$AVAIL" -lt "$CRIT_MB" ]; then
    log "CRITICAL avail=${AVAIL}MB workers=${N_WORKERS} (collect=${N_COLLECT} deepen=${N_DEEPEN})"
    stop_csnaps
    ensure_shed 3
  elif [ "$AVAIL" -lt "$WARN_MB" ] || [ "${N_WORKERS:-0}" -gt "$MAX_COLLECTORS" ]; then
    log "WARN avail=${AVAIL}MB workers=${N_WORKERS} (collect=${N_COLLECT} deepen=${N_DEEPEN})"
    stop_csnaps
    ensure_shed "$MAX_COLLECTORS"
  else
    log "ok avail=${AVAIL}MB workers=${N_WORKERS} (collect=${N_COLLECT} deepen=${N_DEEPEN})"
  fi

  TELEM_M=$(du -sm /var/lib/sand/telemetry 2>/dev/null | awk '{print $1}')
  if [ "${TELEM_M:-0}" -ge 2048 ]; then
    rm -rf /var/lib/sand/telemetry/codebase/roots/workspace-* 2>/dev/null || true
    log "pruned_telemetry was_mb=${TELEM_M}"
  fi
  sleep 45
done
