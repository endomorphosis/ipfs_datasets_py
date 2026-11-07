#!/bin/bash
: "${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT:=$HOME/.ipfs_datasets/legal_collectors}"
cd ${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT}
export MAX_NEW=80 MAX_SECONDS=3600 OCR=1 CDX_LIMIT=400 BILL_DETAILS=120 WP_MEDIA_PAGES=10 BON_PAGES=25 PYTHONUNBUFFERED=1
exec /workspace/hf-venv/bin/python -u scrapers/collect_na.py
