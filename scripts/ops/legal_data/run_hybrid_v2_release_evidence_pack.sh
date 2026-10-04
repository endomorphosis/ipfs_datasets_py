#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$ROOT_DIR"

DATE_TAG="$(date +%Y%m%d)"
RELEASE_LABEL="${RELEASE_LABEL:-ws10_release_${DATE_TAG}}"
OUTPUT_DIR="${OUTPUT_DIR:-$ROOT_DIR/artifacts/formal_logic_tmp_verify/federal/${RELEASE_LABEL}}"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"

mkdir -p "$OUTPUT_DIR"

echo "[evidence-pack] output_dir=$OUTPUT_DIR"

echo "[evidence-pack 1/3] running reasoner pytest gate..."
PYTHONPATH="$ROOT_DIR/src:$ROOT_DIR/ipfs_datasets_py" \
  "$PYTHON_BIN" -m pytest \
  "$ROOT_DIR/ipfs_datasets_py/tests/reasoner/test_hybrid_v2_blueprint.py" \
  "$ROOT_DIR/ipfs_datasets_py/tests/reasoner/test_hybrid_v2_cli.py" \
  "$ROOT_DIR/ipfs_datasets_py/tests/reasoner/test_hybrid_v2_parse_replay.py" \
  "$ROOT_DIR/ipfs_datasets_py/tests/reasoner/test_hybrid_v2_compiler_parity.py" \
  "$ROOT_DIR/ipfs_datasets_py/tests/reasoner/test_hybrid_v2_query_api_matrix.py" \
  "$ROOT_DIR/ipfs_datasets_py/tests/reasoner/test_kg_enrichment_adapter.py" \
  "$ROOT_DIR/ipfs_datasets_py/tests/reasoner/test_prover_backend_registry.py" \
  -q > "$OUTPUT_DIR/pytest_reasoner_release_gate.txt"

echo "[evidence-pack 2/3] running backend smoke matrix..."
PYTHONPATH="$ROOT_DIR/src:$ROOT_DIR/ipfs_datasets_py" \
  "$PYTHON_BIN" - <<'PY' "$OUTPUT_DIR"
import json
import sys
from pathlib import Path

from ipfs_datasets_py.processors.legal_data.reasoner.v2_cli import run_v2_cli

out_dir = Path(sys.argv[1])
out_dir.mkdir(parents=True, exist_ok=True)

for backend in ("mock_smt", "mock_fol"):
    payload = run_v2_cli(
        sentences=["Controller shall report breach within 24 hours."],
        jurisdiction="us/federal",
        enable_optimizer=True,
        enable_kg=True,
        enable_prover=True,
        prover_backend_id=backend,
    )
    summary = payload.get("summary") or {}
    result = {
        "backend": backend,
        "summary": summary,
        "passed": (
            summary.get("total") == 1
            and summary.get("ok") == 1
            and summary.get("error") == 0
            and summary.get("prover_backend_id") == backend
            and summary.get("schema_version") == "1.0"
        ),
    }
    if not result["passed"]:
        raise SystemExit(f"backend smoke failed: {backend}: {result}")
    (out_dir / f"backend_smoke_{backend}.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
PY

echo "[evidence-pack 3/3] running fixture batch smoke..."
PYTHONPATH="$ROOT_DIR/src:$ROOT_DIR/ipfs_datasets_py" \
  "$PYTHON_BIN" "$ROOT_DIR/ipfs_datasets_py/scripts/ops/legal_data/run_hybrid_v2_pipeline.py" \
  --input-jsonl "$ROOT_DIR/ipfs_datasets_py/tests/reasoner/fixtures/hybrid_v2_cli_batch_sentences.jsonl" \
  --sentence-field sentence \
  --output-json "$OUTPUT_DIR/hybrid_v2_cli_batch_smoke.json" \
  --pretty >/tmp/hybrid_v2_release_pack_batch_stdout.log

cat > "$OUTPUT_DIR/EVIDENCE_PACK_MANIFEST.txt" <<EOF
output_dir=$OUTPUT_DIR
pytest_log=$OUTPUT_DIR/pytest_reasoner_release_gate.txt
backend_smoke_mock_smt=$OUTPUT_DIR/backend_smoke_mock_smt.json
backend_smoke_mock_fol=$OUTPUT_DIR/backend_smoke_mock_fol.json
batch_smoke=$OUTPUT_DIR/hybrid_v2_cli_batch_smoke.json
EOF

echo "[evidence-pack] manifest: $OUTPUT_DIR/EVIDENCE_PACK_MANIFEST.txt"
echo "[evidence-pack] done"
