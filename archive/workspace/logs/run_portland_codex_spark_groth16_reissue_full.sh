#!/usr/bin/env bash
set -euo pipefail
cd /home/barberb/HACC/complaint-generator/ipfs_datasets_py
export IPFS_DATASETS_ENABLE_GROTH16=1
python3 scripts/ops/legal_data/reissue_logic_proof_zkp_backend.py \
  --input workspace/municipal_common_crawl_laws/portland_gov_code_current_logic_proof_codex_spark_artifacts/STATE-OR_logic_proof_artifacts.parquet \
  --output-root workspace/municipal_common_crawl_laws/portland_gov_code_current_logic_proof_codex_spark_groth16_artifacts \
  --zkp-backend groth16 \
  --zkp-circuit-version 1 \
  --checkpoint-every 25 \
  --json
