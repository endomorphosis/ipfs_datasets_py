#!/bin/bash
# live crawler tests + full runs, appended to wave 6 without exceeding 3 afme crawls:
#  tests start after the light phase is DONE (then at most PR-or-wave6-full + hubscan + this = 3)
#  full runs start after afme_w6_full_chain.sh (pid 135089) exits (then hubscan + this = 2). Log afme/_wave6.log
cd /workspace/world_law/out; export ARCHIVE_LANE=afme; L=afme/_wave6.log
while ! grep -q "light phase DONE" $L; do sleep 60; done
for c in UG AE; do
  grep -q "^DONE" afme/_test_live_$c.log 2>/dev/null && continue
  .afme_venv/bin/python -W ignore afme_live.py afme_live_$c.json test > afme/_test_live_$c.log 2>&1
  echo "$(date) live_$c test $(tail -1 afme/_test_live_$c.log)" >> $L
done
while kill -0 135089 2>/dev/null || pgrep -f afme_w6_full_chain.sh >/dev/null; do sleep 120; done
for c in UG AE; do
  ok=$(grep -c '"ok": true' afme/_test_live_$c.log); bad=$(grep -c '"ok": false' afme/_test_live_$c.log)
  [ "$(df -BG --output=avail /workspace | tail -1 | tr -dc 0-9)" -lt 35 ] && { echo "$(date) STOP disk" >> $L; exit 1; }
  if [ "$ok" -ge 1 ] && [ "$bad" -eq 0 ]; then echo "$(date) live_$c full start" >> $L
    .afme_venv/bin/python -W ignore afme_live.py afme_live_$c.json > afme/_run_live_$c.log 2>&1
    echo "$(date) live_$c full $(tail -1 afme/_run_live_$c.log)" >> $L; .afme_venv/bin/python afme_stage.py >> $L 2>&1
  else echo "$(date) live_$c full NOT launched (ok=$ok bad=$bad)" >> $L; fi
done
echo "$(date) live chain DONE" >> $L
