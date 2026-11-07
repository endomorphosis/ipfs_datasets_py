#!/bin/bash
: "${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT:=$HOME/.ipfs_datasets/legal_collectors}"
export MAX_NEW=120 MAX_SECONDS=3600 ARCHIVES_PAGES=8 CDX_LIMIT=0
exec /workspace/hf-venv/bin/python ${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT}/scrapers/collect_sn.py
