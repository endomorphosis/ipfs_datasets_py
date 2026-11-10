#!/bin/bash
# 2026-10-25 19:10: KY resume for chapters missing upstream (US HF cite skip: chapters with >=3 good HF sections are skipped).
cd /workspace/world_law/pipeline/scrapers/states
. ./lane_ramgate.sh
L=/workspace/world_law/staging/states/_logs; PY=/workspace/world_law/pipeline/venv/bin/python
echo "$(date) full us_ky_krs (resume, gap chapters)"; ramgate_run 130 $L/full_us_ky_krs.out $PY -u run_full.py --source us_ky_krs; echo "$(date) rc=$?"
echo "$(date) KYRESUME_END"
