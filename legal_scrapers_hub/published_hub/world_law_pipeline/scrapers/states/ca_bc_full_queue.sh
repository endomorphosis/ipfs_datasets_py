#!/bin/bash
# 2026-10-29 06:07 PDT: CA-BC archive FULL (r4 test eyeballed + promoted 06:06 PDT; 00_/base dup ids merged in adapter). RAM-gated; resumes from _state/ca_bc_archive.done.tsv.
# ArchiveDeferred handling: if the run ends with deferred_left>0 (or rc!=0), requeue from checkpoint after 30 min, max 12 passes.
cd /workspace/world_law/pipeline/scrapers/states
. ./lane_ramgate.sh
L=/workspace/world_law/staging/states/_logs; PY=/workspace/world_law/pipeline/venv/bin/python
for i in $(seq 1 12); do
  if pgrep -f "run_full.py --source ca_bc_archive( |$)" >/dev/null; then echo "$(date) ca_bc_archive already running"; exit 0; fi
  echo "$(date) full ca_bc_archive pass $i"
  ramgate_run 130 $L/full_ca_bc_archive.log $PY -u run_full.py --source ca_bc_archive; rc=$?
  dl=$(grep -o 'deferred_left=[0-9]*' $L/full_ca_bc_archive.log | tail -1 | cut -d= -f2)
  echo "$(date) pass $i rc=$rc deferred_left=${dl:-?}"
  [ "$rc" -eq 0 ] && [ "${dl:-1}" = "0" ] && break
  sleep 1800
done
echo "$(date) CABC_FULL_END"
