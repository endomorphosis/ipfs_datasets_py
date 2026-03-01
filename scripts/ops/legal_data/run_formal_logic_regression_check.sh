#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$ROOT_DIR"

REPORT_PATH="${REPORT_PATH:-artifacts/formal_logic_tmp_verify/federal/report.json}"
BASELINE_PATH="${BASELINE_PATH:-artifacts/formal_logic_tmp_verify/federal/report.pre_phase1_cleanup.json}"
RECORDS_PATH="${RECORDS_PATH:-artifacts/formal_logic_tmp_verify/federal/records.jsonl}"
LOGIC_PATH="${LOGIC_PATH:-artifacts/formal_logic_tmp_verify/federal/logic.jsonld}"
ENABLE_HYBRID_IR="${ENABLE_HYBRID_IR:-0}"
HYBRID_IR_JURISDICTION_FALLBACK="${HYBRID_IR_JURISDICTION_FALLBACK:-}"
HYBRID_IR_CANONICAL_PREDICATES="${HYBRID_IR_CANONICAL_PREDICATES:-1}"
LIMIT_SEGMENTS="${LIMIT_SEGMENTS:-50}"
ALLOW_SOURCE_CONDITIONED_ROUNDTRIP="${ALLOW_SOURCE_CONDITIONED_ROUNDTRIP:-0}"
ENABLE_LLM_DECODER_PASS="${ENABLE_LLM_DECODER_PASS:-0}"
ENABLE_POST_PARSE_OPTIMIZERS="${ENABLE_POST_PARSE_OPTIMIZERS:-1}"
ENABLE_POST_COMPILE_OPTIMIZERS="${ENABLE_POST_COMPILE_OPTIMIZERS:-1}"
LLM_KG_ENRICHMENT_MAX_RECORDS="${LLM_KG_ENRICHMENT_MAX_RECORDS:-5}"
OPTIMIZER_CHAIN_PLAN="${OPTIMIZER_CHAIN_PLAN:-}"

