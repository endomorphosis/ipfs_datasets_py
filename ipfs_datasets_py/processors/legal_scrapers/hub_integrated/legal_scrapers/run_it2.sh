#!/bin/bash
: "${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT:=$HOME/.ipfs_datasets/legal_collectors}"
cd ${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT}/scrapers
export YEAR_START=2014 YEAR_END=2005 MAX_NEW=500 MAX_SECONDS=3600
exec /workspace/hf-venv/bin/python -u collect_it.py
