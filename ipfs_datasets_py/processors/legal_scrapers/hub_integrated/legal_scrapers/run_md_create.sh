#!/bin/bash
: "${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT:=$HOME/.ipfs_datasets/legal_collectors}"
export PYTHONUNBUFFERED=1 MAX_NEW=60 MAX_SECONDS=2000 CDX_LIMIT=150
exec /workspace/hf-venv/bin/python -u ${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT}/scrapers/collect_md.py
