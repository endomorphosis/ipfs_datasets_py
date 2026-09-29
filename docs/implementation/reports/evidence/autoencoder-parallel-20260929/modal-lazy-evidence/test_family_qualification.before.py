"""Qualification parses actual exports and never promotes projections/admissions."""
from __future__ import annotations

import hashlib

import pytest

from ipfs_datasets_py.logic.autoformal import family_qualification as qualification


TEXT = "The officer shall retain records."
RULE = {
    "modality": "O", "actor": "officer", "action": "retain", "object": "records",
    "conditions": [], "exceptions": [], "temporal": [],
}


@pytest.mark.parametrize(("family", "formula"), [
    ("fol", "forall x. (Officer(x) -> Retain(x))"),
    ("deontic_fol", "O(forall x. (Officer(x) -> Retain(x)))"),
    ("temporal_fol", "always(forall x. (Officer(x) -> Retain(x)))"),
    ("deontic_temporal_fol", "always(O(forall x. (Officer(x) -> Retain(x))))"),
    ("dcec", "O(Happens(retain,t0))"),
    ("frame_logic", "officer[role->clerk]."),
])
def test_supported_native_syntax_is_only_unbound_syntax_evidence(family, formula):
    report = qualification.validate_family_artifact(family, formula)
    assert report["passed"] is True
    assert report["syntax_valid"] is True
    assert report["consumed_all_input"] is True
    assert report["source_bound"] is False
    assert report["semantic_equivalence_checked"] is False
    assert report["admitted"] is False
    assert report["formalized"] is False
    assert report["formula"] == formula
    assert report["formula_sha256"] == hashlib.sha256(formula.encode()).hexdigest()
    assert report["parser_source_sha256"]


@pytest.mark.parametrize(("family", "formula"), [
    ("fol", ""),
    ("fol", "   "),
    ("fol", "Retain(x) @"),  # Legacy TDFOL lexer alone drops this character.
    ("fol", "Retain(x) trailing"),
    ("fol", "O(Retain(x))"),
    ("deontic_fol", "always(O(Retain(x)))"),
    ("temporal_fol", "O(Retain(x))"),
    ("deontic_fol", "O(frm:abc,t)"),  # Compatibility fallback is not strict.
    ("frame_logic", "span[actor->officer;action->retain]"),
    ("dcec", "O(Happens(retain,t0)) @"),
    ("dcec", "Happens(legal_norm(s), t) => HoldsAt(O(forall x. Retain(x)), t)"),
    ("dcec", "O(Happens(retain,t0)) garbage"),
    ("dcec", "(Retain(x) and)"),
    ("dcec", "(and Retain(x))"),
    ("dcec", "(Retain(x) and Temporal(x))"),
    ("dcec", "O(Happens(retain,t0,extra))"),
    ("flogic", "stitch:span:actor[role->clerk]."),
    ("invented_family", "Retain(x)"),
])
def test_empty_recovery_wrong_dialect_and_unknown_families_fail_closed(family, formula):
    report = qualification.validate_family_artifact(family, formula)
    assert report["passed"] is False
    assert report["syntax_valid"] is False
    assert report["diagnostics"]


def test_all_canonical_exports_are_bound_and_legacy_dialect_failures_are_retained():
    report = qualification.qualify_logic_families(TEXT, RULE, source_id="officer-records")
    assert set(report["families"]) == set(qualification.REQUIRED_FAMILIES)
    assert report["passed"] is True
    assert report["source_sha256"] == hashlib.sha256(TEXT.encode()).hexdigest()
    assert report["canonical_rule"] == RULE
    assert report["projection_only"] is True
    for family in qualification.REQUIRED_FAMILIES:
        row = report["families"][family]
        assert row["source_sha256"] == report["source_sha256"]
        assert row["rule_sha256"] == report["rule_sha256"]
        assert row["formula"]
        assert row["source_bound"] is True
        assert row["admitted"] is False
        assert row["semantic_equivalence_checked"] is False
        assert row["formula"] == row["export_record"]["exported_formula"]
    assert report["families"]["fol"]["passed"] is True
    assert report["families"]["temporal_fol"]["passed"] is True
    for family in ("frame_logic", "deontic_cognitive_event_calculus"):
        record = report["families"][family]["export_record"]
        assert report["families"][family]["passed"] is True
        assert record["legacy_syntax_diagnostic"]["passed"] is False
        assert record["exported_formula"] != record["legacy_export_record"]["exported_formula"]
    assert report["goals"] == []


