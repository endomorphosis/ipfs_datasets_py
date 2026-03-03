"""Tests for WS12-03: Multi-Jurisdiction Replay Matrix.

Covers deterministic proof ID stability and cross-jurisdiction compliance
checking across US-FEDERAL, US-CA, and US-NY policy profiles.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from reasoner.hybrid_v2_blueprint import (
    parse_cnl_to_ir,
    check_compliance,
    clear_v2_proof_store,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "jurisdiction_replay_matrix_v1.json"


def _load_cases():
    with FIXTURE_PATH.open() as fh:
        return json.load(fh)


CASES = _load_cases()


@pytest.fixture(autouse=True)
def reset_proof_store():
    clear_v2_proof_store()
    yield
    clear_v2_proof_store()


def _run_case(case: dict) -> dict:
    ir = parse_cnl_to_ir(case["sentence"], jurisdiction=case["jurisdiction"])
    return check_compliance(
        {"ir": ir, "facts": {}, "events": list(case.get("events") or [])},
        {},
    )


class TestMultiJurisdictionReplayMatrix:
    """WS12-03: compliance checks across multiple jurisdictions are deterministic."""

    @pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
    def test_status_matches_expected(self, case):
        result = _run_case(case)
        assert result["status"] == case["expected_status"], (
            f"[{case['id']}] {case['jurisdiction']}: expected {case['expected_status']!r}, "
            f"got {result['status']!r}"
        )

    @pytest.mark.parametrize(
        "case",
        [c for c in CASES if c.get("expected_violation_type")],
        ids=[c["id"] for c in CASES if c.get("expected_violation_type")],
    )
    def test_violation_type_matches(self, case):
        result = _run_case(case)
        assert result["violations"], f"[{case['id']}] Expected violations but got none"
        types = {v["type"] for v in result["violations"]}
        assert case["expected_violation_type"] in types, (
            f"[{case['id']}] Expected violation type {case['expected_violation_type']!r} "
            f"not found in {types}"
        )

    @pytest.mark.parametrize(
        "case",
        [c for c in CASES if c.get("expected_proof_id_stable")],
        ids=[c["id"] for c in CASES if c.get("expected_proof_id_stable")],
    )
    def test_proof_id_determinism(self, case):
        """Same case run twice produces the same proof_id."""
        clear_v2_proof_store()
        result1 = _run_case(case)
        proof_id_1 = result1["proof_id"]

        clear_v2_proof_store()
        result2 = _run_case(case)
        proof_id_2 = result2["proof_id"]

        assert proof_id_1 == proof_id_2, (
            f"[{case['id']}] Proof ID not deterministic: {proof_id_1!r} != {proof_id_2!r}"
        )

    def test_all_required_jurisdictions_represented(self):
        """Fixture must cover US-FEDERAL, US-CA, and US-NY."""
        jurisdictions = {c["jurisdiction"] for c in CASES}
        for required in ("US-FEDERAL", "US-CA", "US-NY"):
            assert required in jurisdictions, f"Jurisdiction {required!r} missing from fixture"

    def test_both_compliant_and_non_compliant_cases_present(self):
        statuses = {c["expected_status"] for c in CASES}
        assert "compliant" in statuses, "No compliant cases in fixture"
        assert "non_compliant" in statuses, "No non_compliant cases in fixture"

    def test_drift_detected_when_events_changed(self):
        """Passing wrong events changes the outcome (drift detection)."""
        # Find a non_compliant case (no events satisfying the obligation)
        non_compliant_case = next(
            c for c in CASES if c["expected_status"] == "non_compliant"
        )
        ir = parse_cnl_to_ir(
            non_compliant_case["sentence"],
            jurisdiction=non_compliant_case["jurisdiction"],
        )
        # Inject the target frame ref as a satisfied event → should flip to compliant
        norm = list(ir.norms.values())[0]
        result_with_event = check_compliance(
            {"ir": ir, "facts": {}, "events": [norm.target_frame_ref]},
            {},
        )
        assert result_with_event["status"] == "compliant", (
            "Expected compliant when obligation target frame is in events"
        )
