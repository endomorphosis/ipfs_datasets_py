#!/bin/bash
: "${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT:=$HOME/.ipfs_datasets/legal_collectors}"
set -euo pipefail
export MAX_NEW=220
export MAX_SECONDS=9000
export SPM_PAGES=40
export SPM_OCR=1
export SPM_OCR_MAX_PAGES=4
export PRC_LOIS_PAGES=5
export PRC_ORD_PAGES=2
export PRC_DEC_PAGES=2
export PRC_DOCS_PAGES=0
export CDX_LIMIT=20
export CATALOG_MIN=300
export OMP_THREAD_LIMIT=1
cd ${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT}/scrapers
exec /workspace/hf-venv/bin/python -u collect_cm.py
