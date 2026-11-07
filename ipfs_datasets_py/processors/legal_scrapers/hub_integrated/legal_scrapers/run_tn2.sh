#!/bin/bash
: "${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT:=$HOME/.ipfs_datasets/legal_collectors}"
export PYTHONUNBUFFERED=1 MAX_NEW=80 MAX_SECONDS=2400 CDX_LIMIT=200
exec /workspace/hf-venv/bin/python ${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT}/scrapers/collect_tn.py