def test_temporal_projection_discloses_modality_loss_and_adds_no_time_operator():
    report = qualification.qualify_logic_families(TEXT, RULE)
    parent = report["families"]["deontic_temporal_fol"]
    child = report["families"]["temporal_fol"]
    assert "DeonticFormula" in parent["ast_classes"]
    assert "TemporalFormula" not in child["ast_classes"]
    assert "DeonticFormula" not in child["ast_classes"]
    record = child["export_record"]
    assert record["projection_omitted_facets"] == ["modality"]
    assert record["temporal_operator_added"] is False
    assert record["event_time_invented"] is False


def test_no_compiled_rule_cannot_generate_stitch_or_pass_any_family():
    report = qualification.qualify_logic_families("5, 1990, 104 Stat.")
    assert report["passed"] is False
    assert len(report["goals"]) == len(qualification.REQUIRED_FAMILIES)
    assert all(row["passed"] is False and not row["formula"] for row in report["families"].values())
    assert all(row["applicability"] == "unavailable" for row in report["families"].values())
    assert "canonical_compiler_rule_missing" in report["diagnostics"][0]["code"]


def test_empty_required_set_does_not_vacuously_pass():
    report = qualification.qualify_logic_families(TEXT, RULE, required_families=())
    assert report["passed"] is False
    assert "empty_required_family_set" in report["diagnostics"][0]["code"]


def test_parser_supplied_temporal_sidecar_is_retained_without_altering_rule():
    sidecar = [{"temporal_kind": "minimum_duration", "quantity": 20, "value": "at least 20 days"}]
    rule = {**RULE, "temporal": ["at least 20 days"]}
    report = qualification.qualify_logic_families(TEXT, {**rule, "temporal_records": sidecar})
    base = qualification.qualify_logic_families(TEXT, rule)
    assert report["temporal_records"] == sidecar
    assert report["canonical_rule"] == rule
    assert report["rule_sha256"] == base["rule_sha256"]
    assert report["input_rule_sha256"] != base["input_rule_sha256"]
    assert report["passed"] is True
    assert "minimum_duration(" in report["families"]["temporal_fol"]["formula"]


def test_no_automatic_export_rewrite_when_native_parser_rejects(monkeypatch):
    artifact = "Retain(x) @"
    monkeypatch.setattr(qualification, "_export_rule", lambda *args: [
        {"target": "fol", "exported_formula": artifact, "skipped": False},
    ])
    report = qualification.qualify_logic_families(TEXT, RULE, required_families=("fol",))
    assert report["passed"] is False
    assert report["families"]["fol"]["formula"] == artifact


def test_exporter_skip_and_missing_family_cannot_be_passes(monkeypatch):
    monkeypatch.setattr(qualification, "_export_rule", lambda *args: [
        {"target": "fol", "exported_formula": "Retain(x)", "skipped": True},
    ])
    report = qualification.qualify_logic_families(TEXT, RULE)
    assert report["passed"] is False
    assert all(row["passed"] is False for row in report["families"].values())


def test_family_parser_loaded_from_foreign_tree_is_not_an_ordinary_gap(monkeypatch, tmp_path):
    from ipfs_datasets_py.logic.TDFOL import tdfol_parser
    from ipfs_datasets_py.logic.autoformal.tree_pin import LogicTreePinError
    path = tmp_path / "drifted_parser.py"
    path.write_text("# different tree")
    monkeypatch.setattr(tdfol_parser, "__file__", str(path))
    with pytest.raises(LogicTreePinError):
        qualification.validate_family_artifact("fol", "Retain(x)")


def test_artifacts_are_bounded_without_skipping_gate():
    report = qualification.validate_family_artifact("fol", "R" * (qualification.MAX_ARTIFACT_BYTES + 1))
    assert report["passed"] is False
    assert report["diagnostics"][0]["code"] == "artifact_size_limit"


@pytest.mark.parametrize("text", [
    "The officer shall retain the file for at least 20 days.",
    "Company A shall submit backup report within 10 days unless emergency.",
    "The agency shall not disclose records.",
])
def test_real_compiler_gate_spans_have_six_native_syntax_exports(text):
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span
    session = AutoformalSession()
    compiled = compile_span(session, text, "gate")
    assert compiled["compiler_status"] == "compiled"
    report = qualification.qualify_logic_families(text, compiled["rule"], source_id="gate")
    assert report["passed"] is True
    assert report["admitted"] is False
    assert report["formalized"] is False
    assert all(row["passed"] for row in report["families"].values())
    if "within 10" in text:
        assert "within_duration(" in report["families"]["temporal_fol"]["formula"]
        assert "minimum_duration(" not in report["families"]["temporal_fol"]["formula"]


