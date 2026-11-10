#!/bin/bash
# wave 8 CC chain, slot-limited per step. args: list of NAME where cfg=afme_cfg_<NAME>.json, probe=afme/_probe/<name lower>.json
# per NAME: probe (skip if cdx exists) -> 20-place test -> full if ok>=min(15,tested) & 0 bad -> afme_stage.py (flock). Log afme/_wave8.log
cd /workspace/world_law/out; export ARCHIVE_LANE=afme; L=afme/_wave8.log; P=".afme_venv/bin/python -W ignore"
for n in "$@"; do lc=$(echo $n | tr A-Z a-z)
  [ "$(df -BG --output=avail /workspace | tail -1 | tr -dc 0-9)" -lt 35 ] && { echo "$(date) STOP disk" >> $L; exit 1; }
  cdx=$(python3 -c "import json;c=json.load(open('afme_cfg_$n.json'));print(c.get('cdx') or '/workspace/world_law/out/afme/_probe/'+c['cc']+'/_cdx_'+c['cc']+'.jsonl')")
  [ -s "$cdx" ] || ./afme_slot.sh x $P afme_ccidx.py afme/_probe/$lc.json > afme/_probe/$lc.log 2>&1
  echo "$(date) $n probe $(tail -1 afme/_probe/$lc.log)" >> $L
  t=afme/_test_$n.log
  grep -q '^DONE' $t 2>/dev/null || ./afme_slot.sh x $P afme_cc.py afme_cfg_$n.json 20 10 test > $t 2>&1
  ok=$(grep -c '"ok": true' $t); bad=$(grep -c '"ok": false' $t); tested=$((ok+bad)); need=$(( tested < 15 ? tested : 15 ))
  echo "$(date) $n test ok=$ok bad=$bad $(grep -m1 'host-mapped' $t)" >> $L
  if [ "$ok" -ge 1 ] && [ "$ok" -ge "$need" ] && [ "$bad" -eq 0 ]; then
    ./afme_slot.sh x $P afme_cc.py afme_cfg_$n.json 0 300 > afme/_run_$n.log 2>&1
    echo "$(date) $n full $(tail -1 afme/_run_$n.log)" >> $L; .afme_venv/bin/python afme_stage.py >> $L 2>&1
  else echo "$(date) $n full NOT launched" >> $L; fi
done
echo "$(date) w8 cc chain [$*] DONE" >> $L
