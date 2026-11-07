#!/bin/bash
: "${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT:=$HOME/.ipfs_datasets/legal_collectors}"
cd ${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT}
exec /workspace/hf-venv/bin/python restore_and_package.py package-upload cy "GPO mof.gov.cy HTML resume. PDF extract enabled; cylaw.org not used. Not legal advice."
