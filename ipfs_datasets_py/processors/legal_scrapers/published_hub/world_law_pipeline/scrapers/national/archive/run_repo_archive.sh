#!/usr/bin/env bash
# Run repo collectors (https-Wayback patched copies) under an archive work root, one at a time,
# then emit with an 'archiverepo' batch suffix. Usage: run_repo_archive.sh "EG:collect_eg.py IR:collect_ir.py"
set -u
HERE=/workspace/world_law/pipeline/scrapers/national
for pair in $1; do
  CC=${pair%%:*}; COLL=${pair#*:}
  ROOT=/workspace/world_law/staging/national/_archive_work/${CC}_repo
  LOG=/workspace/world_law/staging/national/_logs/archive/repo_$CC.log
  mkdir -p "$ROOT"
  export IPFS_DATASETS_LEGAL_CORPORA_ROOT="$ROOT" IPFS_DATASETS_LEGAL_COLLECTORS_ROOT="$HERE"
  export HF_TOKEN_PATH=/dev/null HF_HUB_OFFLINE=1 HF_TOKEN= PYTHONUNBUFFERED=1
  export MAX_NEW=${MAX_NEW:-100000} MAX_SECONDS=${MAX_SECONDS:-86400} CDX_LIMIT=${CDX_LIMIT:-20000} OCR_PAGES=${OCR_PAGES:-15}
  echo "=== $(date '+%F %T %Z') start $COLL" >> "$LOG"
  ( cd "$ROOT" && nice -n 10 /workspace/world_law/pipeline/venv/bin/python "$HERE/shared/$COLL" ) >> "$LOG" 2>&1 &
  CP=$!
  while kill -0 $CP 2>/dev/null; do sleep 600; /workspace/world_law/pipeline/venv/bin/python "$HERE/archive/emit_repo_archive.py" "$CC" >> "$LOG" 2>&1; done
  wait $CP; echo "=== $(date '+%F %T %Z') exit rc=$?" >> "$LOG"
  /workspace/world_law/pipeline/venv/bin/python "$HERE/archive/emit_repo_archive.py" "$CC" >> "$LOG" 2>&1
done
echo "=== $(date '+%F %T %Z') FINISHED" >> /workspace/world_law/staging/national/_logs/archive/repo_queue.log
