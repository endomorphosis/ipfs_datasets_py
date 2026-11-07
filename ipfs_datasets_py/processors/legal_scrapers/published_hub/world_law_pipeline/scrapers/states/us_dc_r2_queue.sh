#!/bin/bash
# 2026-10-26 15:14 PDT: DC r2 test (r1 rejected: 4/20 '[Repealed]'/'[Recodified]' chapters had in_force=True; USDCCode.fetch now sets None). RAM-gated; held in _review.
cd /workspace/world_law/pipeline/scrapers/states
. ./lane_ramgate.sh
L=/workspace/world_law/staging/states/_logs
echo "$(date) test us_dc_code r2"
ramgate_run 120 $L/test_us_dc_code_r2.out /workspace/world_law/pipeline/venv/bin/python -u run_full.py --source us_dc_code --test 20
echo "$(date) test us_dc_code r2 rc=$?"
