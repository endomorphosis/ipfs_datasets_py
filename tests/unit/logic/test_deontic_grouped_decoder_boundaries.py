"""Adversarial checks for source-withheld grouped decoder request boundaries.

Semantic labels are intentionally supplied. These tests claim no automatic
source-meaning review and no general detection of covert information channels.
"""
from copy import deepcopy
from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.deontic.coordination_decoder import (
    CoordinationDecodeRequest,
    decode_coordination_request,
)
from ipfs_datasets_py.logic.autoformal.legal_coordination_evaluation import evaluate_coordination_outputs

SCHEMA = "legal-coordination-decode-request/v1"


def wire(*, scope="disjunction_of_norms", third=False):
    members = [
        {"actor": "The Registrar", "modality": "O", "action": "publish the notice"},
        {"actor": "The Registrar", "modality": "O", "action": "retain the record"},
    ]
    if third:
        members.append({"actor": "The Registrar", "modality": "O", "action": "file the report"})
    return {"schema": SCHEMA, "modal_scope": scope, "connective": "inclusive_or",
            "binding_profile": "universal_actor_predicate", "members": members}


def typed(value=None):
    return CoordinationDecodeRequest.from_dict(value if value is not None else wire())


@pytest.mark.parametrize("key", [
    "source_text", "raw_text", "source_span", "group", "group_id", "source_sha256",
    "formula", "native_ast", "target", "teacher", "declaration", "prompt",
])
def test_request_extra_source_or_teacher_channels_are_rejected(key):
    value = wire()
    value[key] = "forbidden metadata"
    with pytest.raises(ValueError):
        typed(value)


@pytest.mark.parametrize("key", ["raw_text", "actor_span", "action_span", "source", "formula", "source_sha256"])
def test_member_extra_source_or_formula_channels_are_rejected(key):
    value = wire()
    value["members"][0][key] = "forbidden metadata"
    with pytest.raises(ValueError):
        typed(value)


@pytest.mark.parametrize("slot,value", [
    ("actor", "The Secretary shall publish the notice"),
    ("action", "The Secretary shall publish the notice or shall retain records"),
    ("action", "publish the notice if funding is available"),
    ("action", "publish the notice unless approval is denied"),
    ("action", "publish the notice within thirty days"),
    ("action", "publish the notice under section 552"),
    ("action", "publish notice\nsource text"),
    ("actor", "Registrar\x00Administrator"),
    ("action", "publish notice; destroy records"),
    ("action", "publish café"),
    ("action", "publish " + "a" * 64),
])
def test_semantic_label_profile_rejects_obvious_source_sentence_and_metadata_injection(slot, value):
    request = wire()
    request["members"][0][slot] = value
    with pytest.raises(ValueError):
        typed(request)


@pytest.mark.parametrize("key,value", [
    ("schema", True), ("schema", "legal-coordination-decode-request/v99"),
    ("modal_scope", None), ("modal_scope", "automatic"),
    ("connective", "exclusive_or"), ("binding_profile", "existential_actor"),
    ("members", []), ("members", {}), ("members", True),
])
def test_wrong_wire_types_and_unsupported_semantic_profiles_are_rejected(key, value):
    request = wire()
    request[key] = value
    with pytest.raises(ValueError):
        typed(request)


@pytest.mark.parametrize("slot,value", [("actor", True), ("modality", 1), ("modality", "obligation"), ("action", None)])
def test_member_types_cannot_be_coerced_into_valid_semantic_values(slot, value):
    request = wire()
    request["members"][0][slot] = value
    with pytest.raises(ValueError):
        typed(request)


@pytest.mark.parametrize("mutation", ["actor", "operator"])
def test_outer_modal_requires_one_actor_identity_and_operator(mutation):
    request = wire(scope="modal_over_actions")
    if mutation == "actor":
        request["members"][1]["actor"] = "The Clerk"
    else:
        request["members"][1]["modality"] = "P"
    with pytest.raises(ValueError):
        decode_coordination_request(typed(request))


@pytest.mark.parametrize("slot,value", [
    ("actor", "The Clerk"), ("modality", "P"), ("action", "destroy the record"),
])
def test_valid_candidate_semantic_mutations_are_detected_against_target(slot, value):
    target = typed()
    candidate = wire()
    candidate["members"][1][slot] = value
    typed(candidate)
    result = evaluate_coordination_outputs([target], [candidate])
    assert result["cases"][0]["status"] == "failed"
    assert result["cases"][0][slot + "_equal"] is False


