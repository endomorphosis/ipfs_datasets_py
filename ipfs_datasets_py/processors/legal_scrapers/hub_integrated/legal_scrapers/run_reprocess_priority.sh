#!/bin/bash
: "${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT:=$HOME/.ipfs_datasets/legal_collectors}"
set -e
export REFETCH=1 OCR=1 MAX_OCR=8 MAX_REFETCH=25 OCR_PAGES=25
cd ${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT}
/workspace/hf-venv/bin/python scrapers/reprocess_pdf_articles.py tn 2>&1 | tee logs/reprocess_tn.log
/workspace/hf-venv/bin/python scrapers/reprocess_pdf_articles.py et 2>&1 | tee logs/reprocess_et.log
/workspace/hf-venv/bin/python scrapers/reprocess_pdf_articles.py fj 2>&1 | tee logs/reprocess_fj.log
/workspace/hf-venv/bin/python scrapers/reprocess_pdf_articles.py jm 2>&1 | tee logs/reprocess_jm.log
/workspace/hf-venv/bin/python scrapers/reprocess_pdf_articles.py la 2>&1 | tee logs/reprocess_la.log
echo ALL_DONE
