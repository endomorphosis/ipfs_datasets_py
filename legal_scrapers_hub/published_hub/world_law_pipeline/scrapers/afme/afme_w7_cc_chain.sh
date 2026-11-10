#!/bin/bash
# wave 7 CC chain: per country probe -> 20-place test -> full (gate: ok>=min(15,tested), 0 invalid) -> afme_stage.py. Log afme/_wave7.log
cd /workspace/world_law/out; export ARCHIVE_LANE=afme; L=afme/_wave7.log
for c in "$@"; do lc=$(echo $c | tr A-Z a-z)
  [ "$(df -BG --output=avail /workspace | tail -1 | tr -dc 0-9)" -lt 35 ] && { echo "$(date) STOP disk" >> $L; exit 1; }
  [ -f afme/_probe/$c/_cdx_$c.jsonl ] || .afme_venv/bin/python afme_ccidx.py afme/_probe/$lc.json > afme/_probe/$lc.log 2>&1
  echo "$(date) $c probe $(tail -1 afme/_probe/$lc.log)" >> $L
  t=afme/_test_$c.log
  grep -q '^DONE' $t 2>/dev/null || .afme_venv/bin/python -W ignore afme_cc.py afme_cfg_$c.json 20 10 test > $t 2>&1
  ok=$(grep -c '"ok": true' $t); bad=$(grep -c '"ok": false' $t); tested=$((ok+bad)); need=$(( tested < 15 ? tested : 15 ))
  echo "$(date) $c test ok=$ok bad=$bad $(grep -m1 'host-mapped' $t)" >> $L
  if [ "$ok" -ge 1 ] && [ "$ok" -ge "$need" ] && [ "$bad" -eq 0 ]; then
    .afme_venv/bin/python -W ignore afme_cc.py afme_cfg_$c.json 0 300 > afme/_run_$c.log 2>&1
    echo "$(date) $c full $(tail -1 afme/_run_$c.log)" >> $L; .afme_venv/bin/python afme_stage.py >> $L 2>&1
  else echo "$(date) $c full NOT launched" >> $L; fi
done
echo "$(date) w7 cc chain [$*] DONE" >> $L
