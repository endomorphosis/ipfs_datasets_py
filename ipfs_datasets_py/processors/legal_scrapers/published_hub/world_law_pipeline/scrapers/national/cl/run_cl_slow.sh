#!/usr/bin/env bash
# single attempt (no retry loop), then emit + FINISHED marker
N=/workspace/world_law/pipeline/scrapers/national; ROOT=/workspace/world_law/staging/national/_work/CL
LOG=/workspace/world_law/staging/national/_logs/full/CL.log
export IPFS_DATASETS_LEGAL_CORPORA_ROOT="$ROOT" IPFS_DATASETS_LEGAL_COLLECTORS_ROOT="$N" HF_TOKEN_PATH=/dev/null HF_HUB_OFFLINE=1 HF_TOKEN= PYTHONUNBUFFERED=1
export PYTHONPATH=$N/rlhook ARCHIVE_LANE=national
echo "=== $(date '+%F %T %Z') slow relaunch cl/collect_cl_slow.py (1 worker, >=3s, stop after 20 empty)" >> "$LOG"
( cd "$ROOT" && /workspace/world_law/pipeline/venv/bin/python "$N/cl/collect_cl_slow.py" ) >> "$LOG" 2>&1
rc=$?; echo "=== $(date '+%F %T %Z') exit rc=$rc" >> "$LOG"
/workspace/world_law/pipeline/venv/bin/python "$N/emit_staged.py" CL >> "$LOG" 2>&1
[ $rc -eq 3 ] && echo "=== $(date '+%F %T %Z') STOPPED-THROTTLED (20 consecutive empty) FINISHED" >> "$LOG" || echo "=== $(date '+%F %T %Z') FINISHED" >> "$LOG"
