#!/bin/sh
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-10-30 ~09:00 PDT: Würzburg (Q10458) archive pass 2 (same 549-URL config as de_by18.sh). Pass 1 (10-28 22:56 - 10-29 09:08 PDT, 10 rounds) ended rc=0: 47 staged, 502 deferred, 0 misses; rounds 9-10 staged 0 -> only 6 rounds here, LAST in chain (low yield).
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/counties
PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python
. ${WORLD_LAW_ROOT}/pipeline/scrapers/counties/county_chain_guard.sh   # disk guard GUARD_MIN_MIB (20480 since 2026-10-27 14:12 PDT)
for round in $(seq 1 6); do
  g; echo "== archive round $round $(date)"; timeout 3300 $PY -u archive_retry.py de_by_kreisrecht_landkreis_würzburg_archive.json 50 2>&1 | grep --line-buffered -E '^(todo|OK|MISS|INVALID|SKIP_NOTPDF|written|STOP|Traceback|[A-Za-z]*Error)'
  [ $round -lt 6 ] && sleep 600
done
echo "$(date) done"
