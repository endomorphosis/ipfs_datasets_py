#!/bin/bash
: "${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT:=$HOME/.ipfs_datasets/legal_collectors}"
cd ${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT}
exec /workspace/hf-venv/bin/python local_package.py package na "Partial official scrape: laws.parliament.na Bills + BoN + parliament.na. lac.org.na skipped; gazettes.gov.na/legal.mca.gov.na unreachable; gov.na/moj gaps; NamibLII CF-challenged. OCR when OCR=1. Not legal advice."
