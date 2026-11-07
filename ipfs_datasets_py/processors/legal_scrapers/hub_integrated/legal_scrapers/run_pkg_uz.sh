#!/bin/bash
: "${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT:=$HOME/.ipfs_datasets/legal_collectors}"
exec /workspace/hf-venv/bin/python ${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT}/world_package.py package uz "Partial official scrape batch2."
