"""Named diagnostics reuse real typed fixtures and the original pair owner.

These are authored structural distinctions, not statutory truth, reconstruction
efficacy or corpus evaluation. No model, optimizer, solver or build is invoked.
"""
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys

import pytest

from ipfs_datasets_py.logic.autoformal import legal_relational_reconstruction_diagnostics_v1 as owner


def _fixtures():
    path = Path(__file__).with_name("test_legal_relational_reconstruction_v1.py")
    name = "_reconstruction_diagnostics_existing_fixtures"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


legacy = _fixtures()
GROUPS = {"binder_quantifier_topology", "modal_operator_placement",
          "predicate_ordered_arguments_roles", "connective_negation_context"}


def prepared(left, right):
    reference, left_raw = legacy.prepare_fragment(left)
    candidate, right_raw = legacy.prepare_fragment(right)
    args = legacy.arguments(reference, candidate, left_raw, right_raw)
    report = owner.prepare_relational_reconstruction_diagnostics_v1(reference, candidate, **args)
    return report, reference, candidate, args


def checked(report, reference, candidate, args):
    return owner.validate_relational_reconstruction_diagnostics_v1(
        report, reference, candidate,
        expected_diagnostics_sha256=owner.relational_reconstruction_diagnostics_sha256(report), **args)


def test_self_pair_preserves_original_ledger_replay_and_no_authority():
    request = legacy._FIXTURE.approval_request()
    original = deepcopy(request)
    report, left, right, args = prepared(request, request)
    assert request == original
    assert report["schema"] == "legal-relational-reconstruction-diagnostics/v1"
    assert set(report["groups"]) == GROUPS
    assert all(group["status"] == "equal" and group["equal"] is True for group in report["groups"].values())
    assert report["comparisons"] == report["comparison"]["comparisons"]
    assert all(report["comparisons"].values())
    assert report["comparison_sha256"] == legacy.owner.relational_reconstruction_comparison_sha256(report["comparison"])
    assert report["valid_input_pair_only"] and report["invalid_inputs_refused"]
    assert report["abstention_coverage_evaluated"] is False
    assert report["unavailable_output_policy"] == "retain_enrolled_outcome_with_structural_metrics_unavailable"
    assert all(value is False for value in report["authority"].values())
    assert report["training_mask"] == report["evaluation_gold_mask"] == 0
    assert checked(report, left, right, args) == report


@pytest.mark.parametrize("change", ["alpha", "artifact_ids"])
def test_lexical_alpha_and_artifact_names_do_not_change_named_structural_groups(change):
    original = legacy._FIXTURE.approval_request()
    altered = legacy.rename_bound_variables(original,
        {"actor": "person", "recipient": "beneficiary", "approver": "official"}) if change == "alpha" else legacy.change_artifact_ids(original)
    report, _, _, _ = prepared(original, altered)
    assert report["comparisons"]["exact_typed_expression_equal"] is False
    assert report["comparisons"]["lexical_alpha_structure_equal"] is True
    assert all(group["equal"] is True for group in report["groups"].values())
    if change == "alpha":
        assert report["comparisons"]["declared_structure_equal"] is False
        assert any("binder_name" in row["declared_differences"] for row in report["comparison"]["feature_ledger"])


def _changed(mutation):
    binders = [("actor", "forall"), ("recipient", "exists")]
    original = legacy.relation_request(binders=binders)
    if mutation == "argument_swap":
        altered = legacy.relation_request(arguments=("recipient", "actor"), binders=binders)
    elif mutation == "binding_capture":
        altered = legacy.relation_request(arguments=("recipient", "recipient"), binders=binders)
    elif mutation == "quantifier_kind":
        altered = legacy.relation_request(binders=[("actor", "exists"), ("recipient", "exists")])
    elif mutation == "quantifier_order":
        altered = legacy.relation_request(binders=list(reversed(binders)))
    elif mutation == "missing_binder":
        altered = legacy.relation_request(arguments=("actor", "actor"), binders=[("actor", "forall")])
    elif mutation == "predicate":
        altered = legacy.relation_request(name="Authorizes", binders=binders)
    elif mutation == "ordered_roles":
        altered = legacy.relation_request(roles=("recipient", "actor"), binders=binders)
    elif mutation in ("modal_O", "modal_F"):
        original = legacy._FIXTURE.approval_request()
        altered = legacy._FIXTURE.approval_request(operator=mutation[-1])
    elif mutation == "modal_placement":
        original = legacy._FIXTURE.approval_request(sufficient=True)
        altered = legacy._FIXTURE.approval_request(inner=True)
    elif mutation == "implication_direction":
        original = legacy._FIXTURE.approval_request()
        altered = legacy._FIXTURE.approval_request(sufficient=True)
    elif mutation == "connective":
        original, altered = legacy._FIXTURE.action_request(), legacy._FIXTURE.action_request("and")
    elif mutation == "negation":
        altered = legacy.relation_request(binders=binders, negated=True)
    else:
        raise AssertionError("unknown authored mutation")
    return original, altered


