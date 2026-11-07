#!/bin/bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-10-25 19:20: archive-only US states (Benjamin): SC, ID, MI via the shared Wayback module (breaker respected by cdx_list /
# ArchiveFetcher). OH (robots Disallow: /), TN (Lexis only), OK (oscn query URLs, no statute-only prefix), AL (JS app) not queued.
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/states
. ./lane_ramgate.sh
L=${WORLD_LAW_ROOT}/staging/states/_logs; PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python
while pgrep -f "us_az_arch_queue.sh" >/dev/null; do sleep 60; done
ramgate_run 60 $L/cdx_sc_code.out $PY -u cdx_list.py data/archive/sc_code.txt "www.scstatehouse.gov/code/" t; echo "$(date) cdx SC rc=$?"
ramgate_run 60 $L/cdx_id_code.out $PY -u cdx_list.py data/archive/id_code.txt "legislature.idaho.gov/statutesrules/idstat/" $(seq 1 74 | sed 's|^|Title|; s|$|/|'); echo "$(date) cdx ID rc=$?"
ramgate_run 60 $L/cdx_mi_mcl.out $PY -u cdx_list.py data/archive/mi_mcl.txt "www.legislature.mi.gov/Laws/MCL" ""; echo "$(date) cdx MI rc=$?"
for k in us_sc_code_archive us_id_code_archive us_mi_mcl_archive; do
  f=data/archive/$(echo $k | sed 's/^us_//; s/_archive$//').txt
  [ -s "$f" ] || { echo "$(date) skip $k (no $f)"; continue; }
  echo "$(date) test $k"; ramgate_run 120 $L/test_$k.out $PY -u run_full.py --source $k --test 20; echo "$(date) rc=$?"
done
echo "$(date) USARCH_END"
