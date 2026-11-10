#!/bin/bash
# breaker_loop.sh <stopfile> <cmd...>: rerun <cmd> while it exits 75 (items deferred: Wayback breaker open or
# 429/5xx host cool-down). Between runs: wait for the breaker (wb_wait.py), then sleep until the earliest
# not_before the job reported via $ARCH_NEXT_FILE (min 60 s, max 1 h), so an all-deferred pass never busy-loops.
cd "$(dirname "$0")"
SF=$1; shift
CS=/workspace/world_law/staging/asia_latam/_archive_work/_STOP_worker3e
export ARCH_NEXT_FILE=${ARCH_NEXT_FILE:-$(mktemp /tmp/arch_next.XXXXXX)}
MIN=${BL_MIN_SLEEP:-60}; MAX=${BL_MAX_SLEEP:-3600}
stopped() { [ -e "$SF" ] || [ -e "$CS" ]; }
while true; do
  rm -f "$ARCH_NEXT_FILE"
  start=$(date +%s)
  "$@"; rc=$?
  [ $rc -ne 75 ] && { rm -f "$ARCH_NEXT_FILE"; exit $rc; }
  echo "$(date) rc=75 (deferred items) -> waiting for breaker: $*"
  /workspace/world_law/pipeline/venv/bin/python -u wb_wait.py "$SF" "$CS" || exit 0
  now=$(date +%s)
  nb=$(cut -d. -f1 "$ARCH_NEXT_FILE" 2>/dev/null); nb=${nb:-0}
  wait=$(( nb > now ? nb - now : 0 ))
  ran=$(( now - start ))
  # a short pass (everything deferred/cooling) must not respin quickly
  [ $wait -lt $MIN ] && [ $ran -lt 600 ] && wait=$MIN
  [ $wait -gt $MAX ] && wait=$MAX
  echo "$(date) breaker closed; earliest not_before=$nb ($(( nb > now ? nb - now : 0 ))s), pass took ${ran}s -> sleeping ${wait}s"
  end=$(( now + wait ))
  while [ "$(date +%s)" -lt $end ]; do stopped && { echo "$(date) stop file -> exit"; exit 0; }; sleep 10; done
  echo "$(date) rerun: $*"
done
