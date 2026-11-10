#!/bin/bash
# wave 9 chain D: CV Boletim Oficial Parte G (user-approved despite terms §6) full run after the 0-bad test gate -> stage CV
cd /workspace/world_law/out; export ARCHIVE_LANE=afme; L=afme/_cv_boe_chain.log
while pgrep -f "afme_cv_boe.py 8 test" >/dev/null; do sleep 30; done
if ../pipeline/venv/bin/python afme_gate.py CV .boe_g_20261018.test.jsonl >> $L 2>&1; then
  ./afme_slot.sh x .afme_venv/bin/python -W ignore afme_cv_boe.py 0 >> afme/_cv_boe_full.log 2>&1
  .afme_venv/bin/python afme_stage.py CV >> afme/_stage_w9.log 2>&1
else echo "$(date) CV BOE test gate failed" >> $L; fi
echo "$(date) chain D done" >> $L
