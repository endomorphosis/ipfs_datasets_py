#!/bin/sh
# 2026-10-24 fr_raa_next1: French conseil départemental RAA / actes, next départements after FR-05 + FR-36.
#   phase 1 live (robots RFC 9309): Val-d'Oise FR-95 (monthly RAA 2026), Lot FR-46 (arrêtés published online 2026).
#   phase 2 archive-only: Isère FR-38 RADI (isere.fr serves a JS cookie 'shield' challenge to every request -> not solved; CC/Wayback only):
#   build archive config from an archived copy of the index page (retried up to 6 x 30 min), then archive_retry rounds 30 min apart.
#   Test batches done 2026-10-24 06:17-06:20 PDT (Val-d'Oise 1 ok + 1 SKIP_SIZE >50 MB; Lot 3 ok). Disk guard 45 GB.
cd /workspace/world_law/pipeline/scrapers/counties
PY=/workspace/world_law/pipeline/venv/bin/python
echo "$(date) start live"
$PY -u fr_raa_next1_build.py fr_raa_next1_entries.json
echo "$(date) live done; archive phase (Isère)"
for i in 1 2 3 4 5 6; do
  [ -f fr_raa_cd_fr-38_archive.json ] && break
  df -P /workspace | awk 'NR==2{exit ($4/1048576<45)}' || { echo "STOP disk"; exit 0; }
  echo "== index try $i $(date)"; timeout 3000 $PY -u fr_raa_archive_index.py fr_raa_next1_entries.json 45 2>&1 | grep --line-buffered -vE '^(CC |wayback cdx)'
  [ -f fr_raa_cd_fr-38_archive.json ] || sleep 1800
done
[ -f fr_raa_cd_fr-38_archive.json ] || { echo "$(date) Isère: no archived index after 6 tries"; exit 0; }
for round in 1 2 3 4 5 6; do
  df -P /workspace | awk 'NR==2{exit ($4/1048576<45)}' || { echo "STOP disk"; exit 0; }
  echo "== archive round $round fr_raa_cd_fr-38_archive.json $(date)"; timeout 3000 $PY -u archive_retry.py fr_raa_cd_fr-38_archive.json 45 2>&1 | grep --line-buffered -E '^(todo|OK|MISS|INVALID|SKIP_NOTPDF|written)'
  sleep 1800
done
echo "$(date) done"
