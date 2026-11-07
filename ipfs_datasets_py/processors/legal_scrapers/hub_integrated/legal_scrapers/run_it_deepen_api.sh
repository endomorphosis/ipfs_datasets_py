#!/bin/bash
: "${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT:=$HOME/.ipfs_datasets/legal_collectors}"
cd ${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT}/scrapers
export MAX_NEW="${MAX_NEW:-300}" MAX_SECONDS="${MAX_SECONDS:-3600}" MAX_ARTS_PER_LAW="${MAX_ARTS_PER_LAW:-60}"
exec /workspace/hf-venv/bin/python -u deepen_it_idarticolo.py
