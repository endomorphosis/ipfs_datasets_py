#!/bin/sh
# 2026-10-26 21:20 PDT: Fürth (Q10455) archive pass 5 (copy of pass4 setup). Pass 4 (14:20-20:10, killed by disk guard) staged 103->232, 529 still deferred.
#  (pass 3 note: 04:10-13:39 staged 62->103, 555 deferred, 0 misses.)
#  All 555 are ArchiveDeferred (429/5xx/timeout/breaker cool-downs: box-wide Wayback breaker has opened 195x) -> retryable, not misses.
#  Archive copies only (landkreis-fuerth.de robots.txt = Cloudflare 403, never live). Longer rounds (50 min) / shorter gaps (10 min) than pass 3.
cd /workspace/world_law/pipeline/scrapers/counties
PY=/workspace/world_law/pipeline/venv/bin/python
. /workspace/world_law/pipeline/scrapers/counties/county_chain_guard.sh   # disk guard 46080 MiB (2026-10-26 21:20)
for round in 1 2 3 4 5 6 7 8 9 10; do
  g; echo "== archive round $round $(date)"; timeout 3300 $PY -u archive_retry.py de_by_kreisrecht_landkreis_fürth_archive.json 50 2>&1 | grep --line-buffered -E '^(todo|OK|MISS|INVALID|SKIP_NOTPDF|written|STOP|Traceback|[A-Za-z]*Error)'
  [ $round -lt 10 ] && sleep 600
done
echo "$(date) done"
