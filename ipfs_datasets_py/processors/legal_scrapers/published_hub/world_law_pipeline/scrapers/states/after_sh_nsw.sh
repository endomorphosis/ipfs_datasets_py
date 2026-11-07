#!/bin/bash
# 2026-10-19 03:40 PDT: give the states lane's Wayback share to the DE-SH full run and the NSW r2 test first;
# once both have exited, resume in_state and id_bpk_prov (their deferred queues persist in staging/states/_work/<t>/deferred.tsv).
cd /workspace/world_law/pipeline/scrapers/states
L=/workspace/world_law/staging/states/_logs
while pgrep -f "arch_states.py de_sh_wb" >/dev/null || pgrep -f "run_full.py --source au_nsw_archive --test" >/dev/null; do sleep 120; done
for t in in_state id_bpk_prov; do
  pgrep -f "arch_states.py $t" >/dev/null && continue
  f=$L/${t}_full_$(date +%Y%m%d_%H%M).log
  ARCHIVE_LANE=states nohup /workspace/world_law/pipeline/venv/bin/python -u arch_states.py $t --flush-secs 3600 > $f 2>&1 &
  echo "$(date '+%F %T %Z') started $t pid $! log $f" >> $L/after_sh_nsw.log
done
