#!/bin/bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# 2026-11-01 15:10 PST: restart states lane after the 13:27 PST reboot (code + checkpoints restored 14:11-14:21 PST from
# the store backup; checkpoints verified against hf_published_from_ledger_20261101.tsv). Based on restart_after_reboot_20261101.sh.
# Adds: au_act_leg 20-row test (robots policy change 13:20 PST; held in _review) first in the RAM gate, on_regs_rerun.sh waiter.
# NS batch NOT started (held). deferq_compact_loop.sh not restarted (exits at once: no pre-2026-10-31 process remains).
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/states
L=${WORLD_LAW_ROOT}/staging/states/_logs; PY=${WORLD_LAW_ROOT}/pipeline/venv/bin/python
q() { setsid nohup bash "$1" >> "$L/$2" 2>&1 < /dev/null & echo "$1 pid $!"; }
gated() { local est=$1 log=$2; shift 2
  setsid nohup bash -c '. ./lane_ramgate.sh; ramgate_run "$@"' _ $est "$log" "$@" >> "$log.gate" 2>&1 < /dev/null & echo "gated $* pid $!"; }
gated 250 $L/test_au_act_leg_robots20261101.log $PY -u run_full.py --source au_act_leg --test 20
sleep 5
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
q on_regs_rerun.sh on_regs_rerun.out
