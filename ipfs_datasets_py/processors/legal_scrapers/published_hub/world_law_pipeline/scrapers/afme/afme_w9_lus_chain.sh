#!/bin/bash
# wave 9 chain B: Lusophone municipal sites (live MZ, CV) -> archived fallback (CC then Wayback, 1 worker; test-gated) -> stage MZ CV
cd /workspace/world_law/out; export ARCHIVE_LANE=afme; L=afme/_lus_chain.log
for cc in MZ CV; do ./afme_slot.sh x .afme_venv/bin/python -W ignore afme_au_live.py afme/lus_${cc}_cfg.json 0 >> afme/_lus_${cc}_full.log 2>&1; done
while pgrep -f "lus_CV_arch_cfg.json test" >/dev/null; do sleep 30; done
for cc in CV MZ; do
  [ -f afme/$cc/_arch_done_test.tsv ] || ./afme_slot.sh x ../pipeline/venv/bin/python -W ignore afme_lus_arch.py afme/lus_${cc}_arch_cfg.json test >> afme/_lus_${cc}_arch_test.log 2>&1
  if ../pipeline/venv/bin/python afme_gate.py $cc .lus_arch_w9.test.jsonl --allow-empty >> $L 2>&1; then
    ./afme_slot.sh x ../pipeline/venv/bin/python -W ignore afme_lus_arch.py afme/lus_${cc}_arch_cfg.json >> afme/_lus_${cc}_arch_full.log 2>&1
  else echo "$(date) $cc arch test gate failed" >> $L; fi
done
.afme_venv/bin/python afme_stage.py MZ CV >> afme/_stage_w9.log 2>&1
echo "$(date) chain B done" >> $L
