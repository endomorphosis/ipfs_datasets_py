#!/bin/bash
# County resume chain after the 2026-11-01 restore: 1) Loire FR-42  2) Bavarian Kreisrecht top-up (build -> fetch per Landkreis)
# Robots recrawl step dropped: its input list (robots_recrawl_prep.py output) did not survive the restore.
cd /workspace/world_law/pipeline/scrapers/counties
export GUARD_MIN_MIB=10240
source ./county_chain_guard.sh
PY=/workspace/world_law/pipeline/venv/bin/python
L=/workspace/world_law/staging/counties/_logs
echo "$(date -u +%FT%TZ) chain start pid=$$" >> $L/county_chain_20261101r.log
guard_run loire_fr42 $PY pdf_list_fetch.py entries/fr_raa_cd_fr-42.json >> $L/loire_fr42.log 2>&1 || [ $? -ne 99 ] || exit 99
guard_run de_by_build $PY de_kreisrecht_topup_build.py >> $L/de_by_build.log 2>&1 || [ $? -ne 99 ] || exit 99
for f in entries/de_by_wd_Q*.json; do
  guard_run "de_by_$(basename $f .json)" $PY pdf_list_fetch.py "$f" >> $L/de_by_fetch.log 2>&1 || [ $? -ne 99 ] || exit 99
done
echo "$(date -u +%FT%TZ) chain done" >> $L/county_chain_20261101r.log
