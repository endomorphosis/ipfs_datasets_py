#!/bin/bash
# Idempotent: upload new amea-* shards, verify each on the Hub (sha256), delete only verified local copies.
cd /workspace/world_caselaw/amea && HF_HUB_DISABLE_PROGRESS_BARS=1 /workspace/hf-venv/bin/python upload.py >> logs/upload.log 2>&1
