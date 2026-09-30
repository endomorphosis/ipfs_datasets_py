"""Qualification parses actual exports and never promotes projections/admissions."""
from __future__ import annotations

import hashlib
import json
import re

import pytest

from ipfs_datasets_py.logic.autoformal import family_qualification as qualification


# Explicit historical fragment diagnostics are narrower than the legal floor.
HISTORICAL_SIX_FRAGMENTS = (
    "fol", "deontic_fol", "temporal_fol", "deontic_temporal_fol",
    "deontic_cognitive_event_calculus", "frame_logic",
)


def _historical_fragment_diagnostic(*args, **kwargs):
    report = qualification.qualify_logic_families(
        *args, required_families=HISTORICAL_SIX_FRAGMENTS, **kwargs)
    assert report["scope"] == "requested_fragment_syntax_diagnostic"
    assert report["full_floor_requested"] is report["full_floor_passed"] is False
    return report


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
    report = _historical_fragment_diagnostic(TEXT, RULE, source_id="officer-records")
    assert set(report["families"]) == set(HISTORICAL_SIX_FRAGMENTS)
    assert report["passed"] is True
    assert report["source_sha256"] == hashlib.sha256(TEXT.encode()).hexdigest()
    assert report["canonical_rule"] == RULE
    assert report["projection_only"] is True
    for family in HISTORICAL_SIX_FRAGMENTS:
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
    report = _historical_fragment_diagnostic(TEXT, RULE)
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
    report = _historical_fragment_diagnostic(TEXT, {**rule, "temporal_records": sidecar})
    base = _historical_fragment_diagnostic(TEXT, rule)
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
    report = _historical_fragment_diagnostic(text, compiled["rule"], source_id="gate")
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
    reports = [_historical_fragment_diagnostic(TEXT, {**rule, "temporal_records": records})
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
    report = _historical_fragment_diagnostic(TEXT, {
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
    report = _historical_fragment_diagnostic(TEXT, {
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
    report = _historical_fragment_diagnostic(TEXT, RULE)
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
        report = _historical_fragment_diagnostic(clause.text, row.rule, source_id=row.clause_id)
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


@pytest.mark.parametrize("conflict", [
    {"temporal_kind": "minimum_duration", "quantity": 21, "value": "20 days"},
    {"temporal_kind": "within_duration", "quantity": 20, "value": "20 days"},
])
@pytest.mark.parametrize("reverse", [False, True])
def test_conflicting_known_temporal_sidecars_fail_closed_for_the_same_canonical_atom(conflict, reverse):
    records = [{"temporal_kind": "minimum_duration", "quantity": 20, "value": "20 days"}, conflict]
    if reverse:
        records.reverse()
    report = qualification.qualify_logic_families(TEXT, {**RULE, "temporal": ["20 days"], "temporal_records": records})
    assert report["passed"] is False
    assert len(report["goals"]) == len(qualification.REQUIRED_FAMILIES)
    assert "conflicting_temporal_sidecars_for_canonical_atom" in report["diagnostics"][0]["code"]
    assert all(row["passed"] is False for row in report["families"].values())
    assert report["admitted"] is report["formalized"] is False


def test_identical_duplicate_temporal_sidecars_preserve_existing_export_contract():
    record = {"temporal_kind": "minimum_duration", "quantity": 20, "value": "20 days"}
    report = _historical_fragment_diagnostic(TEXT, {**RULE, "temporal": ["20 days"], "temporal_records": [record, dict(record)]})
    assert report["passed"] is True
    frame = report["families"]["frame_logic"]
    assert frame["representation_coverage"]["typed_duration_record_count"] == 2
    assert frame["representation_coverage"]["typed_duration_atom_indices"] == [0]
    assert frame["formula"].count('temporal_kind(0)->"minimum_duration"') == 2
    assert frame["formula"].count('temporal_quantity(0)->20') == 2
    assert report["admitted"] is report["formalized"] is False


def test_mandatory_eight_family_syntax_floor_does_not_qualify_full_semantics():
    report = qualification.qualify_logic_families(TEXT, RULE, source_id="full-floor")
    assert report["schema"] == "autoformal-family-qualification/v2"
    assert report["scope"] == "mandatory_legal_floor_syntax"
    assert report["full_floor_scope"] == "required_family_syntax_fragments_only"
    assert report["full_floor_requested"] is True
    assert report["missing_floor_families"] == []
    assert len(report["qualification_floor"]) == len(report["families"]) == 8
    assert report["passed"] is report["full_floor_passed"] is True
    assert all(row["passed"] for row in report["families"].values())
    assert report["goals"] == []
    assert report["full_family_semantics_covered"] is False
    assert report["schema_capability_coverage_complete"] is False
    assert report["semantic_qualification_passed"] is False
    assert report["coverage_limitations"]
    assert report["admitted"] is report["formalized"] is False


def test_cec_and_dcec_exports_keep_distinct_deontic_scope():
    report = qualification.qualify_logic_families(TEXT, RULE, required_families=("cec", "dcec"))
    assert report["required_families"] == ["cognitive_event_calculus", "deontic_cognitive_event_calculus"]
    cec, dcec = report["families"].values()
    assert cec["passed"] is dcec["passed"] is True
    assert cec["export_record"]["projection_omitted_facets"] == ["modality"]
    assert cec["representation_coverage"]["deontic_operator_count"] == 0
    assert dcec["representation_coverage"]["deontic_operator_count"] == 1
    assert qualification.validate_family_artifact("cec", dcec["formula"])["passed"] is False
    assert report["passed"] is True and report["full_floor_passed"] is False


@pytest.mark.parametrize("formula", [
    "p", "p and not q -> r", "true or false", "(p or q) iff (r and not s)",
])
def test_propositional_strict_parser_accepts_only_boolean_fragment(formula):
    report = qualification.validate_family_artifact("propositional_logic", formula)
    assert report["passed"] and report["consumed_all_input"]
    assert report["qualified_fragment"] == "nullary_propositions_and_boolean_connectives"
    assert report["deontic_operator_count"] == report["quantifier_count"] == 0
    assert report["admitted"] is report["semantic_equivalence_checked"] is False


@pytest.mark.parametrize("formula", [
    "", "p @", "p trailing", "p and", "(p or)", "Retain(x)",
    "forall x. Retain(x)", "exists x. Retain(x)", "O(p)", "F(p)",
    "box p", "always(p)", "knows[alice] p", "happens(e,t)",
])
def test_propositional_rejects_quantifiers_predicate_terms_and_other_families(formula):
    report = qualification.validate_family_artifact("pl", formula)
    assert report["family"] == "propositional"
    assert report["passed"] is report["syntax_valid"] is False
    assert report["diagnostics"]


@pytest.mark.parametrize(("formula", "events", "cognition"), [
    ("Retain(officer,records)", 0, 0),
    ("happens(e,t) and holds_at(f,t)", 2, 0),
    ("initiates(e,f,t) -> holds_at(f,t)", 2, 0),
    ("forall x:agent. Person(x) -> happens(e,t)", 1, 0),
    ("knows[alice] p", 0, 1),
    ("believes[alice] (p -> q)", 0, 1),
    ("intends[alice] (p and q)", 0, 1),
    ("knows[alice] knows[bob] p", 0, 2),
])
def test_cec_accepts_explicit_native_event_or_cognitive_fragments(formula, events, cognition):
    report = qualification.validate_family_artifact("cec", formula)
    assert report["passed"] and report["consumed_all_input"]
    assert report["family"] == "cognitive_event_calculus"
    assert report["event_calculus_atom_count"] == events
    assert report["cognitive_operator_count"] == cognition
    assert report["deontic_operator_count"] == 0
    assert "combined_cognitive_event_grammar_not_implemented" in report["composition_limitations"]
    assert report["admitted"] is report["semantic_equivalence_checked"] is False
    if cognition:
        assert "[alice]" in report["printed"]
        assert report["qualified_fragment"] == "agent_indexed_single_attitude_over_propositions"


@pytest.mark.parametrize("formula", [
    "happens(e)", "happens(e,t,extra)", "happens(e,t) @", "happens(e,t) trailing",
    "happens(e,t) and", "O(happens(e,t))", "P(report)", "F(report)",
    "obligation(report)", "forall x:agent. O(Report(x))", "not O(report)",
    "Retain(Happens(e,t))", "knows(p)", "knows p", "K(alice,p)",
    "knows[alice] p @", "knows[alice] p trailing", "knows[alice] O(p)",
    "knows[alice] Happens(e,t)", "knows[alice] believes[bob] p",
])
def test_cec_rejects_deontic_malformed_and_unimplemented_compositions(formula):
    report = qualification.validate_family_artifact("cec", formula)
    assert report["passed"] is report["syntax_valid"] is False
    assert report["diagnostics"]
    assert report["admitted"] is False


def test_new_projections_bind_source_atoms_and_disclose_every_abstraction():
    rule = {**RULE, "conditions": ["authorized"], "exceptions": ["emergency"],
            "temporal": ["within 10 days"]}
    sidecar = [{"temporal_kind": "within_duration", "quantity": 10, "value": "10 days"}]
    report = qualification.qualify_logic_families(TEXT, {**rule, "temporal_records": sidecar})
    assert report["passed"]
    fol, cec, prop = (report["families"][name] for name in ("fol", "cognitive_event_calculus", "propositional"))
    assert cec["formula"] == fol["formula"]
    assert cec["representation_coverage"]["complete_family_semantics"] is False
    assert cec["representation_coverage"]["event_calculus_atom_count"] == 0
    assert cec["representation_coverage"]["cognitive_operator_count"] == 0
    bindings = prop["export_record"]["proposition_bindings"]
    reconstructed = re.sub(r"atom_[0-9a-f]{64}", lambda match: bindings[match.group()]["source_formula"], prop["formula"])
    assert reconstructed == fol["formula"]
    assert all(symbol == "atom_" + hashlib.sha256(binding["source_formula"].encode()).hexdigest()
               for symbol, binding in bindings.items())
    assert all(binding["canonical_rule_sha256"] == report["rule_sha256"] for binding in bindings.values())
    assert prop["export_record"]["projection_omitted_facets"] == ["modality", "first_order_term_structure"]
    assert prop["representation_coverage"]["first_order_term_structure_preserved_in_formula"] is False
    assert any("within_duration(" in binding["source_formula"] for binding in bindings.values())
    assert any("exception_emergency" in binding["source_formula"] for binding in bindings.values())
    for row in (cec, prop):
        assert row["source_bound"] is True
        assert row["source_sha256"] == report["source_sha256"]
        assert row["rule_sha256"] == report["rule_sha256"]
        assert row["export_record"]["canonical_rule"] == rule
        assert row["export_record"]["atom_bindings"] == fol["export_record"]["atom_bindings"]
        assert row["admitted"] is row["semantic_equivalence_checked"] is False


def test_original_six_complete_export_records_are_byte_preserved():
    # Captured from the original six-row exporter before this change. Covers
    # source IDs, bindings, conditions, exceptions and both typed duration kinds.
    rule = {"modality": "O", "actor": "Company A", "action": "submit", "object": "backup report",
            "conditions": ["approved", "account-number"], "exceptions": ["emergency"],
            "temporal": ["at least 20 days", "within 10 days"]}
    records = qualification.export_canonical_rule_families(rule, source_id="preservation-case", temporal_records=[
        {"temporal_kind": "minimum_duration", "quantity": 20, "value": "at least 20 days"},
        {"temporal_kind": "within_duration", "quantity": 10, "value": "10 days"}])
    raw = json.dumps(records[:6], sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    assert len(records) == 8
    assert hashlib.sha256(raw).hexdigest() == "5240ae1b23671c4d3e576eb9e70fe1e88c611a7d238cfd6864a1516935116770"


def test_missing_new_export_still_fails_closed_with_a_specific_goal(monkeypatch):
    original = qualification._export_rule
    monkeypatch.setattr(qualification, "_export_rule", lambda *args: [row for row in original(*args)
        if row["target"] != "cognitive_event_calculus"])
    report = qualification.qualify_logic_families(TEXT, RULE)
    assert report["passed"] is report["full_floor_passed"] is False
    goal = next(item for item in report["goals"] if item["family"] == "cognitive_event_calculus")
    assert goal["diagnostics"] == [{"code": "cognitive_event_calculus_exporter_missing"}]
    assert goal["source_sha256"] == report["source_sha256"]
