#!/bin/sh
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-10-25 21:40-22:20 PDT fr_raa_next7 (batch 7): Alpes-Maritimes FR-06 (Q3139), Jura FR-39 (Q3120), Yvelines FR-78 (Q12820).
#   fr_raa_next7_build.py = fr_raa_next6_build.py unchanged; entries fr_raa_next7_entries.json. QIDs checked via Wikidata SPARQL (P300 + P31 Q6465).
#   Alpes-Maritimes: departement06.fr/les-arretes single Drupal page (~930 2026 arrêtés, older-year file names excluded), 3 s.
#   Jura: jura.fr 'Arrêtés départementaux - <mois> 2026' monthly WordPress pages janvier..octobre (~1,300 ARR_2026_*; ARR_2025_* excluded), 3 s.
#   Yvelines: yvelines.fr bulletins officiels 2026 + arrêtés AD 2026-* (~40), 3 s. No Crawl-delay on any host; robots allow all used paths.
#   No source_url from these hosts in staging/* or processed/* (rg 2026-10-25 ~22:05 PDT).
#   Test 2026-10-25 22:13-22:15 PDT (_logs/fr_raa_next7_test.log, fr_raa_cd_FR-{06,39,78}_test.log): 3/3 + 3/3 + 3/3 OK. Disk guard 45 GB.
#   Probed, not taken (2026-10-25 ~21:45-22:05 PDT): Yonne + Mayenne actes-administratifs.*.fr and Deux-Sèvres portailarrete (TLS unexpected EOF),
#     Aveyron (JS/cookie redirect challenge), Ardèche (arcade.ardeche.fr JS SPA), Manche (tous-les-actes stops 2023), Hautes-Pyrénées (wp-file-download AJAX, no PDF links),
#     Loir-et-Cher (CD RAA page 404), Puy-de-Dôme/www.ha-py.fr/eure-et-loir/alpes-maritimes.fr/haute-corse robots unreachable.
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/counties
PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python
df -P / | awk 'NR==2{exit ($4/1048576<45)}' || { echo "STOP disk $(date)"; exit 0; }
echo "$(date) start live"
$PY -u fr_raa_next7_build.py fr_raa_next7_entries.json
echo "$(date) done"