def test_binding_table_retains_canonical_atoms_and_distinguishes_slug_collisions():
    rule = {**RULE, "conditions": ["account number", "account-number"],
            "exceptions": ["emergency"], "temporal": ["20 days"]}
    records = qualification.export_canonical_rule_families(rule, source_id="source")
    for record in records:
        assert record["canonical_rule"] == rule
        bindings = record["atom_bindings"]
        assert {row["value"] for row in bindings.values()} == {
            "officer", "retain", "records", "account-number", "account number", "emergency", "20 days",
        }
        identifiers = [key for key, value in bindings.items() if value["slot"] == "condition"]
        assert len(set(identifiers)) == 2
        family = "dcec" if record["target"] == "deontic_cec" else record["target"]
        assert qualification.validate_family_artifact(family, record["exported_formula"])["passed"]


def test_duration_sidecar_unrelated_to_canonical_rule_fails_closed():
    report = qualification.qualify_logic_families(TEXT, {
        **RULE, "temporal_records": [{"temporal_kind": "minimum_duration", "value": "20 days", "quantity": 20}],
    })
    assert report["passed"] is False
    assert "temporal_sidecar_not_bound_to_canonical_atom" in report["diagnostics"][0]["code"]


def test_dcec_requires_matching_ast_shapes_not_two_boolean_parse_successes():
    # Both parsers accept these bytes, but the shared parser interprets an
    # s-expression predicate Retain with Boolean arguments x/and/Temporal/x.
    text = "(Retain(x) and Temporal(x))"
    report = qualification.validate_family_artifact("dcec", text)
    assert report["passed"] is False
    assert any("dcec_boolean_used_as_term" in row["code"] for row in report["diagnostics"])
    supported = qualification.validate_family_artifact("dcec", "O((Retain(x) and Temporal(x)))")
    assert supported["passed"] is True
    assert supported["parser_ast_parity"] is True
    assert supported["independent_parser"]["consumed_all_input"] is True


def _parsed_frame_slots(formula):
    """Read emitted bindings through the actual F-logic AST, not regexes."""
    from ipfs_datasets_py.logic.parsers.flogic import parse_flogic
    parsed = parse_flogic(formula)
    assert parsed.ok and not parsed.diagnostics
    statements = parsed.document.to_dict()["statements"]
    assert len(statements) == 1
    return {(item["method"]["name"], tuple(arg["name"] for arg in item["method"]["arguments"])):
            tuple(value["name"] for value in item["values"])
            for item in statements[0]["head"]["specs"]}


def test_reordered_temporal_records_bind_quantities_to_canonical_frame_atoms():
    rule = {**RULE, "temporal": ["20 days", "10 days"]}
    sidecars = [{"temporal_kind": "minimum_duration", "value": "20 days", "quantity": 20},
                {"temporal_kind": "minimum_duration", "value": "10 days", "quantity": 10}]
    reports = [qualification.qualify_logic_families(TEXT, {**rule, "temporal_records": records})
               for records in (sidecars, list(reversed(sidecars)))]
    frames = [report["families"]["frame_logic"] for report in reports]
    assert all(report["passed"] for report in reports)
    assert frames[0]["formula"] == frames[1]["formula"]
    slots = _parsed_frame_slots(frames[0]["formula"])
    assert slots["temporal", ("0",)] == ("10 days",)
    assert slots["temporal_quantity", ("0",)] == ("10",)
    assert slots["temporal", ("1",)] == ("20 days",)
    assert slots["temporal_quantity", ("1",)] == ("20",)
    assert [record["canonical_temporal_index"] for record in frames[0]["export_record"]["temporal_records"]] == [1, 0]
    assert reports[0]["rule_sha256"] == reports[1]["rule_sha256"]
    assert reports[0]["input_rule_sha256"] != reports[1]["input_rule_sha256"]


