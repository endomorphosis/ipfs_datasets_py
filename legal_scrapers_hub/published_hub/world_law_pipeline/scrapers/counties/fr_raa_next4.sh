#!/bin/sh
# 2026-10-25 06:15 PDT fr_raa_next4: next French conseil départemental actes collections after fr_raa_next3 (Pas-de-Calais FR-62 done 03:10, 1729/1).
#   Entries (fr_raa_next4_entries.json, builder fr_raa_next4_build.py = next2 builder + per-entry crawl_delay / robots Crawl-Delay, generic link-text fix):
#     Nièvre FR-58 (Q12657) nievre.fr/kiosque/arretes/ - individual arrêtés/décisions, D-2026-* / _ART_2026* only (~600), ?-query URLs -> URL-hash doc_id suffix
#     Corrèze FR-19 (Q3326) correze.fr/la-publication-des-actes - 2026 CP/CD délibérations + arrêtés compilations (~45)
#     Loiret FR-45 (Q12574) loiret.fr/arretes-administratifs - individual arrêtés 2026, 20/page, ?page=N (stop after 2 pages w/o 2026 PDFs)
#   robots.txt (RFC 9309) checked 2026-10-25 06:05 PDT: all used paths allowed, no Crawl-Delay (3 s used). No source_url from these hosts in staging/* or processed/*.
#   Blocked/not taken (probes 06:05 PDT): Oise FR-60, Meuse FR-55, Loire-Atlantique FR-44 (see _reports); somme/cotedor/landes/var/charente-maritime 403,
#     tarn 418, calvados/vosges/lozere/haute-saone/tarn-et-garonne/seinemaritime TLS EOF, lenord.fr timeout; Morbihan RAA ends 2022.
#   Test 2026-10-25 06:08-06:10 PDT (fr_raa_next4_test.log, fr_raa_cd_FR-{58,19,45}_test.log): 6/6 OK (Loiret 1 scanned -> raw PDF). Disk guard 45 GB.
cd /workspace/world_law/pipeline/scrapers/counties
PY=/workspace/world_law/pipeline/venv/bin/python
df -P / | awk 'NR==2{exit ($4/1048576<45)}' || { echo "STOP disk $(date)"; exit 0; }
echo "$(date) start live"
$PY -u fr_raa_next4_build.py fr_raa_next4_entries.json
echo "$(date) done"