def test_alternative_scope_swap_is_failure_even_with_unchanged_members():
    target = typed()
    candidate = wire(scope="modal_over_actions")
    result = evaluate_coordination_outputs([target], [candidate])
    row = result["cases"][0]
    assert row["status"] == "failed"
    assert row["scope_equal"] is False
    assert row["formula_exact_match"] is False
    assert row["native_ast_exact_match"] is False


@pytest.mark.parametrize("mutation", ["drop", "duplicate", "reorder"])
def test_member_count_multiplicity_and_order_are_observable_decoder_errors(mutation):
    target = typed(wire(third=True))
    candidate = wire(third=True)
    if mutation == "drop":
        candidate["members"].pop()
    elif mutation == "duplicate":
        candidate["members"].append(deepcopy(candidate["members"][0]))
    else:
        candidate["members"].reverse()
    typed(candidate)
    row = evaluate_coordination_outputs([target], [candidate])["cases"][0]
    assert row["status"] == "failed"
    assert row["request_exact_match"] is False
    assert row["member_count_equal"] is (mutation == "reorder")


def test_metadata_leakage_in_an_otherwise_correct_output_counts_as_failure():
    target = typed()
    output = wire()
    output["source_text"] = "The Registrar shall publish notice or shall retain records."
    row = evaluate_coordination_outputs([target], [output])["cases"][0]
    assert row["status"] == "failed"
    assert row["blockers"]


def test_typed_dataclass_mutation_is_revalidated_by_decoder():
    target = typed()
    with pytest.raises(ValueError):
        bad_member = replace(target.members[0], action="publish notice if approval is granted")
        bad = replace(target, members=(bad_member, *target.members[1:]))
        decode_coordination_request(bad)


@pytest.mark.parametrize("targets_count,outputs_count,expected_missing,expected_extra", [
    (2, 1, 1, 0), (1, 2, 0, 1), (2, 0, 2, 0), (0, 1, 0, 1),
])
def test_missing_and_unexpected_outputs_stay_in_the_denominator(targets_count, outputs_count, expected_missing, expected_extra):
    result = evaluate_coordination_outputs([typed() for _ in range(targets_count)],
                                          [wire() for _ in range(outputs_count)])
    assert result["case_count"] == max(targets_count, outputs_count)
    assert len(result["cases"]) == result["case_count"]
    assert result["missing_output_count"] == expected_missing
    assert result["unexpected_output_count"] == expected_extra
    assert result["passed_count"] == min(targets_count, outputs_count)
    assert result["failed_count"] == expected_missing + expected_extra
    assert result["all_outputs_agree_with_target_ir"] is False
    assert result["measure_rates"]["semantic_ir_agreement"] == min(targets_count, outputs_count) / max(targets_count, outputs_count)


def test_empty_evaluation_never_reports_vacuous_perfect_accuracy():
    result = evaluate_coordination_outputs([], [])
    assert result["case_count"] == 0
    assert result["all_outputs_agree_with_target_ir"] is False
    assert "empty_reference_set" in result["blockers"]
    assert all(value == 0 for value in result["measure_rates"].values())


@pytest.mark.parametrize("candidate", [None, True, [], "{invalid-json", {"members": []}, 1.0])
def test_malformed_candidates_are_counted_failures_without_target_fallback(candidate):
    result = evaluate_coordination_outputs([typed()], [candidate])
    assert result["invalid_output_count"] == result["failed_count"] == result["case_count"] == 1
    assert result["passed_count"] == 0
    assert all(value == 0 for value in result["measure_counts"].values())
    assert "candidate_formula" not in result["cases"][0]


def test_normalized_ir_agreement_is_distinct_from_exact_wire_agreement():
    target = typed()
    candidate = wire()
    for member in candidate["members"]:
        member["actor"] = "registrar"
        member["action"] = member["action"].upper().replace(" ", "  ")
    row = evaluate_coordination_outputs([target], [candidate])["cases"][0]
    assert row["status"] == "passed"
    assert row["semantic_ir_agreement"] is True
    assert row["request_exact_match"] is False
    assert row["native_ast_exact_match"] is True


