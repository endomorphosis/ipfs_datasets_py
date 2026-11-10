#!/bin/sh
# 2026-10-25 18:10-18:20 PDT fr_raa_next6 (batch 6): Creuse FR-23 (Q3353), Sarthe FR-72 (Q12740), Seine-et-Marne FR-77 (Q12753).
#   fr_raa_next6_build.py = fr_raa_next5_build.py unchanged; entries fr_raa_next6_entries.json. QIDs checked via Wikidata SPARQL (P300 + P31 Q6465).
#   Creuse: creuse.fr arrêtés + délibérations pages (SPIP, Crawl-delay 1 -> 3 s). Sarthe: arrêtés Drupal view ?page=N (3 s).
#   Seine-et-Marne: consultation-des-actes-administratifs ?page=N (Crawl-delay 10).
#   Test 2026-10-25 18:11-18:13 PDT (_logs/fr_raa_next6_test.log, fr_raa_cd_FR-{23,72,77}_test.log): 3/3 + 3/3 + 3/3 OK. Disk guard 45 GB.
#   Probed, not taken (2026-10-25 ~18:10 PDT): Ain (js-challenge), Alpes-de-Haute-Provence (418), Alsace CEA (TLS EOF), Cher (TLS EOF),
#     Territoire de Belfort (cert fail), Seine-Saint-Denis (/shield), Sarthe délibérations (/sites/default/files/documents/ robots-disallowed).
cd /workspace/world_law/pipeline/scrapers/counties
PY=/workspace/world_law/pipeline/venv/bin/python
df -P / | awk 'NR==2{exit ($4/1048576<45)}' || { echo "STOP disk $(date)"; exit 0; }
echo "$(date) start live"
$PY -u fr_raa_next6_build.py fr_raa_next6_entries.json
echo "$(date) done"
