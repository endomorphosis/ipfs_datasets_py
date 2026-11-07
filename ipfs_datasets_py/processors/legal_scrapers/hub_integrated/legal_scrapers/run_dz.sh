#!/bin/bash
: "${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT:=$HOME/.ipfs_datasets/legal_collectors}"
cd ${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT}/scrapers
export PYTHONUNBUFFERED=1
export MAX_NEW=50 MAX_SECONDS=1500 YEAR_FROM=2022 YEAR_TO=2027 JO_MAX_NUM=40
exec /workspace/hf-venv/bin/python collect_dz.py