def test_punctuation_collision_in_action_label_is_a_real_ir_mismatch():
    left = wire()
    left["members"][0]["action"] = "file a-b"
    right = deepcopy(left)
    right["members"][0]["action"] = "file a b"
    row = evaluate_coordination_outputs([typed(left)], [right])["cases"][0]
    assert row["action_equal"] is row["native_ast_exact_match"] is False
    assert row["status"] == "failed"


def test_supported_apostrophe_unicode_stays_bound_to_its_literal_label():
    value = wire()
    value["members"][0]["action"] = "publish agency’s notice"
    result = decode_coordination_request(typed(value))
    assert "agency’s notice" in result["normalized_text"]
    assert all(row["symbol"].isascii() for row in result["mapping"]["action_symbols"])
    assert result["source_semantics_verified"] is result["proof_ready"] is False


def test_group_decoder_requires_a_typed_request_and_never_accepts_its_output_as_input():
    request = typed()
    decoded = decode_coordination_request(request)
    with pytest.raises(ValueError):
        decode_coordination_request(request.to_dict())
    with pytest.raises(ValueError):
        CoordinationDecodeRequest.from_dict(decoded)


@pytest.mark.parametrize("scope", ["modal_over_actions", "disjunction_of_norms"])
def test_controlled_decoder_text_exposes_caller_scope_and_retains_unreviewed_status(scope):
    result = decode_coordination_request(typed(wire(scope=scope)))
    assert "Declared modal scope: " + scope in result["normalized_text"]
    assert result["context"] == "source_withheld_semantic_ir"
    assert result["decoder_kind"] == "deterministic_ir_renderer"
    assert result["source_semantics_verified"] is result["admitted"] is result["proof_ready"] is False
    assert result["requires_validation"] is True


def test_decoder_has_no_dependency_on_group_or_source_reconstruction(monkeypatch):
    from ipfs_datasets_py.logic.deontic.utils import deontic_parser
    request = typed()
    def forbidden(*args, **kwargs):
        raise AssertionError("Original source/group reconstruction was consulted")
    # The source-only integration need not install the optional legacy bridge.
    # If it is absent, prove that any attempted fallback import fails. If it
    # exists in a later integration, poison its real source-recovery helpers.
    import importlib
    import importlib.util
    import sys
    for module_name in (
        "ipfs_datasets_py.logic.deontic.coordination",
        "ipfs_datasets_py.logic.autoformal.legal_coordination",
    ):
        if importlib.util.find_spec(module_name) is None:
            monkeypatch.setitem(sys.modules, module_name, None)
            with pytest.raises(ModuleNotFoundError):
                importlib.import_module(module_name)
        else:
            optional_module = importlib.import_module(module_name)
            for helper in ("build_coordination_groups", "reconstruct_source", "compile_coordination_group",
                           "reconstruct_compiled_group", "coordination_decode_request_from_compiled"):
                if hasattr(optional_module, helper):
                    monkeypatch.setattr(optional_module, helper, forbidden)
                    with pytest.raises(AssertionError):
                        getattr(optional_module, helper)()
    monkeypatch.setattr(deontic_parser, "extract_normative_elements", forbidden)
    result = decode_coordination_request(request)
    assert result["structure_compiled"] is True



@pytest.mark.parametrize("scope,expected_modal_count", [("modal_over_actions", 1), ("disjunction_of_norms", 3)])
@pytest.mark.parametrize("operator", ["O", "P", "F"])
def test_native_tree_preserves_declared_modal_placement_and_deontic_operator(scope, expected_modal_count, operator):
    value = wire(scope=scope, third=True)
    for member in value["members"]:
        member["modality"] = operator
    result = decode_coordination_request(typed(value))
    def dictionaries(value):
        if isinstance(value, dict):
            yield value
            for item in value.values():
                yield from dictionaries(item)
        elif isinstance(value, list):
            for item in value:
                yield from dictionaries(item)
    nodes = list(dictionaries(result["native_ast"]))
    modals = [node for node in nodes if node.get("node_type") == "DeonticFormula"]
    assert len(modals) == expected_modal_count
    assert all(node["operator"] == {"enum": "DeonticOperator", "value": operator} for node in modals)
    assert not any("Temporal" in str(node.get("node_type", "")) for node in nodes)
    if scope == "modal_over_actions":
        assert result["native_ast"]["node_type"] == "DeonticFormula"
    else:
        assert result["native_ast"]["node_type"] == "BinaryFormula"
        assert result["native_ast"]["operator"]["value"] == "∨"
