#!/bin/bash
: "${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT:=$HOME/.ipfs_datasets/legal_collectors}"
cd ${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT}/scrapers
export MAX_NEW=200 MAX_SECONDS=7200 ID_RADIUS=60
exec /workspace/hf-venv/bin/python -u collect_bg.py
