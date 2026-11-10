#!/bin/bash
# wave 6 full runs: wait for the PR LexJuris run (pid 99514 or any afme_pr_lexjuris.py) and the light phase to finish, then one full run at a time
# (with hubscan running that keeps the box at <=2 afme crawls). Gate per source: test ok>=min(15,places tested) and 0 invalid. Stage after each.
cd /workspace/world_law/out; export ARCHIVE_LANE=afme; L=afme/_wave6.log
while kill -0 99514 2>/dev/null || pgrep -f "afme_pr_lexjuris.py afme/PR" >/dev/null; do sleep 120; done
echo "$(date) PR run finished; staging PR" >> $L; .afme_venv/bin/python afme_stage.py >> $L 2>&1
while ! grep -q "light phase DONE" $L; do sleep 120; done
for s in TZ UG ZM MW ZW BW NA LS SZ MA EG AE SA QA OM BH KW TZ_lii UG_lii ZM_lii MW_lii ZW_lii NA_lii LS_lii SZ_lii; do
  [ "$(df -BG --output=avail /workspace | tail -1 | tr -dc 0-9)" -lt 35 ] && { echo "$(date) STOP disk" >> $L; exit 1; }
  t=afme/_test_$s.log; ok=$(grep -c '"ok": true' $t); bad=$(grep -c '"ok": false' $t); tested=$((ok+bad))
  need=$(( tested < 15 ? tested : 15 ))
  if [ "$ok" -ge 1 ] && [ "$ok" -ge "$need" ] && [ "$bad" -eq 0 ]; then
    echo "$(date) $s full start" >> $L
    .afme_venv/bin/python -W ignore afme_cc.py afme_cfg_$s.json 0 300 > afme/_run_$s.log 2>&1
    echo "$(date) $s full $(tail -1 afme/_run_$s.log)" >> $L; .afme_venv/bin/python afme_stage.py >> $L 2>&1
  else echo "$(date) $s full NOT launched (test ok=$ok bad=$bad)" >> $L; fi
done
echo "$(date) wave6 full chain DONE" >> $L
