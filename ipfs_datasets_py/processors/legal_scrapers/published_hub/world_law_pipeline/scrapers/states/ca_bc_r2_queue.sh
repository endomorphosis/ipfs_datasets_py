#!/bin/bash
# 2026-10-29 03:19 PDT r2, 03:27 PDT r3, 03:35 PDT r4 (act titles kept from h1; PIT titles, doc_type, copyright/link chrome; bak_20261029_0335_bcr2): CA-BC archive 20-row test after r1 failed (20x lxml ValueError on <?xml encoding?> XHTML; fixed in
# adapters.py _doc_html, bak_20261029_0320_bcxmldecl; BC footer copyright line stripped). RAM-gated; output HELD in _review.
cd /workspace/world_law/pipeline/scrapers/states
. ./lane_ramgate.sh
L=/workspace/world_law/staging/states/_logs; PY=/workspace/world_law/pipeline/venv/bin/python
if pgrep -f "run_full.py --source ca_bc_archive( |$)" >/dev/null; then echo "$(date) ca_bc_archive already running"; exit 0; fi
ramgate_run 130 $L/test_ca_bc_archive.out $PY run_full.py --source ca_bc_archive --test 20; echo "$(date) BC_R2_TEST_END rc=$?"
