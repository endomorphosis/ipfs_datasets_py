#!/bin/bash
# wait for 185-doc test (pid 3714726), restage its files with v2 rules, then start the follow-mode scale run
cd /workspace/world_law/ocr
while kill -0 3714726 2>/dev/null; do sleep 30; done
L=/workspace/world_law/staging/ocr/_logs
ls /workspace/world_law/staging/ocr/RO/*.jsonl > $L/v1_files.txt
python3 restage_ro.py $(cat $L/v1_files.txt) > $L/restage.out 2>&1
# v1 test docs are in done.txt; prune their cached PDFs
for f in _cache/*.pdf; do rm -f "$f"; done
nohup python3 ocr_ro.py --follow --workers 6 --max-workers 8 > $L/scale.out 2>&1 &
echo $! > /workspace/world_law/staging/ocr/_state/scale.pid
