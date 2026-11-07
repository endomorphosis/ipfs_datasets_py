#!/bin/bash
: "${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT:=$HOME/.ipfs_datasets/legal_collectors}"
cd ${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT}/scrapers
export YEAR_START=2022 YEAR_END=1993 MAX_CATALOG=8000 MAX_NEW=2000 MAX_SECONDS=14400
exec /workspace/hf-venv/bin/python -u collect_si.py
