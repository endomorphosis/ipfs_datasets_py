#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$ROOT_DIR"

PYTHONPATH=src:ipfs_datasets_py \
  /home/barberb/municipal_scrape_workspace/.venv/bin/python \
  ipfs_datasets_py/scripts/ops/legal_data/run_hybrid_v2_pipeline.py "$@"
