#!/bin/bash
# After the running Ontario regs pass ends AND the extra-ID CDX list exists, rerun ca_on_elaws (dedupe by done.tsv).
# 2026-11-01 18:15 PST: disk floor 36 -> 11 GB gate (lane floor 10 GB); ca_on_elaws now launched via lane_ramgate.
# 2026-11-01 12:20 PST: restarted after the 10:20 reboot. Added: single-instance lock; if the ON CDX parts are still
# missing and no act_on_cdx.sh/cdx_list.py chain is running (archive_discovery_loop only calls act_on_cdx.sh while the
# ACT lists are missing), retry just the ON cdx_list itself every 30 min (cached parts are skipped; archive module only).
cd /workspace/world_law/pipeline/scrapers/states
exec 8>data/.on_regs_rerun.lock; flock -n 8 || { echo "$(date) another on_regs_rerun.sh holds the lock; exit"; exit 0; }
L=/workspace/world_law/staging/states/_logs
V=/workspace/world_law/pipeline/venv/bin/python
export ARCHIVE_LANE=states
while pgrep -f "run_full.py --source ca_on_elaws" >/dev/null; do sleep 120; done
while [ ! -s data/on_regulation_cdx_extra.txt ]; do
  if ! pgrep -f "act_on_cdx.sh" >/dev/null && ! pgrep -f "cdx_list.py data/on_regulation_cdx_extra" >/dev/null; then
    g=$(df -BG --output=avail / | tail -1 | tr -dc 0-9)
    if [ "$g" -ge 11 ]; then
      echo "$(date) ON cdx_list retry"
      $V cdx_list.py data/on_regulation_cdx_extra.txt www.ontario.ca/laws/regulation/ 9006 9007 9008 9009 901 902 903 91 92 93 94 95 96 97 98 99 >> $L/cdx_list_on_regs.out 2>&1
      echo "$(date) ON cdx_list rc=$?"
    fi
    [ -s data/on_regulation_cdx_extra.txt ] || sleep 1800
  else
    sleep 300
  fi
done
g=$(df -BG --output=avail / | tail -1 | tr -dc 0-9); [ "$g" -lt 11 ] && { echo "$(date) disk floor: not starting ca_on_elaws"; exit 0; }
cp data/on_regulation_cdx_extra.txt data/.on_reg_full.tmp && mv data/.on_reg_full.tmp data/on_regulation_cdx_full.txt
echo "$(date) starting run_full ca_on_elaws (regs2)"
. ./lane_ramgate.sh; ramgate_run 130 $L/full_ca_on_elaws_regs2.out $V -u run_full.py --source ca_on_elaws
echo "$(date) run_full ca_on_elaws rc=$?"
