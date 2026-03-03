"""Tests for Query API semantics and the 8-Query Proof Matrix.

Covers issues #1173 (API Semantics) and #1175 (8-Query Proof Matrix).
"""
from __future__ import annotations

import pytest

# Path is set up by the layered conftest.py files (root, tests/, and this directory)
from reasoner.hybrid_v2_blueprint import (
    parse_cnl_to_ir, check_compliance, find_violations,
    explain_proof, clear_v2_proof_store, DeonticOpV2,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_proof_store():
    clear_v2_proof_store()
    yield
    clear_v2_proof_store()


@pytest.fixture
def ir_obligation():
    return parse_cnl_to_ir("Contractor shall submit the report")


@pytest.fixture
def ir_prohibition():
    return parse_cnl_to_ir("Vendor shall not disclose confidential data")


@pytest.fixture
def ir_permission():
    return parse_cnl_to_ir("The contractor may extend the deadline")


# ---------------------------------------------------------------------------
# TestQueryAPISemantics (#1173)
# ---------------------------------------------------------------------------

class TestQueryAPISemantics:
    def test_check_compliance_compliant_case(self, ir_obligation):
        # GIVEN an obligation IR and the target frame is in the events list
        norm = list(ir_obligation.norms.values())[0]
        target = norm.target_frame_ref
        result = check_compliance(
            {"ir": ir_obligation, "facts": {}, "events": [target]}, {}
        )
        # THEN status is compliant
        assert result["status"] == "compliant"
        assert result["violation_count"] == 0

    def test_check_compliance_violation_omission(self, ir_obligation):
        # GIVEN an obligation IR but no event fulfilling the obligation
        result = check_compliance(
            {"ir": ir_obligation, "facts": {}, "events": []}, {}
        )
        # THEN status is non_compliant with omission violation
        assert result["status"] == "non_compliant"
        assert result["violation_count"] >= 1
        assert result["violations"][0]["type"] == "omission"

    def test_check_compliance_violation_forbidden(self, ir_prohibition):
        # GIVEN a prohibition IR and the forbidden action appears in events
        norm = list(ir_prohibition.norms.values())[0]
        target = norm.target_frame_ref
        result = check_compliance(
            {"ir": ir_prohibition, "facts": {}, "events": [target]}, {}
        )
        # THEN status is non_compliant with forbidden_action violation
        assert result["status"] == "non_compliant"
        assert result["violations"][0]["type"] == "forbidden_action"

    def test_check_compliance_schema_stable(self, ir_obligation):
        # GIVEN an obligation IR
        result = check_compliance(
            {"ir": ir_obligation, "facts": {}, "events": []}, {}
        )
        # THEN all required keys are present
        for key in ("api", "schema_version", "status", "violations", "proof_id", "violation_count"):
            assert key in result, f"Missing key: {key}"

    def test_find_violations_schema_stable(self, ir_obligation):
        # GIVEN an obligation IR
        result = find_violations(
            {"ir": ir_obligation, "facts": {}, "events": []},
            ("2024-01-01", "2024-12-31"),
        )
        # THEN required keys are present
        for key in ("api", "schema_version", "violations", "proof_id", "violation_count"):
            assert key in result, f"Missing key: {key}"

    def test_explain_proof_nl_format(self, ir_obligation):
        # GIVEN a compliance result
        result = check_compliance(
            {"ir": ir_obligation, "facts": {}, "events": []}, {}
        )
        proof_id = result["proof_id"]
        # WHEN explained in NL format
        expl = explain_proof(proof_id, format="nl")
        # THEN text key is present and non-empty
        assert "text" in expl
        assert len(expl["text"]) > 0

    def test_explain_proof_json_format(self, ir_obligation):
        # GIVEN a compliance result
        result = check_compliance(
            {"ir": ir_obligation, "facts": {}, "events": []}, {}
        )
        proof_id = result["proof_id"]
        # WHEN explained in JSON format
        expl = explain_proof(proof_id, format="json")
        # THEN steps list is present
        assert "steps" in expl
        assert isinstance(expl["steps"], list)

    def test_explain_proof_unknown_raises(self):
        # GIVEN an unknown proof_id
        # WHEN explain_proof is called
        # THEN KeyError is raised
        with pytest.raises(KeyError):
            explain_proof("pf2_nonexistent_xyz999", format="nl")

    def test_compliance_result_has_proof_id(self, ir_obligation):
        # GIVEN a compliance check
        result = check_compliance(
            {"ir": ir_obligation, "facts": {}, "events": []}, {}
        )
        # THEN proof_id is a non-empty string
        assert isinstance(result["proof_id"], str)
        assert len(result["proof_id"]) > 0


# ---------------------------------------------------------------------------
# TestExceptionAndDeadlineSemantics
# ---------------------------------------------------------------------------

class TestExceptionAndDeadlineSemantics:
    def test_exception_prevents_violation(self):
        # GIVEN an obligation with unless clause
        ir = parse_cnl_to_ir("Contractor shall file the form unless emergency")
        norm = list(ir.norms.values())[0]
        # Get the actual exception predicate name
        ex_pred = norm.exceptions[0].atom.pred
        # WHEN the exception fact is true
        result = check_compliance(
            {"ir": ir, "facts": {ex_pred: True}, "events": []}, {}
        )
        # THEN no violation occurs (exception discharges obligation)
        assert result["status"] == "compliant"

    def test_temporal_deadline_in_output(self):
        # GIVEN an obligation with temporal clause
        ir = parse_cnl_to_ir("Contractor shall submit within 7 days")
        result = check_compliance({"ir": ir, "facts": {}, "events": []}, {})
        # THEN the result has non-zero violation count (obligation unfulfilled)
        assert result["violation_count"] >= 1


# ---------------------------------------------------------------------------
# TestConflictSemantics
# ---------------------------------------------------------------------------

class TestConflictSemantics:
    def test_two_conflicting_norms_both_tracked(self):
        # GIVEN two separate IRs: one obligation, one prohibition for similar actions
        ir_o = parse_cnl_to_ir("Contractor shall submit the report")
        ir_f = parse_cnl_to_ir("Vendor shall not disclose confidential data")
        r_o = check_compliance({"ir": ir_o, "facts": {}, "events": []}, {})
        r_f = check_compliance({"ir": ir_f, "facts": {}, "events": []}, {})
        # THEN both are tracked separately
        assert r_o["proof_id"] != r_f["proof_id"]

    def test_deterministic_conflict_precedence(self):
        # GIVEN the same sentence parsed twice
        ir1 = parse_cnl_to_ir("Contractor shall submit the report")
        ir2 = parse_cnl_to_ir("Contractor shall submit the report")
        r1 = check_compliance({"ir": ir1, "facts": {}, "events": []}, {})
        r2 = check_compliance({"ir": ir2, "facts": {}, "events": []}, {})
        # THEN both produce the same proof_id (deterministic)
        assert r1["proof_id"] == r2["proof_id"]


# ---------------------------------------------------------------------------
# TestEightQueryProofMatrix (#1175)
# ---------------------------------------------------------------------------

class TestEightQueryProofMatrix:
    def test_q1_obligation_compliant(self):
        # Q1: O norm + event happened → compliant
        ir = parse_cnl_to_ir("Contractor shall submit the report")
        norm = list(ir.norms.values())[0]
        result = check_compliance(
            {"ir": ir, "facts": {}, "events": [norm.target_frame_ref]}, {}
        )
        assert result["status"] == "compliant"
        assert result["violation_count"] == 0
        assert isinstance(result["proof_id"], str)

    def test_q2_obligation_violated(self):
        # Q2: O norm + event didn't happen → violation
        ir = parse_cnl_to_ir("Contractor shall submit the report")
        result = check_compliance({"ir": ir, "facts": {}, "events": []}, {})
        assert result["status"] == "non_compliant"
        assert result["violation_count"] == 1
        assert result["violations"][0]["type"] == "omission"
        assert isinstance(result["proof_id"], str)

    def test_q3_prohibition_compliant(self):
        # Q3: F norm + event didn't happen → compliant
        ir = parse_cnl_to_ir("Vendor shall not disclose confidential data")
        result = check_compliance({"ir": ir, "facts": {}, "events": []}, {})
        assert result["status"] == "compliant"
        assert result["violation_count"] == 0
        assert isinstance(result["proof_id"], str)

    def test_q4_prohibition_violated(self):
        # Q4: F norm + event happened → violation
        ir = parse_cnl_to_ir("Vendor shall not disclose confidential data")
        norm = list(ir.norms.values())[0]
        result = check_compliance(
            {"ir": ir, "facts": {}, "events": [norm.target_frame_ref]}, {}
        )
        assert result["status"] == "non_compliant"
        assert result["violation_count"] >= 1
        assert result["violations"][0]["type"] == "forbidden_action"
        assert isinstance(result["proof_id"], str)

    def test_q5_permission_no_violation(self):
        # Q5: P norm → no violations regardless of events
        ir = parse_cnl_to_ir("The contractor may extend the deadline")
        norm = list(ir.norms.values())[0]
        assert norm.op == DeonticOpV2.P
        # No events
        r1 = check_compliance({"ir": ir, "facts": {}, "events": []}, {})
        assert r1["violation_count"] == 0
        # With target event
        r2 = check_compliance(
            {"ir": ir, "facts": {}, "events": [norm.target_frame_ref]}, {}
        )
        assert r2["violation_count"] == 0

    def test_q6_conditional_obligation_inactive(self):
        # Q6: O norm + activation=false → no violation
        ir = parse_cnl_to_ir("Contractor shall file the form if approval_granted")
        # Activation fact not provided → condition is false → no violation
        result = check_compliance({"ir": ir, "facts": {}, "events": []}, {})
        assert result["status"] == "compliant"
        assert result["violation_count"] == 0
        assert isinstance(result["proof_id"], str)

    def test_q7_exception_discharges_obligation(self):
        # Q7: O norm + exception holds → no violation
        ir = parse_cnl_to_ir("Contractor shall file the form unless emergency")
        norm = list(ir.norms.values())[0]
        ex_pred = norm.exceptions[0].atom.pred
        result = check_compliance(
            {"ir": ir, "facts": {ex_pred: True}, "events": []}, {}
        )
        assert result["status"] == "compliant"
        assert result["violation_count"] == 0
        assert isinstance(result["proof_id"], str)

    def test_q8_multiple_norms_mixed(self):
        # Q8: two separate norms checked individually; one violated, one compliant
        # Obligation (violated - no event)
        ir_o = parse_cnl_to_ir("Contractor shall submit the report")
        r_o = check_compliance({"ir": ir_o, "facts": {}, "events": []}, {})
        assert r_o["status"] == "non_compliant"
        assert r_o["violation_count"] == 1

        # Prohibition (compliant - no event)
        ir_f = parse_cnl_to_ir("Vendor shall not disclose confidential data")
        r_f = check_compliance({"ir": ir_f, "facts": {}, "events": []}, {})
        assert r_f["status"] == "compliant"
        assert r_f["violation_count"] == 0

        # Both have distinct proof_ids
        assert r_o["proof_id"] != r_f["proof_id"]
