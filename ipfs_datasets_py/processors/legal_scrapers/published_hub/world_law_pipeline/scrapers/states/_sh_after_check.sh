#!/bin/bash
# Waits for the SH CDX check; if it lists >= 50 Gesamtausgabe (max=true) URLs, starts the de_sh_wb full run.
L=/workspace/world_law/staging/states/_logs
while pgrep -f _sh_cdx_check.py >/dev/null; do sleep 120; done
n=$(grep -oE "'?True'?: [0-9]+" $L/sh_cdx_check.out | grep -oE "[0-9]+" | sort -n | tail -1)
echo "$(date) check done; max=true urls: ${n:-0}" >> $L/sh_after_check.log
if [ "${n:-0}" -ge 50 ]; then
  cd /workspace/world_law/pipeline/scrapers/states
  ARCHIVE_LANE=states nohup /workspace/world_law/pipeline/venv/bin/python -u arch_states.py de_sh_wb --no-cc > $L/full_de_sh_wb_$(date +%Y%m%d_%H%M).out 2>&1 &
  echo "$(date) started de_sh_wb full run pid $!" >> $L/sh_after_check.log
else
  echo "$(date) below threshold: SH full run not started" >> $L/sh_after_check.log
fi
