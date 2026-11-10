#!/bin/bash
# wave 10 region chain: ONE archive worker for the whole afme lane, so it waits for the AU archive chain to finish first.
# Then, per country (priority order): 20-place test (or all) -> afme_gate 0 bad -> full -> stage. Resumable (afme/<CC>/_arch_done[_test].tsv; finished countries marked in afme/_w10_region_done.txt).
cd /workspace/world_law/out; export ARCHIVE_LANE=afme; L=afme/_w10_chain.log; D=afme/_w10_region_done.txt; touch $D
while pgrep -f "afme_w10_au_arch_chain.sh" >/dev/null || pgrep -f "afme_arch10.py afme/au_arch" >/dev/null; do sleep 60; done
for cc in CM CI SN BF BJ TG NE ML EG MA DZ TN SA AE KW QA OM BH IQ JO LB ET TZ PG FJ; do
  grep -qx $cc $D && continue
  lc=$(echo $cc | tr A-Z a-z)
  [ $(df --output=avail -B1G /workspace | tail -1) -lt 35 ] && { echo "$(date) STOP disk floor" >> $L; exit 3; }
  ./afme_slot.sh x ../pipeline/venv/bin/python -W ignore afme_arch10.py afme/${lc}_arch_w10_test_cfg.json test >> afme/_${lc}_w10_test.log 2>&1
  if ../pipeline/venv/bin/python afme_gate.py $cc .${lc}_arch_w10t.test.jsonl --allow-empty >> $L 2>&1; then
    ./afme_slot.sh x ../pipeline/venv/bin/python -W ignore afme_arch10.py afme/${lc}_arch_w10_cfg.json >> afme/_${lc}_w10_full.log 2>&1
    echo "$(date) $cc full exit $?" >> $L
    .afme_venv/bin/python afme_stage.py $cc >> afme/_stage_w10.log 2>&1; echo "$(date) $cc staged" >> $L; echo $cc >> $D
  else echo "$(date) $cc test gate FAILED (skipped)" >> $L; fi
done
echo "$(date) region chain done" >> $L
