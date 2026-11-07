#!/bin/sh
# 2026-10-26 18:10 PDT de_by16: Landkreis Rhön-Grabfeld (Q10465) ARCHIVE-ONLY. All 67 other Bavarian Landkreise already staged/processed; the 4 left
#  (Eichstätt Q10491, Rhön-Grabfeld Q10465, Würzburg Q10458, Landsberg Q10507) are robots-blocked live (re-checked 18:03 PDT: rhoen-grabfeld.de and
#  landkreis-eichstaett.de "Disallow: /*.pdf$", landkreis-wuerzburg.de "Disallow: /output/" and the Amtsblatt only links /output/download.php; Landsberg
#  kxp host Disallow: / and ARCHIVE-EXHAUSTED 2026-10-24). Rhön-Grabfeld picked: archive config never run, Wayback has ~1,339 PDF captures under /fileadmin/user_upload/LKR/.
#  Config de_by_kreisrecht_landkreis_rhön_grabfeld_archive.json = de_by13_cdx_cfg.py (de_by16_rhoen_grabfeld_cdx_entry.json, log _logs/de_by16_cdx_cfg.log, 295 kept)
#  + 68 extra Amtsblatt URLs from the 2026-10-23 120-URL config (backup de_by16_rhoen_grabfeld_archive_prev120.json), then filename/title must match law keywords
#  (dropped 50 forms/Merkblätter/Anträge, re-added Haushalt 2025): 314 URLs, 1 with a query string (getMedia.php -> doc_id gets ~URL-hash suffix in archive_retry).
#  Test: de_by16_test_rhoen_grabfeld_archive.json (3 URLs), log _logs/de_by16_test.log.
#  Chained: waits for Fürth pass 4 (36297), Aschaffenburg archive pass 1 (158680) and Bamberg archive pass 1 (de_by15_bamberg_archive_pass1.sh) so only one archive_retry runs at once.
cd /workspace/world_law/pipeline/scrapers/counties
PY=/workspace/world_law/pipeline/venv/bin/python
. /workspace/world_law/pipeline/scrapers/counties/county_chain_guard.sh   # disk guard 46080 MiB (2026-10-26 21:20)
echo "$(date) restart after 2026-10-26 20:10 disk-kill; PID waits removed (36297/158680 dead); chained by county_chain_20261026.sh"
for round in 1 2 3 4 5 6 7 8; do
  g; echo "== archive round $round $(date)"; timeout 3300 $PY -u archive_retry.py de_by_kreisrecht_landkreis_rhön_grabfeld_archive.json 50 2>&1 | grep --line-buffered -E '^(todo|OK|MISS|INVALID|SKIP_NOTPDF|written|STOP|Traceback|[A-Za-z]*Error)'
  [ $round -lt 8 ] && sleep 600
done
echo "$(date) done"
