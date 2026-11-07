#!/bin/bash
: "${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT:=$HOME/.ipfs_datasets/legal_collectors}"
cd ${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT}/scrapers
export MAX_NEW=80 MAX_SECONDS=2400
exec /workspace/hf-venv/bin/python -u collect_cy.py
