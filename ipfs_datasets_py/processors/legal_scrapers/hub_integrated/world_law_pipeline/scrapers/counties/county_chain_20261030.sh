#!/bin/bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-10-30 ~09:00 PDT: next county chain after county_chain_20261028.sh completed 07:21 PDT. One job at a time, new coverage first:
#  fr_raa_next10 (Gers FR-32 live, Webdelib+) -> de_by19 Cham (archive-only, county-level CDX config) -> Rhön-Grabfeld pass 3 -> Eichstätt pass 2 -> Würzburg pass 2 (6 rounds, low yield).
#  Not queued: Fürth pass 7 (pass 6 only +11 in 8 rounds), Sarthe FR-72 délibérations (Wayback lacks copies), Mayotte FR-976 (TLS drops on repeat requests; 14 Wayback captures).
#  RO: re-probed 08:25 PDT - unchanged (cjbn.ro/icc.ro/cjiasi.ro/judbrasov.ro connect fail, cjsuceava 503, cjarges 403, Tulcea SharePoint JS, Vrancea .doc only) -> none queued.
# Guard: before each job and every 20 s while one runs, free MiB on /workspace must be >= GUARD_MIN_MIB (20480); else ask archive_retry to stop (flushes), then kill job group and exit 0.
D=${WORLD_LAW_ROOT}/pipeline/scrapers/counties; L=${WORLD_LAW_ROOT}/staging/counties/_logs
STOP=${WORLD_LAW_ROOT}/staging/counties/_logs/.chain_stop_20261030
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
run fr_raa_next10.sh fr_raa_next10.log
run de_by19.sh de_by19.log
run de_by16_rhoen_grabfeld_archive_pass3.sh de_by16_rhoen_grabfeld_archive_pass3.log
run de_by17_eichstaett_archive_pass2.sh de_by17_eichstaett_archive_pass2.log
run de_by18_wuerzburg_archive_pass2.sh de_by18_wuerzburg_archive_pass2.log
echo "$(date) chain complete"
