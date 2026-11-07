#!/bin/bash
: "${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT:=$HOME/.ipfs_datasets/legal_collectors}"
cd ${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT}/scrapers
export PYTHONUNBUFFERED=1
export MAX_NEW=40 MAX_SECONDS=1800 CDX_LIMIT=180
exec /workspace/hf-venv/bin/python collect_gt.py
