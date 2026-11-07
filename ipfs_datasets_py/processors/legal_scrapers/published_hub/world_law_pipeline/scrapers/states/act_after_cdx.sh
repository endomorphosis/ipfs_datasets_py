#!/bin/bash
# Wait for the ACT CDX URL lists, then run the 20-row ACT test into _review (held for manual spot-check; never auto-promoted).
cd /workspace/world_law/pipeline/scrapers/states
while [ ! -s data/act_sl_cdx.txt ]; do sleep 120; done
/workspace/world_law/pipeline/venv/bin/python run_full.py --source au_act_leg --test 20
