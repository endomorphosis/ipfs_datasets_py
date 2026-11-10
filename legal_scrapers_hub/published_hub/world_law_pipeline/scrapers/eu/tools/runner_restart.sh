#!/bin/bash
# Graceful restart of THE single EU archive runner so it loads new code/targets (2026-10-18, CEE pass).
# SIGTERM -> runner flushes and exits at the next item; wait (<= 45 min); start ONE new runner only if none is alive.
OLD=${1:?old runner pid}
EU=/workspace/world_law/pipeline/scrapers/eu; L=/workspace/world_law/staging/eu/_logs; N=/workspace/world_law/staging/eu/_state/cee_notes.md
ts(){ date '+%F %T %Z'; }
echo "$(ts) restart: SIGTERM $OLD" >> $L/runner_restart.log
kill -TERM "$OLD" 2>/dev/null
for i in $(seq 1 270); do kill -0 "$OLD" 2>/dev/null || break; sleep 10; done
if kill -0 "$OLD" 2>/dev/null; then echo "$(ts) restart ABORTED: $OLD still alive after 45 min (not starting a second runner)" | tee -a $L/runner_restart.log >> $N; exit 1; fi
if pgrep -f "archive_q2.py (run|queue|czfirst)" > /dev/null; then echo "$(ts) restart ABORTED: another archive_q2 runner is alive" | tee -a $L/runner_restart.log >> $N; exit 1; fi
# 2026-10-18: cd on its own line so $! is the python PID (setsid/nohup exec); before, `cd && ... &` logged a subshell PID.
cd $EU || exit 1
ARCHIVE_LANE=eu MALLOC_ARENA_MAX=2 setsid nohup /workspace/world_law/pipeline/venv/bin/python -u archive_q2.py run >> $L/archive_runner.nohup.out 2>&1 < /dev/null &
NEW=$!
sleep 5; kill -0 $NEW 2>/dev/null || { echo "$(ts) restart: new runner $NEW died at start (see archive_runner.log)" | tee -a $L/runner_restart.log >> $N; exit 1; }
echo "$(ts) restart: new runner PID $NEW (old $OLD exited)" | tee -a $L/runner_restart.log >> $N
