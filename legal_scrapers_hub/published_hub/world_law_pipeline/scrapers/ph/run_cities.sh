#!/bin/bash
# Fingerprint then crawl PH cities (resumable via _state/done_cities.jsonl)
cd /workspace/world_law/pipeline/scrapers/ph
export PH_PLACES=/workspace/world_law/staging/ph/_state/cities.jsonl
[ -s /workspace/world_law/staging/ph/_state/fingerprint_cities.jsonl ] || PH_FP_OUT=/workspace/world_law/staging/ph/_state/fingerprint_cities.jsonl /workspace/world_law/pipeline/venv/bin/python -W ignore fingerprint.py 5000
OMP_THREAD_LIMIT=1 PH_OCR=2 PH_OCR_CAP=15 PH_OCR_PAGES=2 /workspace/world_law/pipeline/venv/bin/python -W ignore ph_crawl.py --workers 8 --done /workspace/world_law/staging/ph/_state/done_cities.jsonl
/workspace/world_law/pipeline/venv/bin/python wayback_deferred.py
