#!/bin/sh
# 2026-10-24 20:20 PDT fr_raa_archive_queue2: archive-only retry (Wayback/CC, never live) for Loire-Atlantique FR-44 (Q3068) monthly
#   'Recueil des arrêtés et décisions' 2026 (9 PDFs, janvier-septembre). Index page robots-allowed, PDFs under /upload/ = robots Disallow for * ->
#   archive copies only (source_policy archived_robots_disallowed). Config fr_raa_cd_fr-44_archive.json built by fr_raa_next2_build.py 17:36 PDT;
#   it was meant for fr_raa_next2.sh phase 3 but next2 never left its Oise/Meuse index loop (stopped 20:06 PDT), so it is queued here.
#   Tests: 16:27 PDT fr_raa_next2_test_archive_la.log and 20:06-20:24 PDT fr_raa_archive_queue2_test.log (3 URLs): CC index 'cooling down' and
#   box-wide Wayback slot congested -> no capture served yet, no errors. 8 rounds, 30 min apart, archive_retry 40 min (< timeout 3000), disk guard 45 GB.
cd /workspace/world_law/pipeline/scrapers/counties
PY=/workspace/world_law/pipeline/venv/bin/python
for round in 1 2 3 4 5 6 7 8; do
  for c in fr_raa_cd_fr-44_archive.json; do
    df -P / | awk 'NR==2{exit ($4/1048576<45)}' || { echo "STOP disk $(date)"; exit 0; }
    echo "== round $round $c $(date)"; timeout 3000 $PY -u archive_retry.py $c 40 2>&1 | grep --line-buffered -E '^(todo|OK|MISS|INVALID|SKIP_NOTPDF|written)'
  done
  sleep 1800
done
echo "done $(date)"
