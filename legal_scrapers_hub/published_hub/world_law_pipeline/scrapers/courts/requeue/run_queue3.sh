#!/bin/bash
# post-restore requeue 2026-11-01: NO, PT, then IE full page list; sequential, polite (robots_policy crawl delays)
export IGNORE_ROBOTS=1; cd /workspace/world_courts/scrapers/courts; PY=/workspace/world_law/pipeline/venv/bin/python
touch /tmp/sg_seeds.txt
for cc in NO PT; do echo "== $cc $(date)"; nice $PY -u intl/row_forms_pass5.py $cc 40 200; done
echo "== IE $(date)"; nice $PY -u requeue/forms_ie.py 1845 600
echo "== DONE3 $(date)"
