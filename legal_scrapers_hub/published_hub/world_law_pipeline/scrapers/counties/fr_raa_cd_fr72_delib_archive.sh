#!/bin/sh
# 2026-10-28 10:45 PDT Sarthe FR-72 (Q12740) CD délibérations / relevés de décisions 2015-2026, ARCHIVE-ONLY: PDFs under /sites/default/files/documents/ are robots Disallow for *.
#  Index (allowed) https://www.sarthe.fr/departement-sarthe/services-en-ligne/actes-administratifs/deliberations-depuis-2015 read live 10:40 PDT: 215 PDFs (20 from 2026) -> fr_raa_cd_fr-72_delib_archive.json.
#  Sarthe arrêtés (allowed folder) were already done live in fr_raa_next6. Test: _logs/fr_raa_cd_FR-72_delib_archive_test.log. 6 rounds.
cd /workspace/world_law/pipeline/scrapers/counties
PY=/workspace/world_law/pipeline/venv/bin/python
. /workspace/world_law/pipeline/scrapers/counties/county_chain_guard.sh   # disk guard GUARD_MIN_MIB (20480 since 2026-10-27 14:12 PDT)
for round in $(seq 1 6); do
  g; echo "== archive round $round $(date)"; timeout 3300 $PY -u archive_retry.py fr_raa_cd_fr-72_delib_archive.json 50 2>&1 | grep --line-buffered -E '^(todo|OK|MISS|INVALID|SKIP_NOTPDF|written|STOP|Traceback|[A-Za-z]*Error)'
  [ $round -lt 6 ] && sleep 600
done
echo "$(date) done"
