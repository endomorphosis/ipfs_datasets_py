#!/bin/bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# Task A (2026-10-27): rerun the 6 Wayback-deferred wave-10 places (DZ wd_Q616858, TN wd_Q276565/wd_Q328199/wd_Q123739128, SA wd_Q27139, ET wd_Q193486). 1 Wayback worker, sequential.
cd ${WORLD_LAW_ROOT}/out; export ARCHIVE_LANE=afme; L=afme/_w10_taskA.log
for cc in DZ TN SA ET; do lc=$(echo $cc | tr A-Z a-z)
  [ $(df --output=avail -B1G /workspace | tail -1) -lt 38 ] && { echo "$(date) STOP disk floor" >> $L; exit 3; }
  ./afme_slot.sh x ../pipeline/venv/bin/python -W ignore afme_arch10.py afme/${lc}_arch_w10_taskA_cfg.json >> afme/_${lc}_w10_taskA.log 2>&1
  echo "$(date) $cc taskA exit $?" >> $L
  .afme_venv/bin/python afme_stage.py $cc >> afme/_stage_w10.log 2>&1; echo "$(date) $cc staged" >> $L
done
echo "$(date) taskA done" >> $L
