#!/usr/bin/env bash
set -u
cd /home/barberb/HACC/complaint-generator/ipfs_datasets_py
export PYTHONUNBUFFERED=1
echo "started $(date -Is) pid=$$"
exec python3 scripts/ops/legal_data/build_portland_logic_proof_artifacts.py \
  --input workspace/municipal_common_crawl_laws/portland_gov_code_current_canonical_artifacts/STATE-OR.parquet \
  --output-root workspace/municipal_common_crawl_laws/portland_gov_code_current_logic_proof_codex_spark_artifacts \
  --llm-assisted \
  --llm-provider codex_cli \
  --llm-model gpt-5.3-codex-spark \
  --llm-timeout 90 \
  --checkpoint-every 5 \
  --json