@pytest.mark.parametrize("mutation,group", [
    ("argument_swap", "predicate_ordered_arguments_roles"),
    ("binding_capture", "binder_quantifier_topology"),
    ("quantifier_kind", "binder_quantifier_topology"),
    ("quantifier_order", "binder_quantifier_topology"),
    ("missing_binder", "binder_quantifier_topology"),
    ("predicate", "predicate_ordered_arguments_roles"),
    ("ordered_roles", "predicate_ordered_arguments_roles"),
    ("modal_O", "modal_operator_placement"),
    ("modal_F", "modal_operator_placement"),
    ("modal_placement", "modal_operator_placement"),
    ("implication_direction", "connective_negation_context"),
    ("connective", "connective_negation_context"),
    ("negation", "connective_negation_context"),
])
def test_structural_rivals_keep_scope_order_binding_and_operator_differences(mutation, group):
    report, left, right, _ = prepared(*_changed(mutation))
    assert report["comparisons"]["lexical_alpha_structure_equal"] is False
    result = report["groups"][group]
    assert result["status"] == "different" and result["equal"] is False
    assert result["reference_only_paths"] or result["candidate_only_paths"] or result["different_paths"] or not all(result["declaration_checks"].values())
    # These rivals have equal node/quantifier/modal/predicate counts. Counts alone
    # cannot establish binder references, modal scope or argument/role order.
    if mutation not in ("missing_binder", "negation"):
        assert left["counts"] == right["counts"]


@pytest.mark.parametrize("reverse", [False, True])
def test_added_or_dropped_structure_retains_every_group_path_and_missing_side(reverse):
    full = legacy._FIXTURE.action_request()
    dropped = legacy._FIXTURE.action_request(dropped=True)
    report, _, _, _ = prepared(dropped if reverse else full, full if reverse else dropped)
    all_paths = {entry["typed_path"] for entry in report["comparison"]["feature_ledger"]}
    side = "candidate_only_paths" if reverse else "reference_only_paths"
    assert any(group[side] for group in report["groups"].values())
    for group in report["groups"].values():
        assert {row["typed_path"] for row in group["rows"]} <= all_paths
        for row in group["rows"]:
            if row["presence"] != "both":
                assert row["equal"] is None
                assert row["reference" if row["presence"] == "candidate_only" else "candidate"] is None


def test_absent_modal_and_connective_groups_are_not_successes():
    request = legacy.relation_request()
    report, _, _, _ = prepared(request, request)
    for name in ("modal_operator_placement", "connective_negation_context"):
        assert report["groups"][name]["status"] == "not_applicable"
        assert report["groups"][name]["equal"] is None
        assert report["groups"][name]["rows"] == []


@pytest.mark.parametrize("field", ["expected_reference_request_sha256", "expected_candidate_request_sha256",
                                  "expected_reference_report_sha256", "expected_candidate_report_sha256"])
def test_each_original_input_pin_is_required(field):
    request = legacy.relation_request()
    _, reference, candidate, args = prepared(request, request)
    args[field] = legacy.sha(b"different original")
    with pytest.raises(owner.RelationalReconstructionDiagnosticsError):
        owner.prepare_relational_reconstruction_diagnostics_v1(reference, candidate, **args)


@pytest.mark.parametrize("mutation", ["group", "comparison", "authority"])
def test_self_rehashed_output_cannot_replace_original_bound_regeneration(mutation):
    request = legacy._FIXTURE.approval_request()
    report, reference, candidate, args = prepared(request, request)
    altered = deepcopy(report)
    if mutation == "group":
        altered["groups"]["binder_quantifier_topology"]["rows"].pop()
    elif mutation == "comparison":
        altered["comparison"]["comparisons"]["lexical_alpha_structure_equal"] = False
    else:
        altered["authority"]["accepted"] = True
    with pytest.raises(owner.RelationalReconstructionDiagnosticsError):
        checked(altered, reference, candidate, args)


@pytest.mark.parametrize("unavailable", [None, {}, {"status": "incomplete"}])
def test_unavailable_or_incomplete_candidate_refuses_instead_of_a_false_metric(unavailable):
    request = legacy.relation_request()
    reference, raw = legacy.prepare_fragment(request)
    args = legacy.arguments(reference, unavailable, raw, raw)
    with pytest.raises(owner.RelationalReconstructionDiagnosticsError):
        owner.prepare_relational_reconstruction_diagnostics_v1(reference, unavailable, **args)
