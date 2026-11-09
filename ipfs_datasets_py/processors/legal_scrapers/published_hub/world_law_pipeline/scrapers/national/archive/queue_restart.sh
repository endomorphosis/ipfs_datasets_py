#!/usr/bin/env bash
# Sequential restart of OOM-killed / dead national archive targets, one runner at a time.
# Each runner: prlimit --as=600 MiB (address-space cap -> MemoryError instead of OOM killer), nice 10,
# MALLOC_ARENA_MAX=2, lane 'national'; starts only when MemAvailable >= $MIN_FREE_MB.
# Phase A: small probe (--max-fetch $SMALL), Phase B: full resumable run. Resumes from done.tsv / candidates.jsonl.
set -u
HERE=/workspace/world_law/pipeline/scrapers/national/archive
L=/workspace/world_law/staging/national/_logs/archive
PY=/workspace/world_law/pipeline/venv/bin/python
export PYTHONUNBUFFERED=1 ARCHIVE_LANE=national MALLOC_ARENA_MAX=2
AS=${AS:-629145600}; MIN_FREE_MB=${MIN_FREE_MB:-900}; SMALL=${SMALL:-25}
TARGETS=${TARGETS:-"KZ_adilet PE_spij CN_flk ID_national RU_publication"}
cd $HERE
gate() { while [ $(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo) -lt $MIN_FREE_MB ]; do sleep 30; done; }
echo "$(date '+%F %T') restart-queue $$ start (seq, as=${AS}B minfree=${MIN_FREE_MB}M) targets: $TARGETS" >> $L/queue.log
[ "${SKIP_SMALL:-0}" = 1 ] || for t in $TARGETS; do
  gate; prlimit --as=$AS nice -n 10 $PY run_archive.py $t --max-fetch $SMALL --chunk 25 >> $L/small_$t.log 2>&1
  echo "$(date '+%F %T') small $t rc=$? (restart-queue, as=600M)" >> $L/queue.log
done
for t in $TARGETS; do
  gate; prlimit --as=$AS nice -n 10 $PY run_archive.py $t --chunk 200 >> $L/full_$t.log 2>&1
  echo "$(date '+%F %T') full $t rc=$? (restart-queue, as=600M)" >> $L/queue.log
done
echo "$(date '+%F %T') restart-queue $$ ALL DONE" >> $L/queue.log
