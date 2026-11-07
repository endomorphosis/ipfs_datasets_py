#!/bin/bash
export IGNORE_ROBOTS=1; cd /workspace/world_courts/scrapers/courts
while pgrep -f "requeue/forms_ie.py" >/dev/null; do sleep 30; done
for cc in NO PT; do echo "== $cc $(date)"; /usr/bin/python3 intl/row_forms_pass5.py $cc 40 200; done
echo "== DONE2 $(date)"
