#!/bin/bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-11-01: EU_IGNORE_ROBOTS re-queue, one job at a time (low memory). Resumable: re-run this script; each step dedups via done.sqlite.
export EU_IGNORE_ROBOTS=1 MALLOC_ARENA_MAX=2
cd ${WORLD_LAW_ROOT}/staging/eu; S=${WORLD_LAW_ROOT}/pipeline/scrapers/eu; ST=_state
ts(){ date '+%F %T %Z'; }
step(){ echo "$(ts) start $*"; nice -n 10 "$@"; echo "$(ts) end rc=$? $*"; }
step python3 $S/by_pravo.py pdftext >> _logs/by_pravo_pdftext.nohup.out 2>&1
for c in cy by ua ch; do
  step python3 $S/council_docs.py $c run --workers 2 --redo-file $ST/council_$c/robots_redo_20261101.txt >> _logs/council_${c}_robots.nohup.out 2>&1
done
step python3 $S/nl_gmb.py fetch --redo-robots >> _logs/nl_gmb_robots.nohup.out 2>&1
echo "$(ts) chain finished"
