#!/bin/sh
# 2026-10-24 ro_archive_queue2: second set of 8 archive rounds for the 137 Ialomița (cjialomita.ro) HCJ PDFs still deferred after ro_archive_queue.sh
# (round 8 ended 10:46 PDT: staged 59, miss 0, still_deferred 137 = Wayback/CC ArchiveDeferred, not hard misses). Same pattern; idempotent, 30 min apart, disk guard 45 GB.
cd /workspace/world_law/pipeline/scrapers/counties
PY=/workspace/world_law/pipeline/venv/bin/python
for round in 1 2 3 4 5 6 7 8; do
  for c in ro_cj_hcj_județul_ialomița_archive.json; do
    df -P /workspace | awk 'NR==2{exit ($4/1048576<45)}' || { echo "STOP disk"; exit 0; }
    echo "== round $round $c $(date)"; timeout 3000 $PY -u archive_retry.py $c 45 2>&1 | grep --line-buffered -E '^(todo|OK|MISS|INVALID|SKIP_NOTPDF|written)'
  done
  sleep 1800
done
echo "done $(date)"
