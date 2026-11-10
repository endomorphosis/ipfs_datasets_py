#!/usr/bin/env bash
# Full (resumable) run of one national collector. Usage: run_full.sh CC collector.py
# Raw collector state lives in staging/national/_work/<CC>/ (ignored by uploader);
# emit_staged.py --loop converts it into SCHEMA.md staged files in staging/national/<CC>/.
# Collectors skip ids already present in _work/<CC>/<cc>/instruments, so re-running resumes.
set -u
CC="$1"; COLL="$2"
HERE=/workspace/world_law/pipeline/scrapers/national
ROOT=/workspace/world_law/staging/national/_work/$CC
LOG=/workspace/world_law/staging/national/_logs/full/$CC.log
mkdir -p "$ROOT"
export IPFS_DATASETS_LEGAL_CORPORA_ROOT="$ROOT" IPFS_DATASETS_LEGAL_COLLECTORS_ROOT="$HERE"
export HF_TOKEN_PATH=/dev/null HF_HUB_OFFLINE=1 HF_TOKEN= PYTHONUNBUFFERED=1
for attempt in 1 2 3; do
  echo "=== $(date '+%F %T %Z') attempt $attempt $COLL" >> "$LOG"
  ( cd "$ROOT" && /workspace/world_law/pipeline/venv/bin/python "$HERE/shared/$COLL" ) >> "$LOG" 2>&1
  rc=$?
  echo "=== $(date '+%F %T %Z') exit rc=$rc" >> "$LOG"
  [ $rc -eq 0 ] && break
  sleep 300
done
/workspace/world_law/pipeline/venv/bin/python "$HERE/emit_staged.py" "$CC" >> "$LOG" 2>&1
echo "=== $(date '+%F %T %Z') FINISHED" >> "$LOG"
