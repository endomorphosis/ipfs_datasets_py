#!/bin/bash
: "${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT:=$HOME/.ipfs_datasets/legal_collectors}"
export MAX_NEW="${MAX_NEW:-250}" MAX_SECONDS="${MAX_SECONDS:-7200}" CDX_LIMIT="${CDX_LIMIT:-5000}"
exec /workspace/hf-venv/bin/python ${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT}/scrapers/collect_zw.py
