#!/bin/bash
# 2026-11-01 ~11:50 PST: RESUME of county_chain_20261101.sh (killed by 10:20 reboot): Loire FR-42 top-up remainder -> de_by_topup1.
#  fr_raa_next11 (Cher FR-18, Meurthe-et-Moselle FR-54, Haute-Loire FR-43 Webdelib+ live; Loire FR-42 délibérations top-up) -> de_by_topup1 (13 Bavarian Landkreise capped at 400 URLs).
#  Not queued: Rhön-Grabfeld / Eichstätt / Würzburg archive (exhausted / near-exhausted after last passes), Fürth, Sarthe délibs, Mayotte (TLS drops), Val-de-Marne CD (TLS reset again 00:20 PDT),
#   Mayenne actes-administratifs.lamayenne.fr (connect fail), Orne (arrêtés page only 2023), Vienne/Hautes-Pyrénées (not evaluated in depth). RO: 9 remaining judete known blocked, not re-probed.
# Guard: before each job and every 20 s while one runs, free MiB on /workspace must be >= GUARD_MIN_MIB (20480); else ask archive_retry to stop (flushes), then kill job group and exit 0.
D=/workspace/world_law/pipeline/scrapers/counties; L=/workspace/world_law/staging/counties/_logs
STOP=/workspace/world_law/staging/counties/_logs/.chain_stop_20261101b
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
run fr_raa_loire_resume.sh fr_raa_loire_resume.log
run de_by_topup1.sh de_by_topup1.log
echo "$(date) chain complete"
