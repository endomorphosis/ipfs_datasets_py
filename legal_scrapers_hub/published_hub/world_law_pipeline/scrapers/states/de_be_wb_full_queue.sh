#!/bin/bash
# 2026-10-28 12:20 PDT: DE-BE (Wayback, retired gesetze.berlin.de jportal) FULL run. r3 test (9 rows / 6 files) eyeballed clean
#   and promoted via promote_review.py be_juris-wb. RAM-gated; resumes from _work/de_be_wb (done.tsv, deferred.tsv, cdx_parts).
# 2026-10-28 15:15 PDT: stopped + restarted after norm_root fix (bak_20261028_1515_root): Gesamtausgabe via pAnlage-G6 unit
#   was staged a 2nd time under its unit id; dup row removed from 20261028T203611Z (orig in _review/DE/_superseded).
# 2026-10-28 18:15 PDT: stopped + restarted after jlink-variant/footnote heading_only fix (bak_20261028_1815_jlink); RiGBE2011pG7
#   dropped from 20261029T011318Z (orig in _review/DE/_superseded). 2 boilerplate rows already on hub (see review_holds).
# ArchiveDeferred handling: if a pass ends with deferred queue left > 0 (or rc != 0), requeue after 30 min, max 12 passes.
cd /workspace/world_law/pipeline/scrapers/states
. ./lane_ramgate.sh
export ARCHIVE_LANE=states STATES_MAX_DEFERS=10000
L=/workspace/world_law/staging/states/_logs; PY=/workspace/world_law/pipeline/venv/bin/python
for i in $(seq 1 12); do
  if pgrep -f "arch_states.py de_be_wb" >/dev/null; then echo "$(date) de_be_wb already running"; exit 0; fi
  echo "=== $(date) full de_be_wb pass $i" >> $L/full_de_be_wb.log
  echo "$(date) full de_be_wb pass $i"
  ramgate_run 150 $L/full_de_be_wb.log $PY -u arch_states.py de_be_wb --flush-secs 3600; rc=$?
  dl=$(grep -o 'deferred queue left: [0-9]*' $L/full_de_be_wb.log | tail -1 | grep -o '[0-9]*$')
  echo "$(date) pass $i rc=$rc deferred_left=${dl:-?}"
  [ "$rc" -eq 0 ] && [ "${dl:-1}" = "0" ] && break
  sleep 1800
done
echo "$(date) DEBE_FULL_END"
