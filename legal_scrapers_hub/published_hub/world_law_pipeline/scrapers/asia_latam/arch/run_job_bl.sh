#!/bin/bash
# run_job.sh variant: run_job_bl.sh <name> <workdir_job> <script.py> [args...] -> wrapped in breaker_loop.sh
set -u
NAME=$1; shift; JOB=$1; shift; SCRIPT=$1; shift
LOGD=/workspace/world_law/staging/asia_latam/_logs/archive; mkdir -p "$LOGD"; TS=$(date +%Y%m%d_%H%M)
cd "$(dirname "$0")"
ARCHIVE_LANE=asia_latam setsid nohup nice -n 10 ./breaker_loop.sh /workspace/world_law/staging/asia_latam/_archive_work/$JOB/_STOP \
  /workspace/world_law/pipeline/venv/bin/python -u "$SCRIPT" "$@" > "$LOGD/${NAME}_${TS}.log" 2>&1 < /dev/null &
echo "$!" > "$LOGD/${NAME}.pid"; echo "pid $! log $LOGD/${NAME}_${TS}.log"
