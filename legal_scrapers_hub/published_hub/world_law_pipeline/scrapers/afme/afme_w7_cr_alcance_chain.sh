#!/bin/bash
# CR La Gaceta Alcances: test (latest 60 weekdays) -> gate ok>=min(15,files), 0 bad, >=1 -> full 2016-01-01..2026-10-16 -> stage. Slot-limited.
cd /workspace/world_law/out; export ARCHIVE_LANE=afme; L=afme/_wave7.log; P=".afme_venv/bin/python -W ignore"
grep -q '^DONE' afme/_cr_alcance_test.log 2>/dev/null || ./afme_slot.sh x $P afme_cr_alcance.py 2026-06-01 2026-10-16 test > afme/_cr_alcance_test.log 2>&1
t=$(grep '^DONE' afme/_cr_alcance_test.log); echo "$(date) CR alcance test $(echo $t | head -c 300)" >> $L
ok=$(echo "$t" | awk '{print $3}'); bad=$(echo "$t" | awk '{print $5}'); n=$(echo "$t" | awk '{print $7}'); need=$(( n<15 ? n : 15 ))
if [ -n "$ok" ] && [ "$ok" -ge 1 ] && [ "$ok" -ge "$need" ] && [ "$bad" -eq 0 ]; then
  ./afme_slot.sh x $P afme_cr_alcance.py 2016-01-01 2026-10-16 > afme/_cr_alcance_full.log 2>&1
  echo "$(date) CR alcance full $(grep '^DONE' afme/_cr_alcance_full.log | head -c 300)" >> $L; .afme_venv/bin/python afme_stage.py >> $L 2>&1
else echo "$(date) CR alcance full NOT launched" >> $L; fi
