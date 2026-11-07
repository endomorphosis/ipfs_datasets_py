#!/bin/bash
: "${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT:=$HOME/.ipfs_datasets/legal_collectors}"
/workspace/hf-venv/bin/python ${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT}/world_package.py package-upload lk "documents.gov.lk / parliament.lk Acts+Constitution; pdfplumber+OCR for image Acts; honest Section splits. Not legal advice."
