#!/bin/sh
# 2026-11-02: chunked deferred-places loop (after robots_requeue_20261102T1008 hit the 900 MB RSS StopRun).
# 2026-11-05: unbuffered cycle logging + per-chunk timeout 30m + sleep heartbeats (silent 12h gate-wait fix).
# Each chunk = fresh councils.py --archive-queue process over <=CHUNK due deferred places (+ never-processed places
# from robots_requeue_rest_20261101.txt). ArchiveDeferred not_before honoured by requeue only (worker never sleeps).
# RSS StopRun -> next chunk; disk StopRun -> multi-method confirm >=4 min + retry up to 2h (floor 10 GB). Max 6 runs per place in this loop (counts file). Loop sleeps until
# the earliest future not_before (cap 1 h) when nothing is due; DEFERRED_CHUNKED_DONE only when no eligible work remains.
PY=/workspace/world_law/pipeline/venv/bin/python; [ -x "$PY" ] || PY=/usr/bin/python3
cd /workspace/world_law/pipeline/scrapers/ukie
S=/workspace/world_law/staging/ukie/_state
LOG=${LOG:-$S/logs/deferred_chunked_$(date +%Y%m%dT%H%M).log}
mkdir -p "$S/logs"
# Dedicated append fd so every cycle line hits disk (independent of launch redirection).
exec 3>>"$LOG"
log() { printf '%s\n' "$*" >&3; }
export MALLOC_ARENA_MAX=2 ARCHIVE_LANE=ukie UKIE_IGNORE_ROBOTS=1
CHUNK=${CHUNK:-50}; MAXRUNS=6; CHUNK_TIMEOUT=${CHUNK_TIMEOUT:-1800}; HEARTBEAT=${HEARTBEAT:-300}
CNT=$S/deferred_chunked_counts.tsv; CF=$S/deferred_chunked_chunk.txt; OUT=$S/deferred_chunked_last_chunk.out
exec 8>>$S/deferred_chunked.lock; flock -n 8 || { log "deferred_chunked already running"; echo "deferred_chunked already running"; exit 1; }
. ./archive_passes.sh
ukie_archive_exclusive
touch $CNT; n=0
log "$(date '+%FT%T%z') deferred_chunked start pid=$$ chunk=$CHUNK timeout=${CHUNK_TIMEOUT}s heartbeat=${HEARTBEAT}s ignore_robots=1 disk_guard=10GB rss_guard=900MB log=$LOG"

# Sleep $1 seconds, logging a heartbeat every HEARTBEAT seconds so the lane cannot go silent.
sleep_hb() {
  _total=$1; _left=$_total; _reason=${2:-wait}
  log "$(date '+%FT%T%z') sleep_hb begin reason=$_reason total=${_total}s"
  while [ "$_left" -gt 0 ]; do
    _step=$HEARTBEAT
    [ "$_left" -lt "$_step" ] && _step=$_left
    sleep "$_step"
    _left=$((_left - _step))
    log "$(date '+%FT%T%z') sleep_hb tick reason=$_reason remaining=${_left}s/${_total}s"
  done
  log "$(date '+%FT%T%z') sleep_hb end reason=$_reason"
}

while :; do
  W=$($PY - "$S" "$CNT" "$CF" "$CHUNK" "$MAXRUNS" <<'PYEOF'
import sqlite3, sys, time
S, cnt, cf, chunk, mx = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5])
c = sqlite3.connect(f'file:{S}/ukie_state.sqlite?mode=ro', uri=True)
counts = {}
for l in open(cnt):
    p = l.split('\t')
    if len(p) == 2: counts[p[0]] = int(p[1])
