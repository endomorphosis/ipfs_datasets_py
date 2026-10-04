#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$ROOT_DIR"

TMP_DIR="${TMP_DIR:-/tmp/formal_logic_proof_audit_integration_matrix_smoke}"
REPORT_PATH="${REPORT_PATH:-$TMP_DIR/matrix_report.json}"
mkdir -p "$TMP_DIR"

run_mode() {
  local mode_name="$1"
  local expected_json="$2"
  local expected_markdown="$3"
  shift 3

  local mode_dir="$TMP_DIR/$mode_name"
  local run_log="$mode_dir/run.log"
  local summary_path="$mode_dir/summary.json"
  local triage_json_path="$mode_dir/triage.json"
  local triage_markdown_path="$mode_dir/triage.md"
  local canary_log_path="$mode_dir/canary.log"
  local regression_log_path="$mode_dir/regression.log"

  mkdir -p "$mode_dir"

  echo "[matrix] Running mode: $mode_name"
  set +e
  env \
    SUMMARY_PATH="$summary_path" \
    TRIAGE_JSON_PATH="$triage_json_path" \
    TRIAGE_MARKDOWN_PATH="$triage_markdown_path" \
    CANARY_LOG_PATH="$canary_log_path" \
    REGRESSION_LOG_PATH="$regression_log_path" \
    "$@" \
    bash ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_proof_audit_integration_smoke.sh \
    >"$run_log" 2>&1
  local exit_code=$?
  set -e

  local summary_exists=0
  local triage_json_exists=0
  local triage_markdown_exists=0
  [[ -f "$summary_path" ]] && summary_exists=1
  [[ -f "$triage_json_path" ]] && triage_json_exists=1
  [[ -f "$triage_markdown_path" ]] && triage_markdown_exists=1

  local expected_json_i=0
  local expected_markdown_i=0
  [[ "$expected_json" == "1" ]] && expected_json_i=1
  [[ "$expected_markdown" == "1" ]] && expected_markdown_i=1

  local artifacts_match=1
  if [[ "$triage_json_exists" -ne "$expected_json_i" ]]; then
    artifacts_match=0
  fi
  if [[ "$triage_markdown_exists" -ne "$expected_markdown_i" ]]; then
    artifacts_match=0
  fi

  local mode_passed=0
  if [[ "$exit_code" -eq 0 && "$summary_exists" -eq 1 && "$artifacts_match" -eq 1 ]]; then
    mode_passed=1
  fi

  PYTHONPATH=src:ipfs_datasets_py .venv/bin/python - <<'PY' \
    "$TMP_DIR" "$mode_name" "$exit_code" "$mode_passed" "$summary_exists" \
    "$triage_json_exists" "$triage_markdown_exists" "$expected_json_i" "$expected_markdown_i" \
    "$summary_path" "$triage_json_path" "$triage_markdown_path" "$run_log"
import json
import sys
from pathlib import Path

(
    tmp_dir,
    mode_name,
    exit_code,
    mode_passed,
    summary_exists,
    triage_json_exists,
    triage_markdown_exists,
    expected_json,
    expected_markdown,
    summary_path,
    triage_json_path,
    triage_markdown_path,
    run_log,
) = sys.argv[1:]

report_path = Path(tmp_dir) / "matrix_report.json"
if report_path.exists():
    report = json.loads(report_path.read_text(encoding="utf-8"))
else:
    report = {"modes": []}

report["modes"] = [m for m in report.get("modes", []) if m.get("mode") != mode_name]
report["modes"].append(
    {
        "mode": mode_name,
        "passed": bool(int(mode_passed)),
        "integration_exit_code": int(exit_code),
        "artifacts": {
            "summary": {"exists": bool(int(summary_exists)), "path": summary_path},
            "triage_json": {
                "exists": bool(int(triage_json_exists)),
                "expected": bool(int(expected_json)),
                "path": triage_json_path,
            },
            "triage_markdown": {
                "exists": bool(int(triage_markdown_exists)),
                "expected": bool(int(expected_markdown)),
                "path": triage_markdown_path,
            },
            "run_log": {"path": run_log},
        },
    }
)

report["overall_passed"] = all(bool(m.get("passed")) for m in report["modes"])
report_path.parent.mkdir(parents=True, exist_ok=True)
report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
PY
}

rm -f "$REPORT_PATH"

run_mode "full" "1" "1"
run_mode "json_only" "1" "0" RUN_TRIAGE_MARKDOWN=0
run_mode "summary_only" "0" "0" RUN_TRIAGE_AFTER_SUMMARY=0

echo "[matrix] Report: $REPORT_PATH"
PYTHONPATH=src:ipfs_datasets_py .venv/bin/python - <<'PY' "$REPORT_PATH"
import json
import sys

path = sys.argv[1]
payload = json.load(open(path, encoding="utf-8"))
print(f"overall_passed={str(bool(payload.get('overall_passed'))).lower()}")
for mode in payload.get("modes", []):
    print(
        f"mode={mode['mode']} passed={str(bool(mode.get('passed'))).lower()} "
        f"exit_code={mode.get('integration_exit_code')}"
    )
PY

if PYTHONPATH=src:ipfs_datasets_py .venv/bin/python - <<'PY' "$REPORT_PATH"
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
raise SystemExit(0 if payload.get("overall_passed") else 1)
PY
then
  echo "[matrix] PASS"
  exit 0
fi

echo "[matrix] FAIL"
exit 1