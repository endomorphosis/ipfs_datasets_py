#!/bin/bash
# 2026-10-25: US batch 3 full runs, sequenced to keep lane RSS under ~1 GB:
# NE then PA (short runs, multi-MB pages), then MD + LA together (long, ~1 day each, ~100-160 MB each).
cd /workspace/world_law/pipeline/scrapers/states
L=/workspace/world_law/staging/states/_logs
PY=/workspace/world_law/pipeline/venv/bin/python
run() { pgrep -f "run_full.py --source $1\$" >/dev/null && { echo "$(date) $1 already running, skip"; return; }
        echo "$(date) start $1"; $PY -u run_full.py --source $1 > $L/full_$1.out 2>&1; echo "$(date) end $1 rc=$?"; }
run us_ne_statutes
run us_pa_consolidated
run us_md_code & run us_la_laws & wait
