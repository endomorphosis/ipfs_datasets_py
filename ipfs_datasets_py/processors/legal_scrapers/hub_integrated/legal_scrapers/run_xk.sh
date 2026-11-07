#!/bin/bash
: "${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT:=$HOME/.ipfs_datasets/legal_collectors}"
export PYTHONUNBUFFERED=1 MAX_NEW=80 MAX_SECONDS=2400 ACT_LIMIT=500 SEARCH_PAGES=12 ALLOW_NOTICES=0
exec /workspace/hf-venv/bin/python -u ${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT}/scrapers/collect_xk.py
