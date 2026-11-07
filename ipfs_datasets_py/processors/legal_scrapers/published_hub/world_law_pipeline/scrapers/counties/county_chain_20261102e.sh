#!/bin/bash
# 2026-11-02 19:20 PST chain e: resume of chain b phase 2 (Bavarian top-up 3 archive rounds 2-4) after 17:52 RAM-guard stop.
# archive_retry.py skips URLs already archived. guard_retry waits 5 min x up to 2 h on floor dips.
cd /workspace/world_law/pipeline/scrapers/counties
source ./county_chain_guard.sh; export GUARD_MIN_MIB=10240 GUARD_MIN_RAM_MIB=1536; source ./county_guard_run.sh
PY=/workspace/world_law/pipeline/venv/bin/python; L=/workspace/world_law/staging/counties/_logs; C=$L/county_chain_20261102e.log
echo "$(date) chain e start pid=$$" >> $C
for round in 2 3 4; do
  for cfg in de_by_kreisrecht_landkreis_ebersberg_archive.json de_by_kreisrecht_landkreis_regensburg_archive.json de_by_kreisrecht_landkreis_fürth_archive.json de_by_kreisrecht_Q*_topup3_404_archive.json; do
    [ -f "$cfg" ] || continue; n=$(basename $cfg .json)
    guard_retry "arch_$n" bash -c 'ARCHIVE_RETRY_STOPFILE=$GUARD_STOPFILE exec timeout 3300 '"$PY"' -u archive_retry.py '"$cfg"' 50' 2>&1 \
      | grep --line-buffered -E '^(todo|OK|MISS|INVALID|SKIP_NOTPDF|written|STOP|GUARD|Traceback|[A-Za-z]*Error)' >> $L/de_by_archive_topup3.log
    rc=${PIPESTATUS[0]}; echo "$(date) [e] archive round $round $cfg rc=$rc" >> $C; [ $rc -eq 99 ] && { echo "$(date) [e] guard gave up" >> $C; exit 99; }
  done
  [ $round -lt 4 ] && sleep 900
done
echo "$(date) chain e done" >> $C
