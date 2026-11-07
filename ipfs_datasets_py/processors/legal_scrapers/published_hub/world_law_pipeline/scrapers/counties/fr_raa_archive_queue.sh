#!/bin/sh
# 2026-10-24 fr_raa_next1: archive-only rounds for Val-d'Oise FR-95 RAA 2026 (valdoise.fr live downloads now redirect to a JS '/shield' challenge;
#   not solved). Index was read live (robots-allowed) at 06:20 PDT; 1 of 8 staged live (Janvier). Idempotent rounds 30 min apart, disk guard 45 GB.
cd /workspace/world_law/pipeline/scrapers/counties
PY=/workspace/world_law/pipeline/venv/bin/python
for round in 1 2 3 4 5 6; do
  for c in fr_raa_cd_fr-95_archive.json; do
    df -P /workspace | awk 'NR==2{exit ($4/1048576<45)}' || { echo "STOP disk"; exit 0; }
    echo "== round $round $c $(date)"; timeout 3000 $PY -u archive_retry.py $c 45 2>&1 | grep --line-buffered -E '^(todo|OK|MISS|INVALID|SKIP_NOTPDF|SKIP_SIZE|written)'
  done
  sleep 1800
done
echo "done $(date)"
