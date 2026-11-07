#!/bin/bash
: "${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT:=$HOME/.ipfs_datasets/legal_collectors}"
cd ${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT}/scrapers
export MAX_NEW=200 MAX_SECONDS=7200 ID_RADIUS=6 CDX_LIMIT=2500 SKIP_KNOWN_FAIL=1
exec /workspace/hf-venv/bin/python -u collect_bg.py
