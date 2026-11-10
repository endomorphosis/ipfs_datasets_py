#!/bin/bash
# Detached, resumable launcher: run_job.sh <name> <script.py> [args...]  (re-run the same command to resume)
set -u
NAME=$1; shift; SCRIPT=$1; shift
LOGD=/workspace/world_law/staging/asia_latam/_logs/archive
mkdir -p "$LOGD"
TS=$(date +%Y%m%d_%H%M)
cd "$(dirname "$0")"
ARCHIVE_LANE=asia_latam setsid nohup nice -n 10 /workspace/world_law/pipeline/venv/bin/python -u "$SCRIPT" "$@" > "$LOGD/${NAME}_${TS}.log" 2>&1 < /dev/null &
echo "$!" > "$LOGD/${NAME}.pid"
echo "pid $! log $LOGD/${NAME}_${TS}.log"
