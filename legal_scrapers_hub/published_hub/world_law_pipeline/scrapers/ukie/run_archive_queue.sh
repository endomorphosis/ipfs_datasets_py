#!/bin/sh
PY=/workspace/world_law/pipeline/venv/bin/python; [ -x "$PY" ] || PY=/usr/bin/python3   # venv missing after 2026-10-18 box restore
# Low-rate archive queue (1 process, shared limiter lane ukie): places that were blocked live, and robots-disallowed docs.
cd /workspace/world_law/pipeline/scrapers/ukie
S=/workspace/world_law/staging/ukie/_state
export MALLOC_ARENA_MAX=2 ARCHIVE_LANE=ukie
. ./archive_passes.sh
cat $S/scale_A_zero_w1.txt $S/scale_A_zero_w2.txt $S/scale_B_refresh.txt $S/scale_D_other_principal.txt > $S/scale_all.txt
while :; do
  $PY -u councils.py run --archive-queue --archive-docs 8 --places-file $S/scale_all.txt
  if [ -f $S/live_done_w1 ] && [ -f $S/live_done_w2 ]; then
    $PY -u councils.py run --archive-queue --archive-docs 8 --places-file $S/scale_all.txt
    break
  fi
  sleep 900
done
archive_later_passes $S/scale_all.txt 6
echo ARCHIVE_QUEUE_DONE
