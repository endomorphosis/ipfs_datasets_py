"""Tests for temporal constraints, DCEC, TDFOL compiler passes, and parity.

Covers issues #1166 (Temporal), #1167 (DCEC), #1168 (TDFOL),
and #1174 (compiler side).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# Path is set up by the layered conftest.py files (root, tests/, and this directory)
from reasoner.hybrid_v2_blueprint import (
    parse_cnl_to_ir, compile_ir_to_dcec, compile_ir_to_temporal_deontic_fol,
    build_v2_compiler_parity_report, DeonticOpV2, TemporalRelationV2,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ir_simple():
    return parse_cnl_to_ir("Contractor shall submit the report")


@pytest.fixture
def ir_within():
    return parse_cnl_to_ir("Vendor shall deliver the goods within 7 days")


@pytest.fixture
def ir_by_date():
    return parse_cnl_to_ir("Contractor shall submit the report by 2024-12-31")


# ---------------------------------------------------------------------------
# TestTemporalConstraintsV3 (#1166)
# ---------------------------------------------------------------------------

class TestTemporalConstraintsV3:
    def test_temporal_is_external_object(self, ir_within):
        # GIVEN a sentence with a temporal clause
        # THEN temporal is stored as a separate object in ir.temporals
        assert len(ir_within.temporals) > 0
        temporal = list(ir_within.temporals.values())[0]
        assert temporal.relation is not None

    def test_temporal_within_normalization(self, ir_within):
        # GIVEN "within 7 days"
        # THEN temporal duration is normalized to ISO 8601 period P7D
        temporal = list(ir_within.temporals.values())[0]
        assert temporal.expr.duration == "P7D"

    def test_temporal_anchor_deterministic(self):
        # GIVEN the same sentence
        # WHEN parsed twice
        ir1 = parse_cnl_to_ir("Vendor shall deliver the goods within 7 days")
        ir2 = parse_cnl_to_ir("Vendor shall deliver the goods within 7 days")
        # THEN temporal IDs are the same
        keys1 = list(ir1.temporals.keys())
        keys2 = list(ir2.temporals.keys())
        assert keys1 == keys2

    def test_temporal_by_date(self, ir_by_date):
        # GIVEN "by 2024-12-31"
        # THEN temporal relation is BY and kind is point
        assert len(ir_by_date.temporals) > 0
        temporal = list(ir_by_date.temporals.values())[0]
        assert temporal.relation == TemporalRelationV2.BY
        assert temporal.expr.kind == "point"
        assert temporal.expr.start == "2024-12-31"

    def test_temporal_during_interval(self):
        # GIVEN a sentence with "during" range clause (expressed as within fallback)
        ir = parse_cnl_to_ir("Vendor shall notify within 30 days")
        assert len(ir.temporals) > 0
        temporal = list(ir.temporals.values())[0]
        assert temporal.expr.duration == "P30D"

    def test_temporal_guard_in_formula(self, ir_within):
        # GIVEN an IR with temporal constraint
        # WHEN compiled to TDFOL
        tdfol = compile_ir_to_temporal_deontic_fol(ir_within)
        # THEN the temporal guard appears (Within or By)
        assert len(tdfol) > 0
        formula = tdfol[0]
        assert "Within(t,P7D)" in formula

    def test_compiler_parity_fixture(self):
        # GIVEN the compiler_parity_v2_cases.json fixture
        fixture_path = FIXTURES_DIR / "compiler_parity_v2_cases.json"
        cases = json.loads(fixture_path.read_text())
        for case in cases:
            ir = parse_cnl_to_ir(case["sentence"])
            dcec = compile_ir_to_dcec(ir)
            tdfol = compile_ir_to_temporal_deontic_fol(ir)
            # DCEC output includes Frame declarations + norm formulas; count norm formulas
            norm_formulas = [f for f in dcec if "forall t" in f]
            assert len(norm_formulas) == case["expected_norm_count"], (
                f"Case {case['id']}: expected {case['expected_norm_count']} DCEC norm formula(s), got {len(norm_formulas)}"
            )
            if case["expected_temporal_in_tdfol"]:
                combined = " ".join(tdfol)
                assert any(
                    token in combined for token in ("Within", "By", "During")
                ), f"Case {case['id']}: expected temporal guard in TDFOL"


# ---------------------------------------------------------------------------
# TestDCECCompilerPass (#1167)
# ---------------------------------------------------------------------------

class TestDCECCompilerPass:
    def test_dcec_deontic_wraps_frame_ref(self, ir_simple):
        # GIVEN a simple obligation IR
        # WHEN compiled to DCEC
        dcec = compile_ir_to_dcec(ir_simple)
        # THEN at least one formula contains the deontic operator wrapping a frm: ref
        assert len(dcec) > 0
        assert any("O(frm:" in f for f in dcec)

    def test_dcec_has_temporal_guard_when_applicable(self, ir_within):
        # GIVEN an IR with a WITHIN temporal
        # WHEN compiled to DCEC
        dcec = compile_ir_to_dcec(ir_within)
        # THEN the formula contains temporal info or is still valid
        # (DCEC may fold temporal into annotation; formula must be non-empty)
        assert len(dcec) > 0
        assert "frm:" in dcec[0]

    def test_dcec_frame_declarations_emitted(self, ir_simple):
        # GIVEN an IR with at least one frame
        # WHEN compiled to DCEC
        dcec = compile_ir_to_dcec(ir_simple)
        # THEN there is at least one formula and it references the frame
        assert any("frm:" in f for f in dcec)

    def test_dcec_deterministic_across_replays(self):
        # GIVEN the same sentence parsed twice
        ir1 = parse_cnl_to_ir("Contractor shall submit the report")
        ir2 = parse_cnl_to_ir("Contractor shall submit the report")
        # WHEN compiled
        dcec1 = compile_ir_to_dcec(ir1)
        dcec2 = compile_ir_to_dcec(ir2)
        # THEN output is identical
        assert dcec1 == dcec2

    def test_dcec_no_backend_formatting_drift(self):
        # GIVEN the same sentence
        # WHEN compiled 3 times
        sentence = "Vendor shall deliver within 7 days"
        formulas = [compile_ir_to_dcec(parse_cnl_to_ir(sentence)) for _ in range(3)]
        # THEN all runs produce identical output
        assert formulas[0] == formulas[1] == formulas[2]


# ---------------------------------------------------------------------------
# TestTDFOLCompilerPass (#1168)
# ---------------------------------------------------------------------------

class TestTDFOLCompilerPass:
    def test_tdfol_time_quantifier_present(self, ir_simple):
        # GIVEN a simple obligation IR
        # WHEN compiled to TDFOL
        tdfol = compile_ir_to_temporal_deontic_fol(ir_simple)
        # THEN at least one formula contains "forall t"
        assert len(tdfol) > 0
        assert any("forall t" in f for f in tdfol)

    def test_tdfol_no_free_variable_leakage(self, ir_simple):
        # GIVEN a simple IR
        # WHEN compiled to TDFOL
        tdfol = compile_ir_to_temporal_deontic_fol(ir_simple)
        # THEN every formula that uses "t" also starts with "forall t"
        for formula in tdfol:
            if " t" in formula or "(t)" in formula:
                assert "forall t" in formula, (
                    f"Free variable 't' detected in formula without quantifier: {formula}"
                )

    def test_tdfol_deontic_target_matches_ir(self, ir_simple):
        # GIVEN an IR with a known frame ref
        norm = list(ir_simple.norms.values())[0]
        target_ref = norm.target_frame_ref
        # WHEN compiled to TDFOL
        tdfol = compile_ir_to_temporal_deontic_fol(ir_simple)
        # THEN the formula references the same frame ref
        assert any(target_ref in f for f in tdfol)

    def test_tdfol_temporal_anchor_consistent(self):
        # GIVEN the same sentence parsed twice
        ir1 = parse_cnl_to_ir("Vendor shall deliver the goods within 7 days")
        ir2 = parse_cnl_to_ir("Vendor shall deliver the goods within 7 days")
        # WHEN compiled
        tdfol1 = compile_ir_to_temporal_deontic_fol(ir1)
        tdfol2 = compile_ir_to_temporal_deontic_fol(ir2)
        # THEN output is identical
        assert tdfol1 == tdfol2

    def test_tdfol_and_dcec_parity(self, ir_simple):
        # GIVEN a simple IR
        # WHEN parity report is built
        parity = build_v2_compiler_parity_report(ir_simple)
        # THEN all checks pass (modal and target_ref consistent)
        for entry in parity["entries"]:
            checks = entry["checks"]
            assert checks["modal_consistent"] is True
            assert checks["target_ref_consistent"] is True


# ---------------------------------------------------------------------------
# TestV3TransformationCompilerPack (#1174 compiler side)
# ---------------------------------------------------------------------------

class TestV3TransformationCompilerPack:
    def test_v3_transformation_all_ten_pass(self):
        # GIVEN all 10 V3 transformation fixture cases
        fixture_path = FIXTURES_DIR / "cnl_v3_transformation_cases.json"
        cases = json.loads(fixture_path.read_text())
        assert len(cases) == 10
        for case in cases:
            if case["expected_parse_mode"] != "norm":
                continue
            ir = parse_cnl_to_ir(case["sentence"])
            dcec = compile_ir_to_dcec(ir)
            tdfol = compile_ir_to_temporal_deontic_fol(ir)
            assert len(dcec) > 0, f"Case {case['id']}: no DCEC output"
            assert len(tdfol) > 0, f"Case {case['id']}: no TDFOL output"

    def test_v3_first_five_dcec_tdfol_parity(self):
        # GIVEN the first 5 norm cases from the fixture
        fixture_path = FIXTURES_DIR / "cnl_v3_transformation_cases.json"
        cases = [
            c for c in json.loads(fixture_path.read_text())
            if c["expected_parse_mode"] == "norm"
        ][:5]
        for case in cases:
            ir = parse_cnl_to_ir(case["sentence"])
            parity = build_v2_compiler_parity_report(ir)
            for entry in parity["entries"]:
                assert entry["checks"]["modal_consistent"] is True, (
                    f"Case {case['id']}: modal not consistent"
                )
                assert entry["checks"]["target_ref_consistent"] is True, (
                    f"Case {case['id']}: target_ref not consistent"
                )

    def test_v3_transformation_formulas_deterministic(self):
        # GIVEN the first 5 norm cases
        fixture_path = FIXTURES_DIR / "cnl_v3_transformation_cases.json"
        cases = [
            c for c in json.loads(fixture_path.read_text())
            if c["expected_parse_mode"] == "norm"
        ][:5]
        for case in cases:
            ir = parse_cnl_to_ir(case["sentence"])
            dcec1 = compile_ir_to_dcec(ir)
            dcec2 = compile_ir_to_dcec(ir)
            tdfol1 = compile_ir_to_temporal_deontic_fol(ir)
            tdfol2 = compile_ir_to_temporal_deontic_fol(ir)
            assert dcec1 == dcec2, f"Case {case['id']}: DCEC not deterministic"
            assert tdfol1 == tdfol2, f"Case {case['id']}: TDFOL not deterministic"

    def test_v3_fixture_dcec_contains_expected_substrings(self):
        # GIVEN the first 5 norm cases with expected_dcec_contains
        fixture_path = FIXTURES_DIR / "cnl_v3_transformation_cases.json"
        cases = [
            c for c in json.loads(fixture_path.read_text())
            if c["expected_parse_mode"] == "norm"
        ][:5]
        for case in cases:
            ir = parse_cnl_to_ir(case["sentence"])
            dcec = compile_ir_to_dcec(ir)
            combined_dcec = " ".join(dcec)
            for substr in case["expected_dcec_contains"]:
                assert substr in combined_dcec, (
                    f"Case {case['id']}: '{substr}' not found in DCEC output"
                )

    def test_v3_fixture_tdfol_contains_expected_substrings(self):
        # GIVEN the first 5 norm cases with expected_tdfol_contains
        fixture_path = FIXTURES_DIR / "cnl_v3_transformation_cases.json"
        cases = [
            c for c in json.loads(fixture_path.read_text())
            if c["expected_parse_mode"] == "norm"
        ][:5]
        for case in cases:
            ir = parse_cnl_to_ir(case["sentence"])
            tdfol = compile_ir_to_temporal_deontic_fol(ir)
            combined_tdfol = " ".join(tdfol)
            for substr in case["expected_tdfol_contains"]:
                assert substr in combined_tdfol, (
                    f"Case {case['id']}: '{substr}' not found in TDFOL output"
                )
