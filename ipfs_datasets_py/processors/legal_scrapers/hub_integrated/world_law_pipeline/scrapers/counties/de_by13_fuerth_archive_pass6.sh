#!/bin/sh
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-10-28 10:45 PDT: Fürth (Q10455) archive pass 6 (same setup as pass 5). Pass 5 (2026-10-27 14:12 - 10-28 00:28 PDT) ended rc=0: 216 staged, 442 still deferred (ArchiveDeferred, retryable), 0 misses.
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/counties
PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python
. ${WORLD_LAW_ROOT}/pipeline/scrapers/counties/county_chain_guard.sh   # disk guard GUARD_MIN_MIB (20480 since 2026-10-27 14:12 PDT)
for round in $(seq 1 8); do
  g; echo "== archive round $round $(date)"; timeout 3300 $PY -u archive_retry.py de_by_kreisrecht_landkreis_fürth_archive.json 50 2>&1 | grep --line-buffered -E '^(todo|OK|MISS|INVALID|SKIP_NOTPDF|written|STOP|Traceback|[A-Za-z]*Error)'
  [ $round -lt 8 ] && sleep 600
done
echo "$(date) done"
