#!/bin/bash
: "${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT:=$HOME/.ipfs_datasets/legal_collectors}"
cd ${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT}/scrapers
export MAX_NEW=800 MAX_SECONDS=4500 YEAR_START=2023 YEAR_END=1990
exec /workspace/hf-venv/bin/python -u collect_ro.py
