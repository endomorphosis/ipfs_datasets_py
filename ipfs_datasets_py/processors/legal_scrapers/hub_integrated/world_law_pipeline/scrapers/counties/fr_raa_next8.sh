#!/bin/sh
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-10-26 04:10-04:50 PDT fr_raa_next8 (batch 8): Loire FR-42 (Q12569), Savoie FR-73 (Q12745) - substitutes; none of the 5 requested targets usable.
#   fr_raa_next8_build.py = fr_raa_next7_build.py unchanged; entries fr_raa_next8_entries.json. QIDs via Wikidata SPARQL (P300 + P31 Q6465).
#   Loire: webdelib-citoyens.loire.fr Webdelib+ arrêtés, monthly summary_orders &date=01..10-2026 (~1,890), openfile -> showFile.jsp?pdf= (query -> ~urlhash doc_id), robots 404, 3 s.
#   Savoie: savoie.fr Jalios 'Les arrêtés du Département' lists (sw_174380 01.01-18.05.2026 + sw_92129 + sw_176498, ~755 2026 acts), sw_ links 301 -> /upload/docs/application/pdf/, 3 s.
#   No source_url from these hosts in staging/* (rg 2026-10-26 ~04:45 PDT).
#   Test 2026-10-26 04:19-04:21 PDT (_logs/fr_raa_next8_test.log, fr_raa_cd_FR-{42,73}_test.log): 3/3 + 3/3 OK. Disk guard 45 GB.
#   Requested but blocked (probes 2026-10-26 ~04:15-04:40 PDT): Allier (delib.allier.fr 'site en cours de maintenance', lists 404),
#     Finistère (e-deliberations.finistere.fr Arcade JS SPA, no HTML links), Gironde (webdelibcitoyens.gironde.fr robots.txt 403 + POST search; no arrêtés listing on gironde.fr),
#     Vendée (publication-actes.vendee.fr WAF 'Request Rejected'), Haute-Savoie (delibs.com/cd74 Nuxt; PDFs under robots-disallowed /api/, 0 Wayback captures).
#   Other probes not taken: Orne (list stops 2023), Vienne/Haute-Loire/Eure/Rhône/PO/Indre-et-Loire (no 2026 HTML list; portailactes.touraine.fr TLS EOF),
#     Marne (opendata.spl-xdemat.fr robots Disallow: /), Cher webdelib (robots Disallow: /), Charente (webdelib robots Disallow: /), Aude (JS challenge),
#     Dordogne (search redirects to TLS-failing host), Val-de-Marne/Moselle/Drôme/Saône-et-Loire (TLS/challenge), Gers/Côtes-d'Armor (no acts list).
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/counties
PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python
df -P / | awk 'NR==2{exit ($4/1048576<45)}' || { echo "STOP disk $(date)"; exit 0; }
echo "$(date) start live"
$PY -u fr_raa_next8_build.py fr_raa_next8_entries.json
echo "$(date) done"
