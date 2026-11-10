#!/bin/bash
# wave 10 chain AU-arch: wait for the 20-council test -> validate gate (0 bad) -> full archived fallback for 103 unreachable/blocked AU councils
# (afme_arch10.py, CC index prefix queries then Wayback via ratelimit breaker, 1 archive worker; resumable via afme/AU/_arch_done.tsv) -> stage AU.
cd /workspace/world_law/out; export ARCHIVE_LANE=afme; L=afme/_w10_chain.log
while pgrep -f "afme_arch10.py afme/au_arch_w10_test_cfg.json" >/dev/null; do sleep 30; done
if ../pipeline/venv/bin/python afme_gate.py AU .au_arch_w10.test.jsonl --allow-empty >> $L 2>&1; then
  ./afme_slot.sh x ../pipeline/venv/bin/python -W ignore afme_arch10.py afme/au_arch_w10_cfg.json >> afme/_au_arch_w10_full.log 2>&1
  echo "$(date) AU arch full exit $?" >> $L
  .afme_venv/bin/python afme_stage.py AU >> afme/_stage_w10.log 2>&1; echo "$(date) AU staged" >> $L
else echo "$(date) AU arch test gate FAILED" >> $L; fi
