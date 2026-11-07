#!/bin/sh
# 2026-10-24 fr_raa_next2: French conseil départemental actes / RAA, next départements after fr_raa_next1 (FR-46 Lot done; FR-38 Isère blocked: JS shield,
#   no archived index after 6 tries; FR-95 Val-d'Oise archive-exhausted 1/8). Already covered: FR-05, FR-36, FR-38(blocked), FR-46, FR-49, FR-76, FR-94 (préfecture), FR-95.
#   phase 1 live (robots RFC 9309, fr_raa_next2_build.py):
#     Ille-et-Vilaine FR-35 (ille-et-vilaine.fr/arretes, individual arrêtés 2026, ~13/page, ?page=N up to 130, stop after 3 pages without 2026 PDFs)
#     Loire-Atlantique FR-44 (monthly recueils 2026; index allowed, PDFs under robots-disallowed /upload/ -> fr_raa_cd_fr-44_archive.json, archive copies only)
#   phase 2 archive-only index (fr_raa_archive_index.py, up to 6 tries x 30 min): Oise FR-60 (Cloudflare 403), Meuse FR-55 (anti-DDoS 418) -> never fetched live
#   phase 3: archive_retry rounds (6 x, 30 min apart) over every fr_raa_cd_fr-{44,60,55}_archive.json that exists.
#   Not taken (2026-10-24 probes): Val-de-Marne CD (TLS reset), Hauts-de-Seine (Akamai 403), Essonne/Aube/Doubs/Vaucluse/Ariège/Meurthe-et-Moselle (418),
#     Pyrénées-Atlantiques publication-actes.le64.fr ('Attack detected' 403), Gard (robots Disallow: /), Bouches-du-Rhône (no RAA after 2023),
#     Pas-de-Calais (download/file?key= list, mixed years, 80 pages - later).
#   Test batches 2026-10-24 16:15-16:40 PDT: fr_raa_next2_test.log (FR-35 3 ok / 0 fail; FR-44 3 archive URLs), fr_raa_next2_test_archive_la.log,
#     fr_raa_next2_archive_index_test.log. Disk guard 45 GB.
cd /workspace/world_law/pipeline/scrapers/counties
PY=/workspace/world_law/pipeline/venv/bin/python
echo "$(date) start live"
$PY -u fr_raa_next2_build.py fr_raa_next2_entries.json
echo "$(date) live done; archive index phase (Oise, Meuse)"
for i in 1 2 3 4 5 6; do
  [ -f fr_raa_cd_fr-60_archive.json ] && [ -f fr_raa_cd_fr-55_archive.json ] && break
  df -P /workspace | awk 'NR==2{exit ($4/1048576<45)}' || { echo "STOP disk"; exit 0; }
  echo "== index try $i $(date)"; timeout 3000 $PY -u fr_raa_archive_index.py fr_raa_next2_entries.json 45 2>&1 | grep --line-buffered -vE '^(CC |wayback cdx|cc_index)'
  [ -f fr_raa_cd_fr-60_archive.json ] && [ -f fr_raa_cd_fr-55_archive.json ] || sleep 1800
done
for round in 1 2 3 4 5 6; do
  for c in fr_raa_cd_fr-44_archive.json fr_raa_cd_fr-60_archive.json fr_raa_cd_fr-55_archive.json; do
    [ -f $c ] || continue
    df -P /workspace | awk 'NR==2{exit ($4/1048576<45)}' || { echo "STOP disk"; exit 0; }
    echo "== archive round $round $c $(date)"; timeout 3000 $PY -u archive_retry.py $c 45 2>&1 | grep --line-buffered -E '^(todo|OK|MISS|INVALID|SKIP_NOTPDF|written)'
  done
  sleep 1800
done
echo "$(date) done"
