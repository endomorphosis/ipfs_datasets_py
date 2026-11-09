#!/usr/bin/env bash
# Phase A: small yield probes (--max-fetch $SMALL) for $SMALL_TARGETS (default all), $PA at a time.
# Phase B: full resumable runs for $TARGETS, $P at a time. Logs: staging/national/_logs/archive/<phase>_<TARGET>.log
# Memory guards (box is OOM-prone, no swap): each runner gets `ulimit -v $VMEM_KB` (address-space cap, so a
# runaway runner fails with MemoryError instead of triggering the OOM killer) and only starts when
# MemAvailable >= $MIN_FREE_MB. All requests go through the box-wide limiter as lane 'national'.
set -u
HERE=/workspace/world_law/pipeline/scrapers/national/archive
L=/workspace/world_law/staging/national/_logs/archive
PY=/workspace/world_law/pipeline/venv/bin/python
export PYTHONUNBUFFERED=1 ARCHIVE_LANE=national
P=${P:-2}; PA=${PA:-1}; SMALL=${SMALL:-25}
VMEM_KB=${VMEM_KB:-1500000}; MIN_FREE_MB=${MIN_FREE_MB:-1200}
TARGETS=${TARGETS:-"BD KE_county AT RU_ips VN_vbpl PE MX_leyesbiblio IN_state ID_bpk_regional ID_national PH CN_npc IR EG_parliament EG_cc RU_publication TH KW MX_dof CN_flk KZ_adilet PE_spij"}
GATE="while [ \$(awk '/MemAvailable/{print int(\$2/1024)}' /proc/meminfo) -lt $MIN_FREE_MB ]; do sleep 30; done; ulimit -v $VMEM_KB;"
cd $HERE
echo "$(date '+%F %T') phase A start (PA=$PA vmem=${VMEM_KB}k minfree=${MIN_FREE_MB}M)" >> $L/queue.log
printf '%s\n' ${SMALL_TARGETS:-$TARGETS} | xargs -P $PA -I{} sh -c "$GATE nice -n 10 $PY run_archive.py {} --max-fetch $SMALL --chunk 25 >> $L/small_{}.log 2>&1; echo \"\$(date '+%F %T') small {} rc=\$?\" >> $L/queue.log"
echo "$(date '+%F %T') phase B start (P=$P)" >> $L/queue.log
printf '%s\n' $TARGETS | xargs -P $P -I{} sh -c "$GATE nice -n 10 $PY run_archive.py {} --chunk 200 >> $L/full_{}.log 2>&1; echo \"\$(date '+%F %T') full {} rc=\$?\" >> $L/queue.log"
echo "$(date '+%F %T') ALL DONE" >> $L/queue.log
