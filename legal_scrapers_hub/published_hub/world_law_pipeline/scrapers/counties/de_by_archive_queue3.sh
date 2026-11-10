#!/bin/sh
# 2026-10-24 (by12 worker): archive-only queue for Rottal-Inn deferred URLs (de_by11 archive phase: 252 PDFs, 5 staged, 246 still deferred;
#   rottal-inn.de robots.txt 403 -> archive-only). Modeled on de_by_archive_queue2.sh: idempotent rounds (archive_retry skips already staged
#   source_urls; query URLs get URL-hash doc_id suffix), 30 min apart, disk guard 45 GB.
cd /workspace/world_law/pipeline/scrapers/counties
PY=/workspace/world_law/pipeline/venv/bin/python
for round in 1 2 3 4 5 6 7 8; do
  for c in de_by_kreisrecht_landkreis_rottal_inn_archive.json; do
    df -P /workspace | awk 'NR==2{exit ($4/1048576<45)}' || { echo "STOP disk"; exit 0; }
    echo "== round $round $c $(date)"; timeout 3000 $PY -u archive_retry.py $c 45 2>&1 | grep --line-buffered -E '^(todo|OK|MISS|INVALID|SKIP_NOTPDF|written)'
  done
  sleep 1800
done
echo "done $(date)"