def test_partial_temporal_typing_keeps_untyped_atoms_and_the_typed_atom_index():
    report = qualification.qualify_logic_families(TEXT, {
        **RULE, "temporal": ["10 days", "20 days", "before review"],
        "temporal_records": [{"temporal_kind": "minimum_duration", "value": "20 days", "quantity": 20}],
    })
    frame = report["families"]["frame_logic"]
    slots = _parsed_frame_slots(frame["formula"])
    assert report["passed"] is True
    assert slots["temporal", ("0",)] == ("10 days",)
    assert slots["temporal", ("1",)] == ("20 days",)
    assert slots["temporal", ("2",)] == ("before review",)
    assert slots["temporal_quantity", ("1",)] == ("20",)
    assert ("temporal_kind", ("0",)) not in slots
    assert ("temporal_kind", ("2",)) not in slots
    for row in report["families"].values():
        coverage = row["representation_coverage"]
        assert coverage["temporal_atom_count"] == 3
        assert coverage["typed_duration_record_count"] == 1
        assert coverage["typed_duration_atom_indices"] == [1]


def test_within_and_minimum_records_retain_distinct_kinds_after_sorting():
    report = qualification.qualify_logic_families(TEXT, {
        **RULE, "temporal": ["within 10 days", "20 days"],
        "temporal_records": [
            {"temporal_kind": "within_duration", "value": "10 days", "quantity": 10},
            {"temporal_kind": "minimum_duration", "value": "20 days", "quantity": 20}],
    })
    slots = _parsed_frame_slots(report["families"]["frame_logic"]["formula"])
    assert report["passed"] is True
    assert slots["temporal", ("0",)] == ("20 days",)
    assert slots["temporal_kind", ("0",)] == ("minimum_duration",)
    assert slots["temporal_quantity", ("0",)] == ("20",)
    assert slots["temporal", ("1",)] == ("within 10 days",)
    assert slots["temporal_kind", ("1",)] == ("within_duration",)
    assert slots["temporal_quantity", ("1",)] == ("10",)
    assert not report["admitted"]


def test_representation_coverage_does_not_claim_temporal_event_or_cognitive_semantics():
    report = qualification.qualify_logic_families(TEXT, RULE)
    for family, row in report["families"].items():
        coverage = row["representation_coverage"]
        assert coverage == row["export_record"]["representation_coverage"]
        assert coverage["scope"] == "canonical_atom_syntax_projection"
        assert coverage["temporal_atom_count"] == coverage["typed_duration_record_count"] == 0
        assert coverage["typed_duration_atom_indices"] == []
        assert coverage["temporal_operator_count"] == 0
        assert coverage["event_calculus_atom_count"] == coverage["cognitive_operator_count"] == 0
        assert coverage["semantic_equivalence_checked"] is coverage["admitted"] is False
        if family in {"fol", "temporal_fol"}:
            assert coverage["modality_encoding"] == "omitted"
            assert coverage["deontic_operator_count"] == 0
        elif family == "frame_logic":
            assert coverage["modality_encoding"] == "frame_value"
            assert coverage["deontic_operator_count"] == 0
        else:
            assert coverage["modality_encoding"] == "deontic_operator"
            assert coverage["deontic_operator_count"] == 1


def test_multiple_real_compiled_clauses_keep_separate_source_and_duration_bindings():
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span
    text = ("The officer shall retain the file for at least 20 days. "
            "The agency shall retain records for at least 30 days.")
    session = AutoformalSession()
    compiled = compile_span(session, text, "multiple-duration-clauses", allow_partial=False)
    assert compiled["compiler_status"] == "compiled" and len(session.rows) == 2
    reports = []
    for row, expected_quantity in zip(session.rows, (20, 30)):
        clause = session.documents.clause(row.document_id, row.clause_id)
        report = qualification.qualify_logic_families(clause.text, row.rule, source_id=row.clause_id)
        reports.append(report)
        assert row.status == "roundtrip_ok" and report["passed"] is True
        assert report["source_sha256"] == hashlib.sha256(clause.text.encode()).hexdigest()
        slots = _parsed_frame_slots(report["families"]["frame_logic"]["formula"])
        assert slots["source_id", ()] == (row.clause_id,)
        assert slots["temporal", ("0",)] == (f"{expected_quantity} days",)
        assert slots["temporal_quantity", ("0",)] == (str(expected_quantity),)
        assert report["admitted"] is False
    assert reports[0]["source_id"] != reports[1]["source_id"]
    assert reports[0]["rule_sha256"] != reports[1]["rule_sha256"]
