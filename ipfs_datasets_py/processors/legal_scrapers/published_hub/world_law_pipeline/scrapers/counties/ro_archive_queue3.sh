#!/bin/sh
# 2026-10-24 ro_archive_queue3: archive retry (Wayback/CC) for the 17 Gorj (cjgorj.ro, Q190406) HCJ PDFs that failed live in ro_next12 (finished 13:51 PDT:
#  743 ok / 17 fail = 13x 404, 3x 403, 1x timeout). Config ro_cj_hcj_județul_gorj_archive.json = the 17 failed URLs + 5 corrected variants of
#  malformed site hrefs (stray '""/home/cjgorj/public_html/...' suffix on 222 + 116; missing 'Date site/' prefix on 166, 165, 3) = 22 URLs.
#  Runs alongside ro_archive_queue2.sh (Ialomița), separate config. Same pattern: idempotent rounds 30 min apart, disk guard 45 GB.
#  Test batch 2026-10-24 16:12 PDT: ro_archive_queue3_test.log (5 URLs).
cd /workspace/world_law/pipeline/scrapers/counties
PY=/workspace/world_law/pipeline/venv/bin/python
for round in 1 2 3 4 5 6 7 8; do
  for c in ro_cj_hcj_județul_gorj_archive.json; do
    df -P /workspace | awk 'NR==2{exit ($4/1048576<45)}' || { echo "STOP disk"; exit 0; }
    echo "== round $round $c $(date)"; timeout 3000 $PY -u archive_retry.py $c 45 2>&1 | grep --line-buffered -E '^(todo|OK|MISS|INVALID|SKIP_NOTPDF|written)'
  done
  sleep 1800
done
echo "done $(date)"
