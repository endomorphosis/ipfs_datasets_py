#!/bin/sh
# 2026-10-30 ~09:00 PDT: Rhön-Grabfeld (Q10465) archive pass 3 (same setup as de_by16.sh). Pass 2 (10-29 23:10 - 10-30 07:21 PDT) ended rc=0: 122 staged, 192 still deferred, 0 misses; +5..12 per round to the end.
cd /workspace/world_law/pipeline/scrapers/counties
PY=/workspace/world_law/pipeline/venv/bin/python
. /workspace/world_law/pipeline/scrapers/counties/county_chain_guard.sh   # disk guard GUARD_MIN_MIB (20480 since 2026-10-27 14:12 PDT)
for round in $(seq 1 8); do
  g; echo "== archive round $round $(date)"; timeout 3300 $PY -u archive_retry.py de_by_kreisrecht_landkreis_rhön_grabfeld_archive.json 50 2>&1 | grep --line-buffered -E '^(todo|OK|MISS|INVALID|SKIP_NOTPDF|written|STOP|Traceback|[A-Za-z]*Error)'
  [ $round -lt 8 ] && sleep 600
done
echo "$(date) done"
