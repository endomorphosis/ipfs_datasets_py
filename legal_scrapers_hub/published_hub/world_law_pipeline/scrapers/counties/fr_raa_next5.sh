#!/bin/sh
# 2026-10-25 08:47-09:00 PDT fr_raa_next5 (batch 5): Aisne, Hérault, Lot-et-Garonne, Cantal, Haute-Vienne, Haute-Garonne evaluated.
#   Live (fr_raa_next5_build.py = next4 builder + link_re / href_sub / year_re / extra_urls, entries fr_raa_next5_entries.json):
#     Cantal FR-15 (Q3259) cantal.fr/le-conseil-departemental/arretes-reglementaires/ (?acte_page=N, 20/page) - robots 'Disallow:' empty, no Crawl-Delay (3 s)
#     Haute-Vienne FR-87 (Q12808) arretes.haute-vienne.fr Webdelib+ monthly summaries 2026 -> showFile.jsp?pdf=<token> (query string -> ~urlhash8 doc_id); robots 404 (allow), Crawl-delay 10 (www) honoured
#   Test 2026-10-25 (fr_raa_next5_test2.log, fr_raa_cd_FR-{15,87}_test.log): 6/6 + 6/6 OK. Disk guard 45 GB.
#   Not taken: Aisne (deliberations.aisne.fr robots.txt TLS EOF), Hérault (actes-administratifs.herault.fr robots.txt TLS EOF),
#     Lot-et-Garonne (live page has only 3 2026 PVs, no 2026 délibérations/arrêtés), Haute-Garonne (robots Disallow: / -> archive index test only).
cd /workspace/world_law/pipeline/scrapers/counties
PY=/workspace/world_law/pipeline/venv/bin/python
df -P / | awk 'NR==2{exit ($4/1048576<45)}' || { echo "STOP disk $(date)"; exit 0; }
echo "$(date) start live"
$PY -u fr_raa_next5_build.py fr_raa_next5_entries.json
echo "$(date) done"
