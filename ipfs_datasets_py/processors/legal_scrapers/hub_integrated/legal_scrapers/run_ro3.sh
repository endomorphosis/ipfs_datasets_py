#!/bin/bash
: "${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT:=$HOME/.ipfs_datasets/legal_collectors}"
cd ${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT}/scrapers
export MAX_NEW=500 MAX_SECONDS=2400 YEAR_START=2014 YEAR_END=2008
exec /workspace/hf-venv/bin/python -u collect_ro.py
