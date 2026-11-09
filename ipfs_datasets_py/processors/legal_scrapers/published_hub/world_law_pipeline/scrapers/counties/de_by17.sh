#!/bin/sh
# 2026-10-28 10:45 PDT de_by17: Landkreis Eichstätt (Q10491) ARCHIVE-ONLY (Wayback/CC, never live). robots.txt (re-checked 10:10 PDT) Disallow: /*.pdf$, /fileadmin/Dateien/, /fileadmin/user_upload/.
#  Config de_by_kreisrecht_landkreis_eichstätt_archive.json = de_by13_cdx_cfg.py (de_by17_eichstaett_cdx_entry.json, log _logs/de_by17_cdx_cfg.log): 4,611 Wayback PDF rows -> 1,320 kept -> 1,305 after dropping Merkblätter.
#  Mostly Amtsblatt issues 2000-2026 (titles 'Amtsblatt für den Landkreis und die Stadt Eichstätt Nr. N/YYYY') + Satzungen/Verordnungen first, then newest year first. 0 query-string URLs.
#  Old 3-URL live config de_by_kreisrecht_landkreis_eichstätt.json (2026-10-21, robots-blocked) left untouched.
#  Test 10:10-10:32 PDT (de_by17_test.log, de_by17_test_eichstaett_archive.json): 1 staged (Wayback, text PDF) / 0 miss / 2 deferred (archive throttling). 12 rounds.
cd /workspace/world_law/pipeline/scrapers/counties
PY=/workspace/world_law/pipeline/venv/bin/python
. /workspace/world_law/pipeline/scrapers/counties/county_chain_guard.sh   # disk guard GUARD_MIN_MIB (20480 since 2026-10-27 14:12 PDT)
for round in $(seq 1 12); do
  g; echo "== archive round $round $(date)"; timeout 3300 $PY -u archive_retry.py de_by_kreisrecht_landkreis_eichstätt_archive.json 50 2>&1 | grep --line-buffered -E '^(todo|OK|MISS|INVALID|SKIP_NOTPDF|written|STOP|Traceback|[A-Za-z]*Error)'
  [ $round -lt 12 ] && sleep 600
done
echo "$(date) done"
