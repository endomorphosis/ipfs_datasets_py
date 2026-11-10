#!/bin/bash
# 2026-10-28 10:50 PDT: new county chain after county_chain_20261027.sh completed 08:26 PDT. One job at a time, all archive-only (Wayback/CC):
#  de_by17 Eichstätt -> de_by18 Würzburg -> Sarthe FR-72 délibérations -> Fürth pass 6 -> Rhön-Grabfeld pass 2.
#  RO: no crawlable uncovered judet left (re-probed 10:15 PDT: Bistrița-Năsăud/Iași/Brașov connect fail, Suceava 503, Argeș 403, Tulcea SharePoint JS, Vrancea .doc only).
# Guard: before each job and every 20 s while one runs, free MiB on /workspace must be >= GUARD_MIN_MIB (20480); else ask archive_retry to stop (flushes), then kill job group and exit 0.
D=/workspace/world_law/pipeline/scrapers/counties; L=/workspace/world_law/staging/counties/_logs
STOP=/workspace/world_law/staging/counties/_logs/.chain_stop_20261028
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
run de_by17.sh de_by17.log
run de_by18.sh de_by18.log
run fr_raa_cd_fr72_delib_archive.sh fr_raa_cd_FR-72_delib_archive.log
run de_by13_fuerth_archive_pass6.sh de_by13_fuerth_archive_pass6.log
run de_by16_rhoen_grabfeld_archive_pass2.sh de_by16_rhoen_grabfeld_archive_pass2.log
echo "$(date) chain complete"
