#!/bin/bash
# 2026-10-26 00:15 PDT: RI r2 test (strict UTF-8 decode w/ cp1252 fallback for section pages + chapter titles, &nbsp; unescaped). RAM-gated.
cd /workspace/world_law/pipeline/scrapers/states
. ./lane_ramgate.sh
L=/workspace/world_law/staging/states/_logs
echo "$(date) test us_ri_gl r2"
ramgate_run 120 $L/test_us_ri_gl_r2.out /workspace/world_law/pipeline/venv/bin/python -u run_full.py --source us_ri_gl --test 20
echo "$(date) test us_ri_gl r2 rc=$?"
