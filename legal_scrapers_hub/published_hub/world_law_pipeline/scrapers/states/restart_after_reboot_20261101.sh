#!/bin/bash
# 2026-11-01 ~11:50 PST: restart states lane after box reboot (~10:20 PST). Resumes all from checkpoints. NS batch NOT started (held).
cd /workspace/world_law/pipeline/scrapers/states
L=/workspace/world_law/staging/states/_logs; PY=/workspace/world_law/pipeline/venv/bin/python
q() { setsid nohup bash "$1" >> "$L/$2" 2>&1 < /dev/null & echo "$1 pid $!"; }
gated() { local est=$1 log=$2; shift 2
  setsid nohup bash -c '. ./lane_ramgate.sh; ramgate_run "$@"' _ $est "$log" "$@" >> "$log.gate" 2>&1 < /dev/null & echo "gated $* pid $!"; }
q ca_qc_full_queue.sh ca_qc_full_queue.out
q ca_bc_full_queue.sh ca_bc_full_queue.out
q ca_ab_full_queue.sh ca_ab_full_queue.out
q ca_yt_full_queue.sh ca_yt_full_queue.out
q de_be_wb_full_queue.sh de_be_wb_full_queue.out
gated 130 $L/full_au_nsw_archive_20261020_0345.out $PY -u run_full.py --source au_nsw_archive
export ARCHIVE_LANE=states STATES_MAX_DEFERS=10000
for t in in_state at_ris id_bpk_prov; do gated 150 $L/${t}_full_20261031_1211.log $PY -u arch_states.py $t --flush-secs 3600; done
q archive_discovery_loop.sh archive_discovery_loop.out
q archive_tests.sh archive_tests.out
q us_gap_fulls.sh us_gap_fulls.out
q deferq_compact_loop.sh deferq_compact_loop.log
