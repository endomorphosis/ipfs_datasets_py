"""An opt-in custody gate retains current qualified output without authority."""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.legal_ir import duration_bound_qualified as subject
from ipfs_datasets_py.logic.legal_ir import temporal_bindings as binding_owner


# Load only the neighboring authored fixture helpers, independent of pytest's
# path import mode. There is no model, subprocess or backend in that module.
_spec = importlib.util.spec_from_file_location("duration_custody_authored_test_fixtures",
    Path(__file__).with_name("test_temporal_bindings.py"))
fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixtures)


def native_fixture(*, literal="within 7 days", temporal=True, context="", condition="paid"):
    from ipfs_datasets_py.logic.autoformal import legal_canonical_qualified as native
    args, _ = fixtures.fixture_binding(literal=literal, temporal=temporal, context=context, condition=condition)
    interpretation = native.interpretation_skeleton(args[0])
    for formula in interpretation["formulas"]:
        formula["activation_scope"] = "all_conditions_at_evaluation_origin"
        formula["exception_scope"] = "activation_time_waiver"
        for entry in formula["conditions"] + formula["exceptions"]:
            entry["expression"] = dict(op="atom", predicate=dict(name="authored_" + entry["source_text"].split()[0], arguments=[]))
        if formula["temporal"] is not None:
            formula["temporal"].update({key: args[5][0][key] for key in binding_owner.CLOCK_SEMANTICS})
    args[1] = interpretation
    expected = fixtures.pins(args)
    report = binding_owner.prepare_duration_bindings(*args, **expected)
    expected["expected_report_sha256"] = binding_owner.digest(report)
    return report, args, expected


def prepare(report, args, expected):
    return subject.prepare_duration_bound_qualified(report, *args, **expected)


def test_exact_existing_qualified_output_is_retained_without_backend_or_semantic_authority():
    from ipfs_datasets_py.logic.autoformal import legal_canonical_qualified as native
    report, args, expected = native_fixture()
    before = copy.deepcopy((report, args))
    original = native.prepare_canonical_qualified(args[0], args[1])
    output = prepare(report, args, expected)
    assert (report, args) == before
    assert binding_owner._wire(output["native_output"]) == binding_owner._wire(original)
    assert output["native_output_sha256"] == binding_owner.digest(original)
    assert output["binding_report"] == report
    assert output["binding_report_sha256"] == expected["expected_report_sha256"]
    assert output["native_lowering_prepared"] is output["native_lowering_performed"] is output["lean_source_prepared"] is True
    assert output["backend_build_required"] == "lake build legal"
    assert output["duration_count"] == 1
    assert all(output[field] is False for field in subject.FALSE)
    assert output["model_calls"] == output["prover_calls"] == 0
    assert all(type(value) is int and value == 0 for value in output["masks"].values())
    assert output["content_sha256"] == binding_owner.digest({k: v for k, v in output.items() if k != "content_sha256"})
    assert str(Path(subject.__file__).resolve()) in output["producer_pins"]
    assert str(Path(binding_owner.__file__).resolve()) in output["producer_pins"]
    result = subject.validate_duration_bound_qualified(output, report, *args, **expected)
    assert result["native_output_sha256"] == output["native_output_sha256"]
    assert all(result[field] is False for field in subject.FALSE)


@pytest.mark.parametrize("literal", ["within 1 hour", "within 1201 days", "for at least 7 hours"])
def test_plain_supported_duration_profiles_reach_the_unchanged_native_owner(literal):
    report, args, expected = native_fixture(literal=literal)
    output = prepare(report, args, expected)
    assert output["native_output"]["interpretation"] == args[1]
    assert literal in output["native_output"]["original_canonical_ir"]["rules"][0]["temporal"]


def test_zero_duration_keeps_explicit_instantaneous_qualified_output_and_zero_denominator():
    report, args, expected = native_fixture(temporal=False)
    output = prepare(report, args, expected)
    assert output["duration_count"] == 0 and output["binding_report"]["joins"] == []
    assert "explicit-clock:instantaneous" in output["native_output"]["lean_body"]


@pytest.mark.parametrize("mutation", ["wrong_report_pin", "wrong_candidate_pin", "wrong_interpretation_pin", "wrong_scope_pin",
    "wrong_declaration_pin", "wrong_leaf", "swapped_geometry", "missing_clock", "report_authority", "derived_quantity"])
