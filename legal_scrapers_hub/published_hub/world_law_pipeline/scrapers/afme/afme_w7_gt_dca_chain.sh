#!/bin/bash
# GT legal.dca.gob.gt: test (2025-01-01..today, 20 municipios) -> gate ok>=min(15,files) & 0 bad -> full (17/12/2018..16/10/2026) -> stage
cd /workspace/world_law/out; export ARCHIVE_LANE=afme; L=afme/_wave7.log; P=".afme_venv/bin/python -W ignore"
grep -q '^DONE' afme/_gt_dca_test.log 2>/dev/null || ./afme_slot.sh x $P afme_gt_dca.py 01/01/2025 16/10/2026 test > afme/_gt_dca_test.log 2>&1
t=$(grep '^DONE' afme/_gt_dca_test.log); echo "$(date) GT dca test $t" >> $L
ok=$(echo "$t" | awk '{print $3}'); bad=$(echo "$t" | awk '{print $5}'); n=$(echo "$t" | awk '{print $7}'); need=$(( n<15 ? n : 15 ))
if [ -n "$ok" ] && [ "$ok" -ge 1 ] && [ "$ok" -ge "$need" ] && [ "$bad" -eq 0 ]; then
  ./afme_slot.sh x $P afme_gt_dca.py 17/12/2018 16/10/2026 > afme/_gt_dca_full.log 2>&1
  echo "$(date) GT dca full $(grep '^DONE' afme/_gt_dca_full.log)" >> $L; .afme_venv/bin/python afme_stage.py >> $L 2>&1
else echo "$(date) GT dca full NOT launched" >> $L; fi
