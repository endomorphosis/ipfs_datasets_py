#!/usr/bin/env bash
# One-shot MO_bo archive run, queued 2026-10-16 after reboot. Single instance (flock).
# Gate: starts only once wayback_resume_loop is actually running deferred targets (state phase=running or done)
# AND the box-wide Wayback breaker has been closed >= 15 min AND MemAvailable >= 1500 MB.
# Runs through the shared box-wide Wayback rate limiter (same lane/caps as queue_restart.sh), so it adds no extra
# request rate; items it cannot fetch while the breaker is open go to MO_bo/deferred_wayback.tsv, which the
# resume loop picks up later. Phase A small probe (--max-fetch 25), Phase B full resumable run.
set -u
HERE=/workspace/world_law/pipeline/scrapers/national/archive
L=/workspace/world_law/staging/national/_logs/full; LOG=$L/mo_archive.log
ST=/workspace/world_law/staging/national/_logs/archive/wayback_resume_loop.state.json
PY=/workspace/world_law/pipeline/venv/bin/python
export PYTHONUNBUFFERED=1 ARCHIVE_LANE=national MALLOC_ARENA_MAX=2
AS=${AS:-629145600}; MIN_FREE_MB=${MIN_FREE_MB:-1500}; STABLE=${STABLE:-900}
exec 9>"$L/mo_bo_after_resume.lock"; flock -n 9 || { echo "$(date '+%F %T %Z') another mo_bo_after_resume holds lock; exit" >> "$LOG"; exit 0; }
cd "$HERE"
log() { echo "$(date '+%F %T %Z') mo_bo_after_resume $$: $*" >> "$LOG"; }
ready() {
  $PY - "$ST" "$STABLE" <<'PY'
import json, sys, time
sys.path.insert(0, "/workspace/world_law/pipeline")
from archive import ratelimit as r
st = json.load(open(sys.argv[1])); b = r.breaker_status()
if st.get("phase") not in ("running", "done") or b.get("state") == "open": sys.exit(1)
since = max(float(b.get("closed_at") or 0), float(b.get("opened_at") or 0))
sys.exit(0 if time.time() - since >= float(sys.argv[2]) else 1)
PY
}
gate() { while ! ready || [ $(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo) -lt $MIN_FREE_MB ]; do sleep 120; done; }
log "queued (waiting for resume loop running + breaker closed >= ${STABLE}s + mem >= ${MIN_FREE_MB}M)"
gate; log "gate open: small probe"
prlimit --as=$AS nice -n 10 $PY run_archive.py MO_bo --max-fetch 25 --chunk 25 >> "$LOG" 2>&1; log "small MO_bo rc=$?"
gate; log "gate open: full run"
prlimit --as=$AS nice -n 10 $PY run_archive.py MO_bo --chunk 200 >> "$LOG" 2>&1; log "full MO_bo rc=$?"
log "DONE"
