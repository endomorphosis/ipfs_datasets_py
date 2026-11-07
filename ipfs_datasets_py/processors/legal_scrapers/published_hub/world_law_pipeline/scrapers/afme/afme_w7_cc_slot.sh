#!/bin/bash
# slot-limited CC harvester retest+full: afme_w7_cc_slot.sh CC   (test log afme/_test_<CC>.log; gate ok>=min(15,tested), 0 bad, ok>=1)
cd /workspace/world_law/out; export ARCHIVE_LANE=afme; L=afme/_wave7.log; c=$1; P=".afme_venv/bin/python -W ignore"
t=afme/_test_$c.log; grep -q '^DONE' $t 2>/dev/null || ./afme_slot.sh x $P afme_cc.py afme_cfg_$c.json 20 10 test > $t 2>&1
ok=$(grep -c '"ok": true' $t); bad=$(grep -c '"ok": false' $t); tested=$((ok+bad)); need=$(( tested < 15 ? tested : 15 ))
echo "$(date) $c retest ok=$ok bad=$bad $(grep -m1 'host-mapped' $t)" >> $L
if [ "$ok" -ge 1 ] && [ "$ok" -ge "$need" ] && [ "$bad" -eq 0 ]; then
  ./afme_slot.sh x $P afme_cc.py afme_cfg_$c.json 0 300 > afme/_run_$c.log 2>&1
  echo "$(date) $c full $(tail -1 afme/_run_$c.log)" >> $L; .afme_venv/bin/python afme_stage.py >> $L 2>&1
else echo "$(date) $c full NOT launched" >> $L; fi
