#!/bin/bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-10-28 06:30 PDT: CA-QC archive FULL (r3 test eyeballed + promoted). RAM-gated; resumes from _state/ca_qc_archive.done.tsv.
# ArchiveDeferred handling: if the run ends with deferred_left>0 (or rc!=0), requeue from checkpoint after 30 min, max 12 passes.
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/states
. ./lane_ramgate.sh
L=${WORLD_LAW_ROOT}/staging/states/_logs; PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python
for i in $(seq 1 12); do
  if pgrep -f "run_full.py --source ca_qc_archive( |$)" >/dev/null; then echo "$(date) ca_qc_archive already running"; exit 0; fi
  echo "$(date) full ca_qc_archive pass $i"
  ramgate_run 130 $L/full_ca_qc_archive.log $PY -u run_full.py --source ca_qc_archive; rc=$?
  dl=$(grep -o 'deferred_left=[0-9]*' $L/full_ca_qc_archive.log | tail -1 | cut -d= -f2)
  echo "$(date) pass $i rc=$rc deferred_left=${dl:-?}"
  [ "$rc" -eq 0 ] && [ "${dl:-1}" = "0" ] && break
  sleep 1800
done
echo "$(date) CAQC_FULL_END"
