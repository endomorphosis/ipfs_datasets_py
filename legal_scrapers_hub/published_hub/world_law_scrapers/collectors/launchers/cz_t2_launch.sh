#!/bin/bash
# CZ T2 one-command launch (CoS contingent GO 2026-10-06 00:50 PT; fire only after Box Health Watchdog GO).
# Starts `cz_sbirkapp_collect.py t2` detached in its own session; the collector itself refuses (exit 2, reason in the log) if: STOP_CZ exists,
# MemAvail < 4200, OCR/dictionary tools missing, another CZ collector or any id_bpk process runs, or PIN collectors >= 2.
# Log: /workspace/logs/cz_t2_collect_<YYYYmmddTHHMMSS>.log (review packages log to ..._review.log). Stop: touch STOP_CZ. Pause: touch PAUSE_CZ.
set -u
cd /workspace || exit 1
TS=$(date +%Y%m%dT%H%M%S); LOG=/workspace/logs/cz_t2_collect_$TS.log
TOK=$(head -1 /workspace/legal-corpora/cz_sbirkapp/COS_GO_T2 2>/dev/null)
[ -n "$TOK" ] || { echo "no COS_GO_T2 token"; exit 1; }
U=/workspace/usr/usr
CZ_USR_ROOT=/workspace/usr TESSDATA_PREFIX=$U/share/tesseract-ocr/5/tessdata PATH=$U/bin:$PATH LD_LIBRARY_PATH=$U/lib/x86_64-linux-gnu MALLOC_ARENA_MAX=2 CZP_LOG=$LOG setsid nohup nice -n 5 /workspace/venv/bin/python -u /workspace/scripts/cz_sbirkapp_collect.py t2 --cos-go "$TOK" >> "$LOG" 2>&1 < /dev/null &
sleep 10
echo "log: $LOG"; tail -n 5 "$LOG"
pgrep -af "cz_sbirkapp_collect.py t2" | grep -v pgrep || echo "NOT RUNNING (see log)"
