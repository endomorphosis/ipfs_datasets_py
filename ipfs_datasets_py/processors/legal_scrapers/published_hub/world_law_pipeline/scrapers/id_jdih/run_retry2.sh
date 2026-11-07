#!/bin/bash
# Retry remaining JDIH places one at a time with a hard 2h wall clock each (retry1 hung on reads).
cd /workspace/world_law/pipeline/scrapers/id_jdih
LOG=/workspace/world_law/staging/id_jdih/_logs/retry2.log
for p in wd:Q10377 wd:Q10615 wd:Q11013 wd:Q27458; do
  grep -q "\"$p\"" /workspace/world_law/staging/id_jdih/_state/done_retry1.jsonl && continue
  IDJ_MAXPAGES=300 PDF_TIMEOUT=120 timeout -k 60 7200 /workspace/world_law/pipeline/venv/bin/python -W ignore jdih_crawl.py --places $p --workers 1 --done /workspace/world_law/staging/id_jdih/_state/done_retry1.jsonl >>$LOG 2>&1 || echo "$(date -u +%FT%TZ) $p timeout/fail rc=$?" >>$LOG
done
echo "$(date -u +%FT%TZ) FINISHED" >>$LOG