rest = [l.strip() for l in open(f'{S}/robots_requeue_rest_20261101.txt') if l.strip()]
now = time.time(); due = []; fut = []
for pid, nb in c.execute("SELECT p.place_id, (SELECT MIN(not_before) FROM archive_deferrals d WHERE d.place_id=p.place_id AND d.state='pending') FROM places p WHERE p.status='deferred' ORDER BY p.phase DESC, p.place_id"):
    if counts.get(pid, 0) >= mx: continue
    (due if (nb or 0) <= now else fut).append((pid, nb))
st = dict(c.execute("SELECT place_id, status FROM places"))
seen = {p for p, _ in due}
for pid in rest:   # requeued but never processed (still todo/absent)
    if st.get(pid) in (None, 'todo') and counts.get(pid, 0) < mx and pid not in seen: due.append((pid, 0))
if due:
    sel = [p for p, _ in due[:chunk]]
    open(cf, 'w').write(''.join(p + '\n' for p in sel))
    print(f'RUN {len(sel)} {len(due)} {len(fut)}')
elif fut:
    print(f'WAIT {max(1, int(min(nb for _, nb in fut) - now) + 1)} {len(fut)}')
else:
    print('NONE')
PYEOF
) || { log "$(date '+%FT%T%z') selector failed"; exit 1; }
  set -- $W
  case $1 in
    NONE) log "$(date '+%FT%T%z') no due or future-eligible deferred work left (cap $MAXRUNS runs/place)"
          log DEFERRED_CHUNKED_DONE; echo DEFERRED_CHUNKED_DONE; exit 0;;
    WAIT) s=$2; [ "$s" -gt 3600 ] && s=3600
          log "$(date '+%FT%T%z') nothing due; $3 place(s) waiting on not_before; sleeping ${s}s"
          sleep_hb "$s" not_before; continue;;
  esac
  G=$($PY - <<'PYEOF'
# shared archive gate (same sources councils.py/archive use): Wayback breaker + Common Crawl cool-down/backoff
import sys, time; sys.path.insert(0, '/workspace/world_law/pipeline')
from archive import ratelimit, deferral
b = ratelimit.breaker_status(); w = []
if b.get('state') == 'open' and not ratelimit.wayback_available(): w.append(('wayback_breaker', b.get('next_probe_in') or 60))
cc = max(deferral.host_cooldown('index.commoncrawl.org'), ratelimit.backoff_remaining('cc_index'))
if cc > 0: w.append(('cc_index_cooldown', cc))
print('OPEN %d %s' % (int(max(s for _, s in w)) + 1, ','.join(f'{n}:{s:.0f}s' for n, s in w)) if w else 'OK')
PYEOF
) || G="OPEN 300 gate_check_failed"
  set -- $G
  if [ "$1" = OPEN ]; then s=$2; [ "$s" -gt 3600 ] && s=3600
    log "$(date '+%FT%T%z') archive gate closed ($3): no chunk, sleeping ${s}s"
    sleep_hb "$s" archive_gate; continue; fi
  set -- $W
  n=$((n+1)); log "$(date '+%FT%T%z') chunk $n: $2 places ($3 due, $4 waiting) timeout=${CHUNK_TIMEOUT}s"
  # Per-chunk watchdog: kill hung councils.py after CHUNK_TIMEOUT (default 30m).
  timeout -k 30 "$CHUNK_TIMEOUT" $PY -u councils.py run --archive-queue --archive-docs 8 --places-file $CF > $OUT 2>&1
  rc=$?
  if [ $rc -eq 124 ] || [ $rc -eq 137 ]; then
    log "$(date '+%FT%T%z') chunk $n TIMEOUT after ${CHUNK_TIMEOUT}s (rc=$rc); continuing"
  fi
  if [ -f "$OUT" ]; then
    printf '%s\n' "----- chunk $n out begin -----" >&3
    cat "$OUT" >&3
    printf '%s\n' "----- chunk $n out end rc=$rc -----" >&3
  fi
  # Count a run against a place only if an archive fetch was really attempted (not breaker/cool-down deferrals).
  CNTMSG=$($PY - "$CF" "$OUT" "$CNT" <<'PYEOF'
import os, re, sys
cf, out, cnt = sys.argv[1:4]
ids = [l.strip() for l in open(cf) if l.strip()]
txt = open(out, errors='replace').read().splitlines() if os.path.exists(out) else []
counts = {}
for l in open(cnt):
    p = l.split('\t')
    if len(p) == 2: counts[p[0]] = int(p[1])
GATE = re.compile(r'breaker|cool|unavailable', re.I)
REAL = re.compile(r'\b(429|5\d\d|timeout|timed out|SSL|reset|error)\b', re.I)
hit = []
for pid in ids:
    fin = [l for l in txt if f'place {pid} ' in l and ' -> ' in l]
    if not fin: continue
    st = fin[-1].split(' -> ')[1].split()[0]
    reasons = [l.rsplit(' (', 1)[-1] for l in txt if f'{pid} archive deferred' in l]
    if st != 'deferred' or any(REAL.search(r) or not GATE.search(r) and 'deferred (cc_' not in r for r in reasons):
        counts[pid] = counts.get(pid, 0) + 1; hit.append(pid)
open(cnt + '.tmp', 'w').write(''.join(f'{k}\t{v}\n' for k, v in counts.items())); os.replace(cnt + '.tmp', cnt)
print(f'counted {len(hit)}/{len(ids)} place(s) against the 6-run cap (archive attempted)')
PYEOF
)
  log "$(date '+%FT%T%z') $CNTMSG"
  if grep -q "disk free .* GB <" $OUT 2>/dev/null || grep -q "disk hard write error" $OUT 2>/dev/null; then
    # Strengthened disk handling (2026-11-06):
    # - Never stop on one reading.
    # - Each probe uses df -P + statvfs + shutil on staging path (and /workspace), logs path+device.
    # - Minimum observe window DISK_CONFIRM_S (4 min): do not stop before that.
    # - Keep retrying up to DISK_RETRY_MAX_S (2h, was 15m) for recovery; continue as soon as min>=10.
    # - Stop only if still all-methods-low after the full window, or on hard write error.
    # Floor stays 10 GB.
    DISK_RETRY_MAX_S=${DISK_RETRY_MAX_S:-7200}
    DISK_CONFIRM_S=${DISK_CONFIRM_S:-240}
    log "$(date '+%FT%T%z') disk StopRun/write-error seen in chunk $n; retry (min_observe=${DISK_CONFIRM_S}s max=${DISK_RETRY_MAX_S}s floor=10GB)"
    _disk_start=$(date +%s)
    _disk_deadline=$((_disk_start + DISK_RETRY_MAX_S))
    _recovered=0
    while [ "$(date +%s)" -lt "$_disk_deadline" ]; do
      PROBE=$($PY - <<'PYPROBE'
import sys
sys.path.insert(0, "/workspace/world_law/pipeline/scrapers/ukie")
from common.util import disk_probe, format_disk_probe, MIN_FREE_GB, STAGE, STATE_DIR
parts = []
mins = []
for path in (str(STAGE), "/workspace", "/", "/tmp"):
    pr = disk_probe(path)
    parts.append(format_disk_probe(pr))
    if pr.get("min_gb") is not None:
        mins.append(pr["min_gb"])
write_err = "-"
try:
    t = STATE_DIR / ".disk_write_probe"
    t.write_bytes(b"ok"); t.unlink(missing_ok=True)
except OSError as e:
    write_err = str(e).replace("\n", " ")
overall_min = min(mins) if mins else None
ok = overall_min is not None and overall_min >= MIN_FREE_GB
print("PROBE_OK" if ok else "PROBE_LOW")
print("min=%.3f" % overall_min if overall_min is not None else "min=None")
print("write_err=" + write_err)
print(" || ".join(parts))
PYPROBE
) || PROBE="PROBE_LOW
min=None
write_err=probe_failed
probe_failed"
      _status=$(printf '%s\n' "$PROBE" | sed -n '1p')
      _minmax=$(printf '%s\n' "$PROBE" | sed -n '2p')
      _werr=$(printf '%s\n' "$PROBE" | sed -n '3p')
      _detail=$(printf '%s\n' "$PROBE" | sed -n '4p')
      _elapsed=$(( $(date +%s) - _disk_start ))
      log "$(date '+%FT%T%z') disk probe t=${_elapsed}s: status=$_status $_minmax $_werr | $_detail"
      case "$_werr" in
        write_err=-|write_err=) ;;
        write_err=*)
          log "$(date '+%FT%T%z') disk hard write error ($_werr); stopping"
          log DEFERRED_CHUNKED_STOPPED_DISK
          echo DEFERRED_CHUNKED_STOPPED_DISK; exit 2
          ;;
      esac
      if [ "$_status" = PROBE_OK ]; then
        log "$(date '+%FT%T%z') disk recovered at t=${_elapsed}s ($_minmax) >= 10 GB; continuing next chunk"
        _recovered=1
        break
      fi
      # Do not stop before minimum observe window (4 min)
      if [ "$_elapsed" -ge "$DISK_RETRY_MAX_S" ]; then
        break
      fi
      sleep_hb 60 disk_retry
    done
    if [ "$_recovered" = 1 ]; then
      continue
    fi
    _elapsed=$(( $(date +%s) - _disk_start ))
    # Final double recheck only if we observed at least DISK_CONFIRM_S of low
    if [ "$_elapsed" -lt "$DISK_CONFIRM_S" ]; then
      log "$(date '+%FT%T%z') disk low but observe window < ${DISK_CONFIRM_S}s; extending"
      sleep_hb $((DISK_CONFIRM_S - _elapsed)) disk_extend
    fi
    _final_low=1
    for _i in 1 2; do
      sleep_hb 60 disk_final_recheck
      PROBE2=$($PY - <<'PYPROBE'
import sys
sys.path.insert(0, "/workspace/world_law/pipeline/scrapers/ukie")
from common.util import disk_probe, format_disk_probe, MIN_FREE_GB, STAGE
pr = disk_probe(str(STAGE)); pw = disk_probe("/workspace")
mins = [x for x in (pr.get("min_gb"), pw.get("min_gb")) if x is not None]
ok = bool(mins) and min(mins) >= MIN_FREE_GB
print("PROBE_OK" if ok else "PROBE_LOW")
print("min=%.3f" % min(mins) if mins else "min=None")
print(format_disk_probe(pr) + " || " + format_disk_probe(pw))
PYPROBE
) || PROBE2="PROBE_LOW
min=None
failed"
      log "$(date '+%FT%T%z') disk final recheck $_i: $PROBE2"
      _s2=$(printf '%s\n' "$PROBE2" | sed -n '1p')
      if [ "$_s2" = PROBE_OK ]; then
        log "$(date '+%FT%T%z') disk recovered on final recheck; continuing"
        _final_low=0
        break
      fi
    done
    if [ "$_final_low" = 0 ]; then
      continue
    fi
    log "$(date '+%FT%T%z') disk still low after >=${DISK_CONFIRM_S}s observe + up to ${DISK_RETRY_MAX_S}s retry + 2 rechecks; stopping"
    log DEFERRED_CHUNKED_STOPPED_DISK
    echo DEFERRED_CHUNKED_STOPPED_DISK; exit 2
  fi
  if grep -q "peak RSS .* MB >" $OUT 2>/dev/null; then
    log "$(date '+%FT%T%z') RSS StopRun in chunk $n (rc=$rc): next chunk"
  elif [ $rc -ne 0 ] && [ $rc -ne 124 ] && [ $rc -ne 137 ]; then
    log "$(date '+%FT%T%z') chunk $n exited rc=$rc; continuing"; sleep_hb 30 chunk_err
  fi
done
