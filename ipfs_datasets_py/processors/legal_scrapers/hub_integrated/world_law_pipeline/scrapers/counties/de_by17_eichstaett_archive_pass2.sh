#!/bin/sh
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-10-30 ~09:00 PDT: Eichstätt (Q10491) archive pass 2 (same config as de_by17.sh, 1,305 CDX URLs). Pass 1 (10-28 10:55-22:56 PDT, 12 rounds) ended rc=0: 94 staged, 1,211 still deferred, 0 misses; still +5..20 per round at the end.
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/counties
PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python
. ${WORLD_LAW_ROOT}/pipeline/scrapers/counties/county_chain_guard.sh   # disk guard GUARD_MIN_MIB (20480 since 2026-10-27 14:12 PDT)
for round in $(seq 1 10); do
  g; echo "== archive round $round $(date)"; timeout 3300 $PY -u archive_retry.py de_by_kreisrecht_landkreis_eichstätt_archive.json 50 2>&1 | grep --line-buffered -E '^(todo|OK|MISS|INVALID|SKIP_NOTPDF|written|STOP|Traceback|[A-Za-z]*Error)'
  [ $round -lt 10 ] && sleep 600
done
echo "$(date) done"
