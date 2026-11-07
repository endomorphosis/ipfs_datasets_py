#!/bin/bash
# 2026-10-28 03:25 PDT: CA-QC archive r2 test (r1 defective: title_native = site name "Légis Québec"; hidden running
# heads / status dates / duplicated historical notes leaked into text; QCArchive.parse fixed). RAM-gated; held in _review.
# r3 (03:20 PDT): r2 rows were clean but 2 French captures (?langCont=fr) were tagged language=en with "chapter chapitre" titles -> language detection + fr titles/citations.
cd /workspace/world_law/pipeline/scrapers/states
. ./lane_ramgate.sh
L=/workspace/world_law/staging/states/_logs
echo "$(date) test ca_qc_archive r3"
ramgate_run 120 $L/test_ca_qc_archive_r3.out /workspace/world_law/pipeline/venv/bin/python -u run_full.py --source ca_qc_archive --test 20
echo "$(date) test ca_qc_archive r3 rc=$?"
