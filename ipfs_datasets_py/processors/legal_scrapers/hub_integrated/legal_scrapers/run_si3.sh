#!/bin/bash
: "${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT:=$HOME/.ipfs_datasets/legal_collectors}"
cd ${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT}/scrapers
# Resume remaining from existing 8015 catalog first (no rediscover)
export MAX_NEW=2000 MAX_SECONDS=14400
exec /workspace/hf-venv/bin/python -u collect_si.py
