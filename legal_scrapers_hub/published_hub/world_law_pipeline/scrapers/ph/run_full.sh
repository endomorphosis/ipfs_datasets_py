#!/bin/bash
# Resumable: skips place_ids in staging/ph/_state/done.jsonl
cd /workspace/world_law/pipeline/scrapers/ph
OMP_THREAD_LIMIT=1 PH_OCR=2 PH_OCR_CAP=15 PH_OCR_PAGES=2 setsid nohup /workspace/world_law/pipeline/venv/bin/python -W ignore ph_crawl.py --workers 8 >> /workspace/world_law/staging/ph/_logs/full_run.log 2>&1 < /dev/null &
echo $!
