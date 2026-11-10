#!/bin/bash
# wait for post-2020 URN discovery and the running Toscana full run, then resume Toscana incl. post-2020 URNs (first chunk held in _review)
cd /workspace/world_law/pipeline/scrapers/states
L=/workspace/world_law/staging/states/_logs
while pgrep -f "tos_post2020.py" >/dev/null || pgrep -f "run_full.py --source it_tos_raccolta" >/dev/null; do sleep 120; done
echo "$(date -u +%FT%TZ) post2020 urns: $(wc -l < data/it_tos/urns_post2020.tsv 2>/dev/null)" >> $L/tos_after.out
/workspace/world_law/pipeline/venv/bin/python run_full.py --source it_tos_raccolta --hold-first >> $L/full_it_tos_raccolta_post2020.out 2>&1
echo "$(date -u +%FT%TZ) done" >> $L/tos_after.out
