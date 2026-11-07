#!/bin/bash
: "${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT:=$HOME/.ipfs_datasets/legal_collectors}"
cd ${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT}/scrapers
export YEAR_START=2004 YEAR_END=1861 MAX_NEW=2000 MAX_SECONDS=14400
exec /workspace/hf-venv/bin/python -u collect_it.py
