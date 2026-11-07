#!/bin/bash
: "${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT:=$HOME/.ipfs_datasets/legal_collectors}"
cd ${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT}/scrapers
export MAX_NEW=600 MAX_SECONDS=3600 YEAR_START=2022 YEAR_END=2015
exec /workspace/hf-venv/bin/python -u collect_ro.py
