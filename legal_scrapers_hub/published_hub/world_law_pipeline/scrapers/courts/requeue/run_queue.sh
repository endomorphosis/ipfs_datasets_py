#!/bin/bash
# sequential robots re-queue (IGNORE_ROBOTS=1), one job at a time
export IGNORE_ROBOTS=1; cd /workspace/world_courts/scrapers/courts
while pgrep -f robots_requeue_cos.py >/dev/null; do sleep 30; done
for cc in NO PT; do echo "== $cc $(date)"; /usr/bin/python3 intl/row_forms_pass5.py $cc 40 200; done
echo "== IE $(date)"; /usr/bin/python3 requeue/forms_ie.py 300 300
echo "== DONE $(date)"
