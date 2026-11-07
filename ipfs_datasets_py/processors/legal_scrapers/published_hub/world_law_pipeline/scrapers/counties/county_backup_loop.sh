#!/bin/bash
# Hourly county-lane backup (2026-11-01): (a) tarball of scrapers/counties (code, entries, skip list; no PDFs)
# plus a staged doc_id/URL checkpoint and _reports, kept 48 deep in /workspace/world_law/backups/
# (b) upload scrapers/counties/ to HF endomorphosis/world_law_pipeline (model repo) IF a HF token is available
# (HF_TOKEN env or the standard ~/.cache/huggingface/token used by huggingface_hub); otherwise log and skip.
C=/workspace/world_law/pipeline/scrapers/counties; S=/workspace/world_law/staging/counties; B=/workspace/world_law/backups
LOG=$S/_logs/county_backup.log; PY=/workspace/world_law/pipeline/venv/bin/python
while true; do
  ts=$(date -u +%Y%m%dT%H%M%SZ); mkdir -p $B $S/_reports
  # checkpoint: doc_id + source_url of everything staged by this lane (still in staging) + fetch audit logs
  cat $S/*/*.jsonl 2>/dev/null | $PY -c "import sys,json
for l in sys.stdin:
  try: d=json.loads(l); print(json.dumps({'doc_id':d['doc_id'],'source_url':d['source_url'],'place_id':d['place_id']}))
  except Exception: pass" > $C/checkpoint_staged.jsonl
  cp -f $S/_state/done_*.jsonl $C/ 2>/dev/null
  tar czf $B/county_lane_$ts.tgz --exclude='*.pdf' --exclude='__pycache__' -C /workspace/world_law pipeline/scrapers/counties staging/counties/_reports 2>>$LOG \
    && echo "$(date -u +%FT%TZ) tar ok $B/county_lane_$ts.tgz $(du -h $B/county_lane_$ts.tgz|cut -f1)" >> $LOG
  ls -1t $B/county_lane_*.tgz | tail -n +49 | xargs -r rm -f
  if [ -n "$HF_TOKEN" ] || [ -s ~/.cache/huggingface/token ]; then
    $PY - >>$LOG 2>&1 <<'P'
from huggingface_hub import HfApi
HfApi().upload_folder(repo_id="endomorphosis/world_law_pipeline", repo_type="model",
    folder_path="/workspace/world_law/pipeline/scrapers/counties", path_in_repo="scrapers/counties",
    allow_patterns=["*.py","*.sh","*.json","*.jsonl","*.md"], ignore_patterns=["__pycache__/*","*.pdf"],
    commit_message="sync_code: county lane (scrapers/counties) backup")
print("hf upload ok")
P
  else echo "$(date -u +%FT%TZ) hf upload skipped: no HF token on box" >> $LOG; fi
  sleep 3600
done
