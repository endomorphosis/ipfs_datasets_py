#!/bin/bash
# wave 9 chain C: VIC + WA gazette council local laws, queued after chain A; each full run only if its test passed the 0-bad gate -> stage AU
cd /workspace/world_law/out; export ARCHIVE_LANE=afme; L=afme/_gaz_chain.log
while pgrep -f "afme_w9_au_chain.sh" >/dev/null || pgrep -f "afme_aus_gaz.py (vic|wa) .* test" >/dev/null; do sleep 60; done
for st in vic wa; do
  if ../pipeline/venv/bin/python afme_gate.py AU .gaz_${st}_20261018.test.jsonl >> $L 2>&1; then
    ./afme_slot.sh x .afme_venv/bin/python -W ignore afme_aus_gaz.py $st 2000-2026 0 >> afme/_gaz_${st}_full.log 2>&1
  else echo "$(date) $st gazette test gate failed" >> $L; fi
done
.afme_venv/bin/python afme_stage.py AU >> afme/_stage_w9.log 2>&1
echo "$(date) chain C done" >> $L
