#!/bin/bash
: "${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT:=$HOME/.ipfs_datasets/legal_collectors}"
cd ${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT}/scrapers
export PYTHONUNBUFFERED=1
export REPROCESS="${REPROCESS:-1}"
export MAX_NEW="${MAX_NEW:-100}"
export REPROCESS_MAX="${REPROCESS_MAX:-80}"
export MAX_SECONDS="${MAX_SECONDS:-4200}"
export CDX_LIMIT="${CDX_LIMIT:-400}"
exec /workspace/hf-venv/bin/python collect_md.py
