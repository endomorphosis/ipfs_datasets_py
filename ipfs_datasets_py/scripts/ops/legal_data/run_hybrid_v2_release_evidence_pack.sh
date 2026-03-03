#!/usr/bin/env bash
# WS12-07: Unified Release Evidence Pack v2
# Runs all WS12 test gates and generates the release evidence manifest.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# repo root is 4 levels up: legal_data/ -> ops/ -> scripts/ -> ipfs_datasets_py/ -> repo root
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"

cd "${REPO_ROOT}"

echo "============================================================"
echo " WS12 Release Evidence Pack v2"
echo " Repo root: ${REPO_ROOT}"
echo "============================================================"
echo ""

PASS=0
FAIL=0

run_gate() {
    local label="$1"
    local cmd="$2"
    echo "--- ${label} ---"
    if eval "${cmd}"; then
        echo "PASS: ${label}"
        PASS=$((PASS + 1))
    else
        echo "FAIL: ${label}"
        FAIL=$((FAIL + 1))
    fi
    echo ""
}

echo "=== WS12 Test Gates ==="
echo ""

run_gate "HL-WS12-01: Policy Pack Schema" \
    "python -m pytest ipfs_datasets_py/tests/reasoner/test_policy_pack_schema.py -q --tb=short"

run_gate "HL-WS12-02: Policy Resolver Determinism" \
    "python -m pytest ipfs_datasets_py/tests/reasoner/test_policy_resolver_determinism.py -q --tb=short"

run_gate "HL-WS12-03: Jurisdiction Replay Matrix" \
    "python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_jurisdiction_matrix.py -q --tb=short"

run_gate "HL-WS12-04: Conflict Reason Codes" \
    "python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_conflict_reason_codes.py -q --tb=short"

run_gate "HL-WS12-05: Conflict Triage Report Builder" \
    "python -m pytest ipfs_datasets_py/tests/reasoner/test_conflict_triage_report_builder.py -q --tb=short"

run_gate "HL-WS12-06: Performance Budget Sentinel" \
    "python -m pytest ipfs_datasets_py/tests/reasoner/test_perf_budget_sentinel.py -q --tb=short"

run_gate "HL-WS12-07: Release Evidence Pack" \
    "python -m pytest ipfs_datasets_py/tests/reasoner/test_release_evidence_pack_v2.py -q --tb=short"

echo "=== Evidence Manifest ==="
echo ""
python ipfs_datasets_py/scripts/ops/legal_data/build_hybrid_v2_evidence_manifest.py

echo ""
echo "============================================================"
echo " Summary: ${PASS} passed, ${FAIL} failed"
if [ "${FAIL}" -gt 0 ]; then
    echo " STATUS: FAIL"
    exit 1
else
    echo " STATUS: PASS - WS12 release evidence pack complete"
fi
echo "============================================================"