def test_all_custody_refusals_happen_before_native_owner_import_or_emission(monkeypatch, mutation):
    report, args, expected = native_fixture()

    def native_forbidden():
        pytest.fail("native owner imported before the failing custody/context gate")

    monkeypatch.setattr(subject, "_owner", native_forbidden)
    if mutation == "wrong_report_pin":
        expected["expected_report_sha256"] = "0" * 64
    elif mutation == "wrong_candidate_pin":
        expected["expected_candidate_sha256"] = "0" * 64
    elif mutation == "wrong_interpretation_pin":
        expected["expected_interpretation_sha256"] = "0" * 64
    elif mutation == "wrong_scope_pin":
        expected["expected_scope_input_sha256"] = "0" * 64
    elif mutation == "wrong_declaration_pin":
        expected["expected_scope_declaration_sha256"] = "0" * 64
    elif mutation == "wrong_leaf":
        args[4][0]["scope_leaf_path"] = "/rules/0/qualifiers/conditions"
    elif mutation == "swapped_geometry":
        occurrence = next(item for item in args[3]["occurrences"] if item["facet"] == "conditions")
        args[4][0]["duration_anchor"] = fixtures.geometry(occurrence["anchor"], args[2])
    elif mutation == "missing_clock":
        args[5].clear()
    elif mutation == "report_authority":
        report["qualified"] = True
        report["content_sha256"] = binding_owner.digest({k: v for k, v in report.items() if k != "content_sha256"})
        expected["expected_report_sha256"] = binding_owner.digest(report)
    else:
        report["joins"][0]["declared_clock"]["quantity"] = 1
        report["content_sha256"] = binding_owner.digest({k: v for k, v in report.items() if k != "content_sha256"})
        expected["expected_report_sha256"] = binding_owner.digest(report)
    with pytest.raises(ValueError):
        prepare(report, args, expected)


def test_declared_context_transport_cannot_be_silently_lowered_as_no_context(monkeypatch):
    report, args, expected = native_fixture(context="Complete authored context retained without semantic resolution.")
    assert report["duration_count"] == 1

    def native_forbidden():
        pytest.fail("context refusal occurred after native owner import")

    monkeypatch.setattr(subject, "_owner", native_forbidden)
    with pytest.raises(ValueError, match="requires none_required context"):
        prepare(report, args, expected)


@pytest.mark.parametrize("mutation", ["unset_activation", "unsupported_exception_scope", "missing_condition", "bad_expression", "wrong_mapping", "wrong_formula"])
def test_native_interpretation_validity_remains_with_existing_owner(mutation):
    report, args, expected = native_fixture()
    if mutation == "unset_activation":
        args[1]["formulas"][0]["activation_scope"] = None
    elif mutation == "unsupported_exception_scope":
        args[1]["formulas"][0]["exception_scope"] = "inferred"
    elif mutation == "missing_condition":
        args[1]["formulas"][0]["conditions"].clear()
    elif mutation == "bad_expression":
        args[1]["formulas"][0]["conditions"][0]["expression"] = None
    elif mutation == "wrong_mapping":
        args[1]["mapping_sha256"] = "f" * 64
    else:
        args[1]["formulas"][0]["original_formula_sha256"] = "f" * 64
    expected = fixtures.pins(args)
    report = binding_owner.prepare_duration_bindings(*args, **expected)
    assert report["native_interpretation_validated"] is False
    expected["expected_report_sha256"] = binding_owner.digest(report)
    with pytest.raises(ValueError):
        prepare(report, args, expected)


def test_a_duration_looking_activation_condition_stays_a_native_refusal():
    report, args, expected = native_fixture(condition="within 7 days")
    assert report["duration_count"] == 1
    with pytest.raises(ValueError, match="duration_literal_cannot_be_an_activation_atom"):
        prepare(report, args, expected)


@pytest.mark.parametrize("mutation", ["native_lean", "native_interpretation", "report_clock", "qualification", "mask", "extra", "remove_report"])
def test_resigned_native_or_derived_output_tampering_fails_exact_replay(mutation):
    report, args, expected = native_fixture()
    output = prepare(report, args, expected)
    if mutation == "native_lean":
        output["native_output"]["lean_body"] += "\n-- changed\n"
    elif mutation == "native_interpretation":
        output["native_output"]["interpretation"]["formulas"][0]["temporal"]["quantity"] = 1
    elif mutation == "report_clock":
        output["binding_report"]["clock_declarations"][0]["quantity"] = 1
    elif mutation == "qualification":
        output["family_qualified"] = True
    elif mutation == "mask":
        output["masks"]["strong_semantic_fit"] = 1
    elif mutation == "extra":
        output["approved"] = True
    else:
        del output["binding_report"]
    output["content_sha256"] = binding_owner.digest({k: v for k, v in output.items() if k != "content_sha256"})
    with pytest.raises(ValueError, match="exact replay"):
        subject.validate_duration_bound_qualified(output, report, *args, **expected)


def test_caller_cannot_mutate_retained_native_output_or_binding_report():
    report, args, expected = native_fixture()
    output = prepare(report, args, expected)
    before = copy.deepcopy(output)
    report["joins"].clear()
    args[1]["formulas"][0]["temporal"]["quantity"] = 99
    assert output == before


def test_producer_endpoint_changes_refuse_prepared_output(monkeypatch):
    report, args, expected = native_fixture()
    current = subject.producer_pins()
    values = iter((current, {**current, "/changed": "0" * 64}))
    monkeypatch.setattr(subject, "producer_pins", lambda: next(values))
    with pytest.raises(ValueError, match="producer endpoints changed"):
        prepare(report, args, expected)
