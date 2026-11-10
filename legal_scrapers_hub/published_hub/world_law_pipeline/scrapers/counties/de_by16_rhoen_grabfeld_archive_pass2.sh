#!/bin/sh
# 2026-10-28 10:45 PDT: Rhön-Grabfeld (Q10465) archive pass 2 (same setup as de_by16.sh). Pass 1 (de_by16.sh, 10-28 00:28 - 08:26 PDT) ended rc=0: 59 staged, 255 still deferred, 0 misses.
cd /workspace/world_law/pipeline/scrapers/counties
PY=/workspace/world_law/pipeline/venv/bin/python
. /workspace/world_law/pipeline/scrapers/counties/county_chain_guard.sh   # disk guard GUARD_MIN_MIB (20480 since 2026-10-27 14:12 PDT)
for round in $(seq 1 8); do
  g; echo "== archive round $round $(date)"; timeout 3300 $PY -u archive_retry.py de_by_kreisrecht_landkreis_rhön_grabfeld_archive.json 50 2>&1 | grep --line-buffered -E '^(todo|OK|MISS|INVALID|SKIP_NOTPDF|written|STOP|Traceback|[A-Za-z]*Error)'
  [ $round -lt 8 ] && sleep 600
done
echo "$(date) done"
