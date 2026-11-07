#!/bin/bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-10-27 05:50 PDT: restart chain after the 04:41 guard trip (Fürth pass 5 resume, then Rhön-Grabfeld). One job at a time.
# Guard: before each job and every 20 s while one runs, free MiB on /workspace must be >= 46080; else ask archive_retry to stop (flushes), then kill job group and exit 0.
D=${WORLD_LAW_ROOT}/pipeline/scrapers/counties; L=${WORLD_LAW_ROOT}/staging/counties/_logs
STOP=${WORLD_LAW_ROOT}/staging/counties/_logs/.chain_stop_20261027
. $D/county_chain_guard.sh
rm -f $STOP; export ARCHIVE_RETRY_STOPFILE=$STOP
cd $D
echo "$(date) chain start pid $$ free $(free_mib) MiB"
run() {  # run <script> <log>
  f=$(free_mib); [ "$f" -lt "$GUARD_MIN_MIB" ] && { echo "$(date) STOP before $1: ${f} MiB free < $GUARD_MIN_MIB"; exit 0; }
  echo "$(date) START $1 -> $2 (free ${f} MiB)"
  setsid sh $D/$1 >> $L/$2 2>&1 & jp=$!
  while kill -0 $jp 2>/dev/null; do
    sleep 20; f=$(free_mib)
    if [ "$f" -lt "$GUARD_MIN_MIB" ]; then
      echo "$(date) DISK GUARD TRIPPED during $1: ${f} MiB free < $GUARD_MIN_MIB; asking archive_retry to flush+stop"
      touch $STOP; echo "$(date) STOP disk guard tripped (${f} MiB free < $GUARD_MIN_MIB) - chain stopping" >> $L/$2
      for i in $(seq 1 21); do pgrep -s $jp -f archive_retry.py >/dev/null || break; sleep 20; done
      pkill -TERM -s $jp; sleep 3; pkill -KILL -s $jp
      echo "$(date) chain exit (disk guard)"; exit 0
    fi
  done
  wait $jp; echo "$(date) END $1 rc=$?"
}
run de_by13_fuerth_archive_pass5.sh de_by13_fuerth_archive_pass5.log
run de_by16.sh de_by16.log
echo "$(date) chain complete"
