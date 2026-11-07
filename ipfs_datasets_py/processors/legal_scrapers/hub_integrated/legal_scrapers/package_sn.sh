#!/bin/bash
: "${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT:=$HOME/.ipfs_datasets/legal_collectors}"
exec /workspace/hf-venv/bin/python ${IPFS_DATASETS_LEGAL_COLLECTORS_ROOT}/world_package.py package sn "JO Senegal research snapshot; jo.gouv.sn often unreachable — live+Wayback of official URLs only; secondary seed from archives.sn official JO PDFs."
