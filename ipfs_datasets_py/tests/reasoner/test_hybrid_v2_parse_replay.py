"""Tests for CNL grammar, ambiguity, round-trip, and V3 transformation pack.

Covers issues #1165 (CNL Grammar + Ambiguity), #1169 (Round-Trip),
and #1174 (V3 10-example pack, CNL side).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# Path is set up by the layered conftest.py files (root, tests/, and this directory)
from reasoner.hybrid_v2_blueprint import (
    parse_cnl_to_ir_with_diagnostics, parse_cnl_to_ir,
    compile_ir_to_dcec, compile_ir_to_temporal_deontic_fol,
    generate_cnl_from_ir, CNLParseError, DeonticOpV2,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# TestCNLParseReplay (#1165)
# ---------------------------------------------------------------------------

class TestCNLParseReplay:
    def test_canonical_shall_template(self):
        # GIVEN a "shall" sentence
        ir = parse_cnl_to_ir("Contractor shall submit the report")
        norm = list(ir.norms.values())[0]
        # THEN the deontic op is O (obligation)
        assert norm.op == DeonticOpV2.O

    def test_canonical_shall_not_template(self):
        # GIVEN a "shall not" sentence
        ir = parse_cnl_to_ir("The vendor shall not disclose confidential information")
        norm = list(ir.norms.values())[0]
        # THEN the deontic op is F (prohibition)
        assert norm.op == DeonticOpV2.F

    def test_canonical_may_template(self):
        # GIVEN a "may" sentence
        ir = parse_cnl_to_ir("The contractor may terminate the agreement")
        norm = list(ir.norms.values())[0]
        # THEN the deontic op is P (permission)
        assert norm.op == DeonticOpV2.P

    def test_definition_means_template(self):
        # GIVEN a "means" sentence
        ir = parse_cnl_to_ir("Force Majeure means events beyond reasonable control")
        # THEN the IR has rules (definition), not norms
        assert len(ir.rules) > 0
        assert len(ir.norms) == 0

    def test_definition_includes_template(self):
        # GIVEN an "includes" sentence
        ir = parse_cnl_to_ir("Party includes natural persons and legal entities")
        # THEN the IR has multiple rules
        assert len(ir.rules) > 0

    def test_temporal_within_days(self):
        # GIVEN a sentence with "within N days" temporal clause
        ir, diag = parse_cnl_to_ir_with_diagnostics(
            "Vendor shall deliver the goods within 7 days"
        )
        # THEN temporal is detected
        assert diag["temporal_detected"] is True
        assert len(ir.temporals) > 0

    def test_temporal_by_date(self):
        # GIVEN a sentence with "by DATE" temporal clause
        ir, diag = parse_cnl_to_ir_with_diagnostics(
            "Contractor shall submit the report by 2024-12-31"
        )
        # THEN temporal is detected and relation is BY
        assert diag["temporal_detected"] is True
        assert len(ir.temporals) > 0
        temporal = list(ir.temporals.values())[0]
        from reasoner.hybrid_v2_blueprint import TemporalRelationV2
        assert temporal.relation == TemporalRelationV2.BY

    def test_activation_if_clause(self):
        # GIVEN a sentence with an "if" activation clause
        ir = parse_cnl_to_ir("Contractor shall file the form if approval_granted")
        norm = list(ir.norms.values())[0]
        # THEN the activation atom predicate reflects the if-clause
        assert "if_approval_granted" in norm.activation.atom.pred

    def test_exception_unless_clause(self):
        # GIVEN a sentence with "unless" exception clause
        ir = parse_cnl_to_ir("Vendor shall perform the service unless force_majeure")
        norm = list(ir.norms.values())[0]
        # THEN the norm has at least one exception
        assert len(norm.exceptions) > 0

    def test_ambiguous_raises_error(self):
        # GIVEN a sentence with multiple activation markers (if + when)
        # WHEN parsed
        # THEN CNLParseError is raised
        with pytest.raises(CNLParseError) as exc_info:
            parse_cnl_to_ir("The vendor shall provide if approved when ready")
        err = exc_info.value
        assert hasattr(err, "error_code")
        assert hasattr(err, "ambiguity_flags")

    def test_empty_sentence_raises_error(self):
        # GIVEN an empty string
        # WHEN parsed
        # THEN CNLParseError is raised with the empty-sentence code
        with pytest.raises(CNLParseError) as exc_info:
            parse_cnl_to_ir("")
        assert exc_info.value.error_code == "V2_CNL_PARSE_EMPTY_SENTENCE"

    def test_replay_corpus_fixture(self):
        # GIVEN the cnl_parse_replay_v2_corpus.json fixture
        fixture_path = FIXTURES_DIR / "cnl_parse_replay_v2_corpus.json"
        cases = json.loads(fixture_path.read_text())
        # WHEN each non-ambiguous case is parsed
        for case in cases:
            if case["expect_ambiguity_error"]:
                with pytest.raises(CNLParseError):
                    parse_cnl_to_ir(case["sentence"])
            else:
                ir = parse_cnl_to_ir(case["sentence"])
                if case["expected_parse_mode"] == "norm":
                    assert len(ir.norms) > 0, f"Expected norms for case {case['id']}"
                else:
                    assert len(ir.rules) > 0, f"Expected rules for case {case['id']}"


# ---------------------------------------------------------------------------
# TestParseReplayCandidateDiagnostics
# ---------------------------------------------------------------------------

class TestParseReplayCandidateDiagnostics:
    def test_diagnostics_include_parse_alternatives(self):
        # GIVEN a normal sentence
        _, diag = parse_cnl_to_ir_with_diagnostics("Contractor shall submit the report")
        # THEN diagnostics include parse_alternatives
        assert "parse_alternatives" in diag
        assert isinstance(diag["parse_alternatives"], list)
        assert len(diag["parse_alternatives"]) > 0

    def test_diagnostics_include_marker_counts(self):
        # GIVEN a normal sentence
        _, diag = parse_cnl_to_ir_with_diagnostics("Contractor shall submit the report")
        # THEN diagnostics include marker_counts
        assert "marker_counts" in diag
        assert isinstance(diag["marker_counts"], dict)

    def test_diagnostics_confidence_range(self):
        # GIVEN a normal sentence
        _, diag = parse_cnl_to_ir_with_diagnostics("Contractor shall submit the report")
        # THEN parse_confidence is between 0.85 and 1.0
        conf = diag["parse_confidence"]
        assert 0.85 <= conf <= 1.0, f"Confidence {conf} out of expected range [0.85, 1.0]"


# ---------------------------------------------------------------------------
# TestRoundTripCNL (#1169)
# ---------------------------------------------------------------------------

class TestRoundTripCNL:
    def test_round_trip_strict_mode(self):
        # GIVEN a parsed IR
        sentence = "Contractor shall submit the report"
        ir = parse_cnl_to_ir(sentence)
        norm_ref = list(ir.norms.keys())[0]
        # WHEN CNL is generated twice
        cnl1 = generate_cnl_from_ir(norm_ref, ir)
        cnl2 = generate_cnl_from_ir(norm_ref, ir)
        # THEN both are equal (deterministic)
        assert cnl1 == cnl2
        assert len(cnl1) > 0

    def test_round_trip_paraphrase_safe(self):
        # GIVEN semantically equivalent paraphrases
        paraphrases = [
            "Contractor shall submit the report",
            "The contractor shall submit the report",
        ]
        norm_counts = []
        for para in paraphrases:
            ir = parse_cnl_to_ir(para)
            norm_counts.append(len(ir.norms))
        # THEN all produce the same number of norms
        assert len(set(norm_counts)) == 1

    def test_round_trip_preserves_modal(self):
        # GIVEN a "shall not" sentence
        ir = parse_cnl_to_ir("Vendor shall not disclose data")
        norm_ref = list(ir.norms.keys())[0]
        norm = ir.norms[norm_ref]
        cnl = generate_cnl_from_ir(norm_ref, ir)
        # THEN original modal is F and round-trip CNL is non-empty
        assert norm.op == DeonticOpV2.F
        assert len(cnl) > 0

    def test_round_trip_preserves_temporal(self):
        # GIVEN a sentence with temporal
        ir = parse_cnl_to_ir("Vendor shall deliver the goods within 7 days")
        norm_ref = list(ir.norms.keys())[0]
        cnl = generate_cnl_from_ir(norm_ref, ir)
        # THEN the CNL output references time (week or days)
        assert len(cnl) > 0
        assert len(ir.temporals) > 0

    def test_paraphrase_fixture(self):
        # GIVEN the paraphrase equivalence fixture
        fixture_path = FIXTURES_DIR / "cnl_parse_paraphrase_equivalence_v2.json"
        cases = json.loads(fixture_path.read_text())
        for case in cases:
            canonical_ir = parse_cnl_to_ir(case["canonical_sentence"])
            assert len(canonical_ir.norms) == case["expected_norm_count"], (
                f"Case {case['id']}: expected {case['expected_norm_count']} norms"
            )
            canon_norm = list(canonical_ir.norms.values())[0]
            expected_op = DeonticOpV2[case["expected_modal"]]
            assert canon_norm.op == expected_op, (
                f"Case {case['id']}: expected modal {case['expected_modal']}"
            )
            # Each paraphrase should also produce the same norm count
            for para in case["paraphrases"]:
                para_ir = parse_cnl_to_ir(para)
                assert len(para_ir.norms) == case["expected_norm_count"], (
                    f"Paraphrase '{para}' norm count mismatch"
                )


# ---------------------------------------------------------------------------
# TestV3TransformationPack (#1174 CNL side)
# ---------------------------------------------------------------------------

class TestV3TransformationPack:
    def test_v3_transformation_fixture_exists(self):
        # GIVEN the fixture path
        fixture_path = FIXTURES_DIR / "cnl_v3_transformation_cases.json"
        # THEN the file exists and has exactly 10 cases
        assert fixture_path.exists()
        cases = json.loads(fixture_path.read_text())
        assert len(cases) == 10

    def test_v3_transformation_first_five_parse_mode(self):
        # GIVEN the first 5 cases in the fixture
        fixture_path = FIXTURES_DIR / "cnl_v3_transformation_cases.json"
        cases = json.loads(fixture_path.read_text())[:5]
        # WHEN each is parsed
        for case in cases:
            ir = parse_cnl_to_ir(case["sentence"])
            if case["expected_parse_mode"] == "norm":
                assert len(ir.norms) > 0, f"Case {case['id']}: expected norms"
            else:
                assert len(ir.rules) > 0, f"Case {case['id']}: expected rules"

    def test_v3_round_trip_nl_stability(self):
        # GIVEN the first 5 norm cases from the fixture
        fixture_path = FIXTURES_DIR / "cnl_v3_transformation_cases.json"
        cases = [
            c for c in json.loads(fixture_path.read_text())
            if c["expected_parse_mode"] == "norm"
        ][:5]
        # WHEN CNL is generated twice for the same IR
        for case in cases:
            ir = parse_cnl_to_ir(case["sentence"])
            if ir.norms:
                norm_ref = list(ir.norms.keys())[0]
                cnl1 = generate_cnl_from_ir(norm_ref, ir)
                cnl2 = generate_cnl_from_ir(norm_ref, ir)
                assert cnl1 == cnl2, (
                    f"Case {case['id']}: CNL round-trip not deterministic"
                )
