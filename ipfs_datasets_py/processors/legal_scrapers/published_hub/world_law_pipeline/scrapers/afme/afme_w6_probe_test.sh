#!/bin/bash
# wave 6 light phase: CC index probes + 20-place tests (one process at a time). Log afme/_wave6.log
cd /workspace/world_law/out; export ARCHIVE_LANE=afme; L=afme/_wave6.log
free(){ df -BG --output=avail /workspace | tail -1 | tr -dc 0-9; }
.afme_venv/bin/python afme_ccidx.py afme/_probe/lii.json > afme/_probe/lii.log 2>&1; echo "$(date) LII probe $(tail -1 afme/_probe/lii.log)" >> $L
for c in TZ UG ZM MW ZW BW NA LS SZ MA EG AE SA QA OM BH KW; do lc=$(echo $c | tr A-Z a-z)
  [ "$(free)" -lt 35 ] && { echo "$(date) STOP disk" >> $L; exit 1; }
  [ -f afme/_probe/$c/_cdx_$c.jsonl ] || .afme_venv/bin/python afme_ccidx.py afme/_probe/$lc.json > afme/_probe/$lc.log 2>&1
  echo "$(date) $c probe $(tail -1 afme/_probe/$lc.log)" >> $L
  .afme_venv/bin/python -W ignore afme_cc.py afme_cfg_$c.json 20 10 test > afme/_test_$c.log 2>&1
  echo "$(date) $c test ok=$(grep -c '"ok": true' afme/_test_$c.log) bad=$(grep -c '"ok": false' afme/_test_$c.log) nodocs=$(grep -c '"FAIL"' afme/_test_$c.log) $(grep -m1 'places' afme/_test_$c.log)" >> $L
done
for c in TZ UG ZM MW ZW NA LS SZ; do
  .afme_venv/bin/python -W ignore afme_cc.py afme_cfg_${c}_lii.json 20 10 test > afme/_test_${c}_lii.log 2>&1
  echo "$(date) ${c}_lii test ok=$(grep -c '"ok": true' afme/_test_${c}_lii.log) bad=$(grep -c '"ok": false' afme/_test_${c}_lii.log) $(grep 'mapped' afme/_test_${c}_lii.log|tail -1)" >> $L
done
echo "$(date) light phase DONE" >> $L