if [[ $# -ge 1 ]]; then
  BASELINE_PATH="$1"
fi

EXTRA_ARGS=()
OPTIMIZER_ARGS=()

if [[ -n "$OPTIMIZER_CHAIN_PLAN" && -f "$OPTIMIZER_CHAIN_PLAN" ]]; then
  readarray -t _chain_env < <(PYTHONPATH=src:ipfs_datasets_py .venv/bin/python - <<'PY' "$OPTIMIZER_CHAIN_PLAN"
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
d = json.loads(p.read_text(encoding='utf-8'))
env = d.get('env') or {}
print(f"ENABLE_POST_PARSE_OPTIMIZERS={env.get('ENABLE_POST_PARSE_OPTIMIZERS','1')}")
print(f"ENABLE_POST_COMPILE_OPTIMIZERS={env.get('ENABLE_POST_COMPILE_OPTIMIZERS','1')}")
PY
  )
  for kv in "${_chain_env[@]}"; do
    export "$kv"
  done
fi
if [[ "$ENABLE_HYBRID_IR" == "1" ]]; then
  EXTRA_ARGS+=(--enable-hybrid-ir)
  if [[ -n "$HYBRID_IR_JURISDICTION_FALLBACK" ]]; then
    EXTRA_ARGS+=(--hybrid-ir-jurisdiction-fallback "$HYBRID_IR_JURISDICTION_FALLBACK")
  fi
  if [[ "$HYBRID_IR_CANONICAL_PREDICATES" != "1" ]]; then
    EXTRA_ARGS+=(--no-hybrid-ir-canonical-predicates)
  fi
fi

if [[ "$ALLOW_SOURCE_CONDITIONED_ROUNDTRIP" == "1" ]]; then
  EXTRA_ARGS+=(--allow-source-conditioned-roundtrip)
fi

if [[ "$ENABLE_POST_PARSE_OPTIMIZERS" == "1" ]]; then
  OPTIMIZER_ARGS+=(
    --enable-focused-retry-optimizer
    --enable-encoder-quality-retry
  )
fi

if [[ "$ENABLE_POST_COMPILE_OPTIMIZERS" == "1" ]]; then
  OPTIMIZER_ARGS+=(
    --enable-fragment-merging
    --enable-llm-kg-enrichment
    --llm-kg-enrichment-max-records "$LLM_KG_ENRICHMENT_MAX_RECORDS"
  )
fi

if [[ "$ENABLE_LLM_DECODER_PASS" == "1" && "$ENABLE_POST_COMPILE_OPTIMIZERS" == "1" ]]; then
  EXTRA_ARGS+=(
    --enable-llm-decoder-pass
    --llm-decoder-pass-max-records 8
    --llm-decoder-pass-min-semantic-gain -0.2
    --llm-decoder-pass-min-semantic-floor 0.25
    --llm-decoder-pass-min-overlap 0.45
  )
elif [[ "$ENABLE_LLM_DECODER_PASS" == "1" && "$ENABLE_POST_COMPILE_OPTIMIZERS" != "1" ]]; then
  echo "[warn] ENABLE_LLM_DECODER_PASS=1 ignored because ENABLE_POST_COMPILE_OPTIMIZERS!=1"
fi

echo "[1/2] Running formal logic conversion benchmark..."
echo "[config] ENABLE_HYBRID_IR=$ENABLE_HYBRID_IR HYBRID_IR_JURISDICTION_FALLBACK=${HYBRID_IR_JURISDICTION_FALLBACK:-<default>}"
echo "[config] HYBRID_IR_CANONICAL_PREDICATES=$HYBRID_IR_CANONICAL_PREDICATES"
echo "[config] LIMIT_SEGMENTS=$LIMIT_SEGMENTS"
echo "[config] ALLOW_SOURCE_CONDITIONED_ROUNDTRIP=$ALLOW_SOURCE_CONDITIONED_ROUNDTRIP ENABLE_LLM_DECODER_PASS=$ENABLE_LLM_DECODER_PASS"
echo "[config] ENABLE_POST_PARSE_OPTIMIZERS=$ENABLE_POST_PARSE_OPTIMIZERS ENABLE_POST_COMPILE_OPTIMIZERS=$ENABLE_POST_COMPILE_OPTIMIZERS"
PYTHONPATH=src:ipfs_datasets_py .venv/bin/python ipfs_datasets_py/scripts/ops/legal_data/convert_legal_corpus_to_formal_logic.py \
  --input data/federal_laws/us_constitution.jsonld \
  --limit-segments "$LIMIT_SEGMENTS" \
  --enable-clause-decomposition \
  --enable-tdfol \
  --enable-cec \
  --enable-flogic \
  --enable-semantic-roundtrip \
  --embedding-backend sentence-transformers \
  --strict-embedding-backend \
  "${OPTIMIZER_ARGS[@]}" \
  --exclude-heading-segments-from-semantic-metrics \
  --output-json "$REPORT_PATH" \
  --output-jsonl "$RECORDS_PATH" \
  --output-logic-jsonld "$LOGIC_PATH" \
  "${EXTRA_ARGS[@]}"

echo "[2/2] Running low-tail delta analysis..."
if [[ -f "$BASELINE_PATH" ]]; then
  .venv/bin/python ipfs_datasets_py/scripts/ops/legal_data/analyze_formal_logic_low_tail.py \
    --report "$REPORT_PATH" \
    --baseline "$BASELINE_PATH" \
    --top-k 12 \
    --show-worst 8
else
  echo "Baseline not found at: $BASELINE_PATH"
  .venv/bin/python ipfs_datasets_py/scripts/ops/legal_data/analyze_formal_logic_low_tail.py \
    --report "$REPORT_PATH" \
    --top-k 12 \
    --show-worst 8
fi

PREVIEW_MODE="final"
if [[ "$ENABLE_HYBRID_IR" == "1" ]]; then
  PREVIEW_MODE="hybrid"
fi
PREVIEW_PATH="$(dirname "$REPORT_PATH")/constitution_final_decoder_preview.md"
echo "[post] Generating decoder preview (mode=$PREVIEW_MODE) at $PREVIEW_PATH"
python3 ipfs_datasets_py/scripts/ops/legal_data/generate_decoder_preview.py \
  --records "$RECORDS_PATH" \
  --report "$REPORT_PATH" \
  --mode "$PREVIEW_MODE" \
  --max-rows 50 \
  --output "$PREVIEW_PATH"
