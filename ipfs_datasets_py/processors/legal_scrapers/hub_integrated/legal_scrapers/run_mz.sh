#!/bin/bash
: "${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT:=$HOME/.ipfs_datasets/legal_collectors}"
export PYTHONUNBUFFERED=1
export MAX_NEW="${MAX_NEW:-100}"
export MAX_SECONDS="${MAX_SECONDS:-5400}"
export CDX_LIMIT="${CDX_LIMIT:-300}"
export MIN_CATALOG="${MIN_CATALOG:-60}"
export MIN_PARL="${MIN_PARL:-15}"
export OCR="${OCR:-1}"
export OCR_MAX_PAGES="${OCR_MAX_PAGES:-30}"
export FORCE_CDX="${FORCE_CDX:-1}"
exec /workspace/hf-venv/bin/python ${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT}/scrapers/collect_mz.py
