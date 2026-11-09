#!/usr/bin/env bash
N=/workspace/world_law/pipeline/scrapers/national; ROOT=/workspace/world_law/staging/national/_work/DK
LOG=/workspace/world_law/staging/national/_logs/full/DK.log
export IPFS_DATASETS_LEGAL_CORPORA_ROOT="$ROOT" IPFS_DATASETS_LEGAL_COLLECTORS_ROOT="$N" HF_TOKEN_PATH=/dev/null HF_HUB_OFFLINE=1 HF_TOKEN= PYTHONUNBUFFERED=1
export PYTHONPATH=$N/rlhook ARCHIVE_LANE=national
echo "=== $(date '+%F %T %Z') relaunch dk/collect_dk_fast_skip.py (historic metadata-only fast skip, 2 workers)" >> "$LOG"
( cd "$ROOT" && /workspace/world_law/pipeline/venv/bin/python "$N/dk/collect_dk_fast_skip.py" ) >> "$LOG" 2>&1
rc=$?; echo "=== $(date '+%F %T %Z') exit rc=$rc" >> "$LOG"
/workspace/world_law/pipeline/venv/bin/python "$N/emit_staged.py" DK >> "$LOG" 2>&1
echo "=== $(date '+%F %T %Z') FINISHED" >> "$LOG"
