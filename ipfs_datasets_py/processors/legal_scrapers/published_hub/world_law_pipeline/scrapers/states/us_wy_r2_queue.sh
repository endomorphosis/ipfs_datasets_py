#!/bin/bash
# 2026-10-26 00:50 PDT: WY r2 test (r1 00:36 STAGE FAILED: content_format 'pdf' not in schema; _us_rec now maps pdf->pdf_text). RAM-gated.
cd /workspace/world_law/pipeline/scrapers/states
. ./lane_ramgate.sh
L=/workspace/world_law/staging/states/_logs
echo "$(date) test us_wy_statutes r2"
ramgate_run 150 $L/test_us_wy_statutes_r2.out /workspace/world_law/pipeline/venv/bin/python -u run_full.py --source us_wy_statutes --test 20
echo "$(date) test us_wy_statutes r2 rc=$?"
