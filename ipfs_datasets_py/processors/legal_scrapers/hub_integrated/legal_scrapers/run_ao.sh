#!/bin/bash
: "${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT:=$HOME/.ipfs_datasets/legal_collectors}"
# Angola deepen: digital PDFs + OCR of official scans when ALLOW_OCR=1.
# Uses CDX-timestamped Wayback (prefer_pdf); no Imprensa WAF bypass.
export MAX_NEW="${MAX_NEW:-350}"
export MAX_SECONDS="${MAX_SECONDS:-7200}"
export CDX_LIMIT="${CDX_LIMIT:-2000}"
export GOV_PAGES="${GOV_PAGES:-10}"
export MIN_CATALOG="${MIN_CATALOG:-80}"
export FORCE_CDX="${FORCE_CDX:-1}"
export SKIP_OCR="${SKIP_OCR:-0}"
export ALLOW_OCR="${ALLOW_OCR:-1}"
export INCLUDE_IMPRENSA_CDX="${INCLUDE_IMPRENSA_CDX:-1}"
export OCR_MAX_PAGES="${OCR_MAX_PAGES:-40}"
export OMP_THREAD_LIMIT="${OMP_THREAD_LIMIT:-1}"
exec /workspace/hf-venv/bin/python ${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT}/scrapers/collect_ao.py
