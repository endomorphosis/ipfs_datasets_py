#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"

if [[ -f ".venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

OUT_DIR="${OUT_DIR:-${HOME}/.ipfs_datasets/state_laws/procedural_rules}"
BASE="${BASE:-${OUT_DIR}/us_state_procedural_rules_merged_with_rjina.jsonl}"
OUT="${OUT:-${OUT_DIR}/us_state_procedural_rules_supplemental_rjina_guarded_smoke.jsonl}"
MERGED="${MERGED:-${OUT_DIR}/us_state_procedural_rules_merged_with_rjina_guarded_smoke.jsonl}"
STATES="${STATES:-MI KY}"
MIN_RECORDS="${MIN_RECORDS:-20}"

printf '[1/4] compile checks\n'
PYTHONPATH=. python3 -m py_compile \
  scripts/ops/legal_data/supplement_procedural_rules_via_rjina.py \
  scripts/ops/legal_data/cleanup_procedural_rules_merged.py

printf '[2/4] focused unit tests\n'
PYTHONPATH=. python3 -m pytest -q \
  tests/unit/test_cleanup_procedural_rules_merged.py \
  tests/unit/test_supplement_procedural_rules_via_rjina.py

printf '[3/4] guarded supplement smoke (states: %s)\n' "$STATES"
PYTHONPATH=. python3 scripts/ops/legal_data/supplement_procedural_rules_via_rjina.py \
  --base-jsonl "$BASE" \
  --output-jsonl "$OUT" \
  --merged-output-jsonl "$MERGED" \
  --states $STATES \
  --post-cleanup-merged

printf '[4/4] coverage check (min-records=%s)\n' "$MIN_RECORDS"
PYTHONPATH=. python3 scripts/ops/legal_data/check_state_law_coverage.py --min-records "$MIN_RECORDS"

printf 'guarded procedural rules smoke: PASS\n'
