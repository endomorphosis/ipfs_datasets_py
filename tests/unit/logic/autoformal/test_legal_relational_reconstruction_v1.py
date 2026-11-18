"""Paired authored structures diagnose reconstruction without legal accuracy.

Fixtures use the real existing TypedExpression builders and relational owner.
The expected alpha and structural distinctions are authored independently; no
statutory payload, labels, model, prover or replacement product namespace is used.
"""
from __future__ import annotations

import builtins
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

from ipfs_datasets_py.logic.autoformal import legal_relational_norm_v1 as relational
from ipfs_datasets_py.logic.autoformal import legal_relational_reconstruction_v1 as owner
from ipfs_datasets_py.logic.syntax_core import ast


def _load_fixture():
    path = Path(__file__).with_name("test_legal_relational_norm_v1.py")
    name = "_relational_reconstruction_authored_fixtures"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_FIXTURE = _load_fixture()


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(wire(value))


def transport(value):
    return json.dumps(value, sort_keys=True, indent=2,
                      ensure_ascii=False, allow_nan=False).encode("utf-8") + b"\n"


def prepare_fragment(request, *, raw=None):
    raw = wire(request) if raw is None else raw
    return relational.prepare_relational_norm_v1(raw, expected_request_sha256=sha(raw)), raw


def arguments(reference, candidate, reference_raw, candidate_raw, **overrides):
    return {
        "reference_request_raw": reference_raw,
        "candidate_request_raw": candidate_raw,
        "expected_reference_request_sha256": sha(reference_raw),
        "expected_candidate_request_sha256": sha(candidate_raw),
        "expected_reference_report_sha256": digest(reference),
        "expected_candidate_report_sha256": digest(candidate),
        **overrides,
    }


def compare(reference_request, candidate_request, *, reference_raw=None, candidate_raw=None):
    reference, reference_raw = prepare_fragment(reference_request, raw=reference_raw)
    candidate, candidate_raw = prepare_fragment(candidate_request, raw=candidate_raw)
    result = owner.prepare_relational_reconstruction_comparison_v1(
        reference, candidate, **arguments(reference, candidate, reference_raw, candidate_raw),
    )
    return result, reference, candidate, reference_raw, candidate_raw


def validate(result, reference, candidate, reference_raw, candidate_raw, **overrides):
    return owner.validate_relational_reconstruction_comparison_v1(
        result, reference, candidate, expected_comparison_sha256=digest(result),
        **arguments(reference, candidate, reference_raw, candidate_raw, **overrides),
    )


def relation_request(*, name="Relates", arguments=("actor", "recipient"),
                     roles=("actor", "recipient"), binders=None, negated=False):
    builder = _FIXTURE.Builder()
    body = builder.atom(name, *arguments)
    if negated:
        body = ast.mk_not(builder.nid(), body)
    if binders is None:
        binders = [(argument, "forall") for argument in dict.fromkeys(arguments)]
    return _FIXTURE.request_for(builder, body, [(name, roles)], binders)


def change_artifact_ids(request):
    result = deepcopy(request)
    def visit(value):
        if type(value) is dict:
            for key, child in value.items():
                if key in {"node_id", "expression_id", "signature_id"}:
                    value[key] = "changed:" + child
                else:
                    visit(child)
        elif type(value) is list:
            for child in value:
                visit(child)
    visit(result["expression"])
    return _FIXTURE.reseal_expression(result)


def rename_bound_variables(request, rename):
    result = deepcopy(request)
    def visit(value):
        if type(value) is dict:
            if value.get("kind") == "variable" and value.get("symbol") in rename:
                value["symbol"] = rename[value["symbol"]]
            if "name" in value and "sort" in value and value["name"] in rename:
                value["name"] = rename[value["name"]]
            for child in value.values():
                visit(child)
        elif type(value) is list:
            for child in value:
                visit(child)
    visit(result["expression"]["root"])
    return _FIXTURE.reseal_expression(result)


@pytest.fixture(scope="module")
def base_request():
    return _FIXTURE.approval_request()


@pytest.fixture(scope="module")
def base_fragment(base_request):
    return prepare_fragment(base_request)


COMPARISON_FIELDS = {
    "exact_typed_expression_equal", "family_profile_equal", "signature_declarations_equal",
    "argument_roles_equal", "declared_structure_equal", "lexical_alpha_structure_equal",
}
FEATURE_FIELDS = {
    "kind", "node_id", "native_path", "symbol", "sort", "ordered_child_paths",
    "binder_paths", "binder_name", "binding_quantifier_path", "quantifier_kind",
    "predicate_symbol", "predicate_typed_path", "predicate_argument_index",
    "declared_argument_role", "argument_roles", "modal_operator",
    "extension_payload_schema", "extension_family", "extension_profile",
    "extension_features", "extension_payload", "modal_ancestry", "connective_ancestry",
}


def assert_unreviewed(result):
    assert set(result) == {
        "schema", "profile", "status", "reference", "candidate", "comparisons",
        "signature_diagnostics", "role_diagnostics", "feature_ledger",
        "reference_only_paths", "candidate_only_paths", "valid_input_pair_only",
        "invalid_inputs_refused", "abstention_coverage_evaluated", "producer_pins",
        "authority", "training_mask", "evaluation_gold_mask", "limitations",
    }
    assert result["schema"] == "legal-relational-reconstruction-comparison/v1"
    assert result["profile"] == "paired-valid-authored-relational-structure-diagnostics/v1"
    assert result["status"] == "unreviewed_valid_relational_pair_compared"
    assert result["valid_input_pair_only"] is True
    assert result["invalid_inputs_refused"] is True
    assert result["abstention_coverage_evaluated"] is False
    assert set(result["comparisons"]) == COMPARISON_FIELDS
    assert all(type(value) is bool for value in result["comparisons"].values())
    assert result["authority"] and all(value is False for value in result["authority"].values())
    assert type(result["training_mask"]) is int and result["training_mask"] == 0
    assert type(result["evaluation_gold_mask"]) is int and result["evaluation_gold_mask"] == 0
    assert owner.relational_reconstruction_comparison_sha256(result) == digest(result)
    for row in result["feature_ledger"]:
        assert set(row) == {"typed_path", "presence", "reference", "candidate",
                            "declared_features_equal", "declared_differences", "identity_differences"}
        for side in ("reference", "candidate"):
            assert row[side] is None or set(row[side]) == FEATURE_FIELDS


def assert_complete_mapping_union(result, reference, candidate):
    left = [row["typed_path"] for row in reference["structural_mapping"]]
    right = [row["typed_path"] for row in candidate["structural_mapping"]]
    expected = left + [path for path in right if path not in set(left)]
    rows = result["feature_ledger"]
    assert [row["typed_path"] for row in rows] == expected
    assert len(expected) == len(set(expected))
    assert result["reference_only_paths"] == [path for path in left if path not in set(right)]
    assert result["candidate_only_paths"] == [path for path in right if path not in set(left)]
    for row in rows:
        path = row["typed_path"]
        presence = "both" if path in left and path in right else "reference_only" if path in left else "candidate_only"
        assert row["presence"] == presence
        if presence != "both":
            assert row["declared_features_equal"] is None
            assert row["candidate" if presence == "reference_only" else "reference"] is None


def test_self_pair_retains_complete_authoritative_mapping_and_zero_authority(base_request):
    before = deepcopy(base_request)
    result, reference, candidate, left_raw, right_raw = compare(base_request, base_request)
    assert_unreviewed(result)
    assert all(result["comparisons"].values())
    assert_complete_mapping_union(result, reference, candidate)
    assert all(row["declared_features_equal"] is True and row["declared_differences"] == []
               and row["identity_differences"] == [] for row in result["feature_ledger"])
    assert validate(result, reference, candidate, left_raw, right_raw) == result
    assert base_request == before


def test_id_only_changes_are_exactly_distinguished_from_declared_and_alpha_structure(base_request):
    changed = change_artifact_ids(base_request)
    result, reference, candidate, left_raw, right_raw = compare(base_request, changed)
    assert_unreviewed(result)
    assert result["comparisons"] == {
        "exact_typed_expression_equal": False, "family_profile_equal": True,
        "signature_declarations_equal": True, "argument_roles_equal": True,
        "declared_structure_equal": True, "lexical_alpha_structure_equal": True,
    }
    assert_complete_mapping_union(result, reference, candidate)
    changed_rows = [row for row in result["feature_ledger"] if row["identity_differences"]]
    assert changed_rows and all(row["identity_differences"] == ["node_id"] for row in changed_rows)
    assert all(row["declared_differences"] == [] for row in result["feature_ledger"])
    assert result["reference"]["declared_structure_sha256"] == result["candidate"]["declared_structure_sha256"]
    assert result["reference"]["typed_expression_full_canonical_sha256"] != result["candidate"]["typed_expression_full_canonical_sha256"]
    assert validate(result, reference, candidate, left_raw, right_raw) == result


@pytest.mark.parametrize("rename", [
    {"actor": "person", "recipient": "beneficiary", "approver": "official"},
    {"actor": "recipient", "recipient": "actor", "approver": "authorizer"},
])
def test_consistent_lexical_binder_renaming_preserves_alpha_without_erasing_names(base_request, rename):
    changed = rename_bound_variables(base_request, rename)
    result, reference, candidate, left_raw, right_raw = compare(base_request, changed)
    assert_unreviewed(result)
    assert result["comparisons"] == {
        "exact_typed_expression_equal": False, "family_profile_equal": True,
        "signature_declarations_equal": True, "argument_roles_equal": True,
        "declared_structure_equal": False, "lexical_alpha_structure_equal": True,
    }
    assert_complete_mapping_union(result, reference, candidate)
    assert any("binder_name" in row["declared_differences"] for row in result["feature_ledger"])
    assert any("symbol" in row["declared_differences"] for row in result["feature_ledger"])
    assert validate(result, reference, candidate, left_raw, right_raw) == result


@pytest.mark.parametrize("reordered", ["sorts", "predicates", "role_rows", "all"])
def test_signature_and_role_row_declaration_order_is_normalized_without_reordering_arguments(
        base_request, reordered):
    changed = deepcopy(base_request)
    if reordered in {"sorts", "all"}:
        changed["expression"]["signature"]["sorts"].reverse()
    if reordered in {"predicates", "all"}:
        changed["expression"]["signature"]["symbols"].reverse()
    if reordered in {"role_rows", "all"}:
        changed["argument_roles"].reverse()
    changed = _FIXTURE.reseal_expression(changed)
    result, reference, candidate, _, _ = compare(base_request, changed)
    assert_unreviewed(result)
    assert result["comparisons"]["family_profile_equal"] is True
    assert result["comparisons"]["signature_declarations_equal"] is True
    assert result["comparisons"]["argument_roles_equal"] is True
    assert result["comparisons"]["declared_structure_equal"] is True
    assert result["comparisons"]["lexical_alpha_structure_equal"] is True
    assert_complete_mapping_union(result, reference, candidate)


def test_raw_transport_hashes_remain_separate_from_full_typed_expression_identity(base_request):
    compact, pretty = wire(base_request), transport(base_request)
    result, reference, candidate, left_raw, right_raw = compare(
        base_request, base_request, reference_raw=compact, candidate_raw=pretty,
    )
    assert_unreviewed(result)
    assert compact != pretty and sha(compact) != sha(pretty)
    assert all(result["comparisons"].values())
    assert reference != candidate and digest(reference) != digest(candidate)
    reference_fields = {
        "schema", "profile", "request_raw_sha256", "request_raw_bytes",
        "report_full_canonical_sha256", "typed_expression_full_canonical_sha256",
        "typed_expression_content_digest", "signature_declarations_sha256",
        "argument_roles_sha256", "declared_structure_sha256",
    }
    for side, fragment, raw in [("reference", reference, compact), ("candidate", candidate, pretty)]:
        ref = result[side]
        assert set(ref) == reference_fields
        assert ref["schema"] == fragment["schema"] and ref["profile"] == fragment["profile"]
        assert ref["request_raw_sha256"] == sha(raw) and ref["request_raw_bytes"] == len(raw)
        assert ref["report_full_canonical_sha256"] == digest(fragment)
        assert ref["typed_expression_full_canonical_sha256"] == digest(fragment["typed_expression"])
        assert ref["typed_expression_content_digest"] == fragment["typed_expression_content_digest"]
        assert ref["signature_declarations_sha256"] == digest(result["signature_diagnostics"][side])
        assert ref["argument_roles_sha256"] == digest(sorted(fragment["argument_roles"], key=lambda row: row["symbol"]))
    assert result["reference"]["request_raw_sha256"] != result["candidate"]["request_raw_sha256"]
    assert result["reference"]["typed_expression_full_canonical_sha256"] == result["candidate"]["typed_expression_full_canonical_sha256"]
    assert validate(result, reference, candidate, left_raw, right_raw) == result


@pytest.mark.parametrize("mutation", ["argument_swap", "binding_capture", "quantifier_kind", "quantifier_order", "negation"])
def test_valid_bound_relational_changes_are_not_lexical_alpha_variants(mutation):
    original = relation_request(binders=[("actor", "forall"), ("recipient", "exists")])
    if mutation == "argument_swap":
        changed = relation_request(arguments=("recipient", "actor"),
                                   binders=[("actor", "forall"), ("recipient", "exists")])
    elif mutation == "binding_capture":
        changed = relation_request(arguments=("recipient", "recipient"),
                                   binders=[("actor", "forall"), ("recipient", "exists")])
    elif mutation == "quantifier_kind":
        changed = relation_request(binders=[("actor", "exists"), ("recipient", "exists")])
    elif mutation == "quantifier_order":
        changed = relation_request(binders=[("recipient", "exists"), ("actor", "forall")])
    else:
        changed = relation_request(binders=[("actor", "forall"), ("recipient", "exists")], negated=True)
    result, reference, candidate, _, _ = compare(original, changed)
    assert_unreviewed(result)
    assert result["comparisons"]["signature_declarations_equal"] is True
    assert result["comparisons"]["argument_roles_equal"] is True
    assert result["comparisons"]["declared_structure_equal"] is False
    assert result["comparisons"]["lexical_alpha_structure_equal"] is False
    assert any(row["declared_features_equal"] is False for row in result["feature_ledger"])
    assert_complete_mapping_union(result, reference, candidate)


@pytest.mark.parametrize("mutation", ["predicate", "arity", "role_values"])
def test_actual_signature_and_ordered_argument_roles_gate_alpha_comparison(mutation):
    original = relation_request()
    if mutation == "predicate":
        changed = relation_request(name="Authorizes")
    elif mutation == "arity":
        changed = relation_request(arguments=("actor", "recipient", "origin"),
                                   roles=("actor", "recipient", "origin"))
    else:
        changed = relation_request(roles=("recipient", "actor"))
    result, reference, candidate, _, _ = compare(original, changed)
    assert_unreviewed(result)
    assert result["comparisons"]["declared_structure_equal"] is False
    assert result["comparisons"]["lexical_alpha_structure_equal"] is False
    assert result["comparisons"]["signature_declarations_equal"] is (mutation == "role_values")
    assert result["comparisons"]["argument_roles_equal"] is False
    if mutation == "role_values":
        assert result["comparisons"]["exact_typed_expression_equal"] is True
        assert any("declared_argument_role" in row["declared_differences"] for row in result["feature_ledger"])
    assert_complete_mapping_union(result, reference, candidate)


@pytest.mark.parametrize("mutation", ["implication_direction", "modal_placement", "modal_O", "modal_F", "connective", "distributed_modal"])
def test_direction_modal_operators_and_operator_ownership_remain_distinct(mutation):
    if mutation == "implication_direction":
        original, changed = _FIXTURE.approval_request(), _FIXTURE.approval_request(sufficient=True)
    elif mutation == "modal_placement":
        original, changed = _FIXTURE.approval_request(sufficient=True), _FIXTURE.approval_request(inner=True)
    elif mutation in {"modal_O", "modal_F"}:
        original = _FIXTURE.approval_request()
        changed = _FIXTURE.approval_request(operator=mutation[-1])
    elif mutation == "connective":
        original, changed = _FIXTURE.action_request(), _FIXTURE.action_request("and")
    else:
        original, changed = _FIXTURE.action_request(), _FIXTURE.action_request(separated=True)
    result, reference, candidate, _, _ = compare(original, changed)
    assert_unreviewed(result)
    assert result["comparisons"]["signature_declarations_equal"] is True
    assert result["comparisons"]["argument_roles_equal"] is True
    assert result["comparisons"]["declared_structure_equal"] is False
    assert result["comparisons"]["lexical_alpha_structure_equal"] is False
    assert_complete_mapping_union(result, reference, candidate)


@pytest.mark.parametrize("connective", ["and", "or", "iff"])
def test_even_commutative_connectives_keep_declared_child_order(connective):
    def request(swapped):
        builder = _FIXTURE.Builder()
        names = ("Right", "Left") if swapped else ("Left", "Right")
        body = builder.binary(connective, *(builder.atom(name, "actor") for name in names))
        return _FIXTURE.request_for(builder, body,
            [("Left", ("subject",)), ("Right", ("subject",))], [("actor", "forall")])
    result, reference, candidate, _, _ = compare(request(False), request(True))
    assert_unreviewed(result)
    assert result["comparisons"]["signature_declarations_equal"] is True
    assert result["comparisons"]["argument_roles_equal"] is True
    assert result["comparisons"]["declared_structure_equal"] is False
    assert result["comparisons"]["lexical_alpha_structure_equal"] is False
    assert_complete_mapping_union(result, reference, candidate)


def test_double_negation_is_not_erased_as_a_lexical_alpha_rename():
    original = relation_request()
    builder = _FIXTURE.Builder()
    body = builder.atom("Relates", "actor", "recipient")
    body = ast.mk_not(builder.nid(), ast.mk_not(builder.nid(), body))
    changed = _FIXTURE.request_for(builder, body,
        [("Relates", ("actor", "recipient"))], [("actor", "forall"), ("recipient", "forall")])
    result, reference, candidate, _, _ = compare(original, changed)
    assert_unreviewed(result)
    assert result["comparisons"]["declared_structure_equal"] is False
    assert result["comparisons"]["lexical_alpha_structure_equal"] is False
    assert_complete_mapping_union(result, reference, candidate)


@pytest.mark.parametrize("reverse", [False, True])
def test_complete_mapping_union_keeps_every_path_for_added_or_dropped_structure(reverse):
    full, dropped = _FIXTURE.action_request(), _FIXTURE.action_request(dropped=True)
    result, reference, candidate, _, _ = compare(dropped if reverse else full, full if reverse else dropped)
    assert_unreviewed(result)
    assert_complete_mapping_union(result, reference, candidate)
    assert result["candidate_only_paths" if reverse else "reference_only_paths"]
    assert result["comparisons"]["declared_structure_equal"] is False
    assert result["comparisons"]["lexical_alpha_structure_equal"] is False


def test_binder_and_ordered_argument_roles_belong_to_their_exact_existing_paths():
    request = relation_request(binders=[("actor", "forall"), ("recipient", "exists")])
    result, reference, candidate, _, _ = compare(request, request)
    assert_unreviewed(result)
    by_path = {row["typed_path"]: row["reference"] for row in result["feature_ledger"]}
    predicate_path = "/root/arguments/0/arguments/0"
    assert by_path["/root"]["binder_paths"] == ["/root/binders/0"]
    assert by_path["/root"]["quantifier_kind"] == "forall"
    assert by_path["/root/binders/0"]["kind"] == "binder"
    assert by_path["/root/binders/0"]["binder_name"] == "actor"
    assert by_path["/root/binders/0"]["binding_quantifier_path"] == "/root"
    assert by_path["/root/arguments/0"]["quantifier_kind"] == "exists"
    assert by_path[predicate_path]["predicate_symbol"] == "Relates"
    assert by_path[predicate_path]["argument_roles"] == ["actor", "recipient"]
    assert by_path[predicate_path]["ordered_child_paths"] == [
        predicate_path + "/arguments/0", predicate_path + "/arguments/1",
    ]
    for index, (symbol, role, binding_path) in enumerate([
        ("actor", "actor", "/root"), ("recipient", "recipient", "/root/arguments/0"),
    ]):
        features = by_path[predicate_path + "/arguments/" + str(index)]
        assert features["symbol"] == symbol
        assert features["binding_quantifier_path"] == binding_path
        assert features["predicate_symbol"] == "Relates"
        assert features["predicate_typed_path"] == predicate_path
        assert features["predicate_argument_index"] == index
        assert features["declared_argument_role"] == role
    assert_complete_mapping_union(result, reference, candidate)


def test_modal_extension_and_connective_ancestry_keep_actual_operator_ownership(base_request):
    result, reference, candidate, _, _ = compare(base_request, base_request)
    by_path = {row["typed_path"]: row["reference"] for row in result["feature_ledger"]}
    implication_path = "/root/arguments/0/arguments/0/arguments/0"
    modal_path = implication_path + "/arguments/0"
    extension_path = modal_path + "/extension"
    action_path = extension_path + "/children/0"
    assign_path = action_path + "/arguments/0"
    approved_path = implication_path + "/arguments/1"
    assert by_path[modal_path]["kind"] == "extension"
    assert by_path[modal_path]["modal_operator"] == "P"
    extension = by_path[extension_path]
    assert extension["kind"] == "legacy.deontic/v1"
    assert extension["extension_payload_schema"] == "legacy.deontic/v1"
    assert extension["extension_payload"] == {
        "kind": "permission", "letter": "P", "resolution": "deontic",
        "schema_version": "legacy.deontic/v1",
    }
    assert set(extension["extension_features"]) == {"legacy.permission", "legacy.classic_letter"}
    assert extension["ordered_child_paths"] == [action_path]
    assert by_path[assign_path]["modal_ancestry"] == [{"typed_path": modal_path, "modal_operator": "P"}]
    assert by_path[assign_path]["connective_ancestry"] == [
        {"typed_path": implication_path, "connective_operator": "implies", "argument_index": 0},
        {"typed_path": action_path, "connective_operator": "or", "argument_index": 0},
    ]
    assert by_path[approved_path]["modal_ancestry"] == []
    assert by_path[approved_path]["connective_ancestry"] == [
        {"typed_path": implication_path, "connective_operator": "implies", "argument_index": 1},
    ]
    assert_complete_mapping_union(result, reference, candidate)


@pytest.mark.parametrize("pin", [
    "expected_reference_request_sha256", "expected_candidate_request_sha256",
    "expected_reference_report_sha256", "expected_candidate_report_sha256",
])
def test_each_independent_request_and_full_report_pin_is_required_before_lazy_owners(
        base_fragment, pin):
    fragment, raw = base_fragment
    args = arguments(fragment, fragment, raw, raw, **{pin: sha(b"another independent input")})
    with patch.object(owner, "_owners", side_effect=AssertionError("operation owner reached")) as operation:
        with pytest.raises(ValueError):
            owner.prepare_relational_reconstruction_comparison_v1(fragment, fragment, **args)
        operation.assert_not_called()


@pytest.mark.parametrize("side", ["reference", "candidate"])
@pytest.mark.parametrize("field", [
    "native_ast", "lean_body", "structural_mapping", "argument_roles",
    "authority", "typed_expression", "counts", "training_mask",
])
def test_self_rehashed_full_input_reports_still_require_original_authoritative_replay(
        base_fragment, side, field):
    fragment, raw = base_fragment
    offered = deepcopy(fragment)
    if field == "native_ast":
        offered[field]["variable"]["name"] = "substituted_actor"
    elif field == "lean_body":
        offered[field] += "\n-- substituted generated text"
    elif field == "structural_mapping":
        offered[field].pop()
    elif field == "argument_roles":
        offered[field][0]["roles"].reverse()
    elif field == "authority":
        offered[field]["accepted"] = True
    elif field == "typed_expression":
        offered[field]["expression_id"] = "invented:expression"
    elif field == "counts":
        offered[field]["nodes"] -= 1
    else:
        offered[field] = 1
    reference, candidate = (offered, fragment) if side == "reference" else (fragment, offered)
    with pytest.raises(ValueError):
        owner.prepare_relational_reconstruction_comparison_v1(
            reference, candidate, **arguments(reference, candidate, raw, raw),
        )


def test_unproved_offered_producer_filename_is_never_opened(tmp_path, base_fragment):
    fragment, raw = base_fragment
    forged_path = str((tmp_path / "unproved-producer-source.py").resolve())
    offered = deepcopy(fragment)
    offered["producer_pins"][forged_path] = sha(b"unproved producer")
    opened = []
    original_builtin_open, original_io_open, original_os_open = builtins.open, io.open, os.open
    def reject_offered(original, file, *args, **kwargs):
        if isinstance(file, (str, os.PathLike)) and os.fspath(file) == forged_path:
            opened.append(forged_path)
            raise AssertionError("unproved producer filename opened")
        return original(file, *args, **kwargs)
    with patch.object(builtins, "open", lambda file, *args, **kwargs:
                      reject_offered(original_builtin_open, file, *args, **kwargs)), patch.object(
                          io, "open", lambda file, *args, **kwargs:
                          reject_offered(original_io_open, file, *args, **kwargs)), patch.object(
                              os, "open", lambda file, *args, **kwargs:
                              reject_offered(original_os_open, file, *args, **kwargs)):
        with pytest.raises(ValueError):
            owner.prepare_relational_reconstruction_comparison_v1(
                fragment, offered, **arguments(fragment, offered, raw, raw),
            )
    assert opened == []


@pytest.mark.parametrize("mutation", [
    "source_binding", "free_variable", "shadowing", "family", "profile",
    "unknown_request_field", "duplicate_json_key", "invalid_utf8",
])
def test_invalid_or_unsupported_inputs_refuse_instead_of_entering_comparison_denominator(
        base_request, base_fragment, mutation):
    reference, reference_raw = base_fragment
    changed = deepcopy(base_request)
    if mutation == "source_binding":
        changed["source_binding"] = {"caller_says_grounded": True}
    elif mutation == "free_variable":
        # Exact existing geometry: three quantifiers, implication, modal,
        # action connective, first predicate, first ordered argument.
        implication = changed["expression"]["root"]["arguments"][0]["arguments"][0]["arguments"][0]
        implication["arguments"][0]["extension"]["children"][0]["arguments"][0]["arguments"][0]["symbol"] = "unbound_person"
        changed = _FIXTURE.reseal_expression(changed)
    elif mutation == "shadowing":
        changed["expression"]["root"]["arguments"][0]["binders"][0]["name"] = "actor"
        changed = _FIXTURE.reseal_expression(changed)
    elif mutation in {"family", "profile"}:
        changed["expression"][mutation]["value"] = "fol" if mutation == "family" else "fol_default"
    elif mutation == "unknown_request_field":
        changed["extra"] = "unknown"
    candidate_raw = wire(changed)
    if mutation == "duplicate_json_key":
        candidate_raw = b'{"schema":"duplicate",' + candidate_raw[1:]
    elif mutation == "invalid_utf8":
        candidate_raw = b"\xff"
    offered = deepcopy(reference)
    with pytest.raises(ValueError):
        owner.prepare_relational_reconstruction_comparison_v1(
            reference, offered, **arguments(reference, offered, reference_raw, candidate_raw),
        )


@pytest.mark.parametrize("damage", [
    "raw_type", "raw_bound", "report_bound", "dict_subclass", "nonfinite",
    "deep", "ordinary_object", "boolean_pin",
])
def test_finite_detached_preflight_refuses_before_operation_imports(base_fragment, damage):
    fragment, raw = base_fragment
    offered = deepcopy(fragment)
    args = arguments(fragment, offered, raw, raw)
    if damage == "raw_type":
        args["candidate_request_raw"] = bytearray(raw)
    elif damage == "raw_bound":
        args["candidate_request_raw"] = b" " * (524288 + 1)
        args["expected_candidate_request_sha256"] = sha(args["candidate_request_raw"])
    elif damage == "report_bound":
        offered["extra"] = "x" * (8 * 1024 * 1024 + 1)
        args["expected_candidate_report_sha256"] = digest(offered)
    elif damage == "dict_subclass":
        class CustomDict(dict):
            pass
        offered = CustomDict(offered)
    elif damage == "nonfinite":
        offered["extra"] = float("nan")
    elif damage == "deep":
        child = "leaf"
        for _ in range(97):
            child = [child]
        offered["extra"] = child
        args["expected_candidate_report_sha256"] = digest(offered)
    elif damage == "ordinary_object":
        offered["extra"] = object()
    else:
        args["expected_reference_report_sha256"] = True
    with patch.object(owner, "_owners", side_effect=AssertionError("operation owner reached")) as operation:
        with pytest.raises(ValueError):
            owner.prepare_relational_reconstruction_comparison_v1(fragment, offered, **args)
        operation.assert_not_called()


@pytest.mark.parametrize("damage", [
    "structure_boolean", "alpha_boolean", "feature_row", "missing_path", "path_order",
    "reference_hash", "source_pin", "authority", "training_boolean", "gold_float",
    "unknown_field", "missing_field",
])
def test_rehashed_comparison_cannot_replace_complete_original_bound_regeneration(
        base_request, damage):
    result, reference, candidate, left_raw, right_raw = compare(base_request, base_request)
    offered = deepcopy(result)
    if damage in {"structure_boolean", "alpha_boolean"}:
        key = "declared_structure_equal" if damage == "structure_boolean" else "lexical_alpha_structure_equal"
        offered["comparisons"][key] = False
    elif damage == "feature_row":
        offered["feature_ledger"][-1]["reference"]["symbol"] = "invented"
    elif damage == "missing_path":
        offered["feature_ledger"].pop()
    elif damage == "path_order":
        offered["feature_ledger"].reverse()
    elif damage == "reference_hash":
        offered["reference"] = deepcopy(offered["candidate"])
        offered["reference"]["invented_hash"] = sha(b"different reference")
    elif damage == "source_pin":
        path = next(iter(offered["producer_pins"]))
        offered["producer_pins"][path] = sha(b"substituted producer source")
    elif damage == "authority":
        offered["authority"]["source_semantics_verified"] = True
    elif damage == "training_boolean":
        offered["training_mask"] = False
    elif damage == "gold_float":
        offered["evaluation_gold_mask"] = 0.0
    elif damage == "unknown_field":
        offered["unknown"] = "new authority namespace"
    else:
        offered.pop("feature_ledger")
    with pytest.raises(ValueError):
        validate(offered, reference, candidate, left_raw, right_raw)


def test_wrong_independent_comparison_pin_refuses_before_regeneration(base_request):
    result, reference, candidate, left_raw, right_raw = compare(base_request, base_request)
    with patch.object(owner, "prepare_relational_reconstruction_comparison_v1",
                      side_effect=AssertionError("regeneration reached")) as regenerate:
        with pytest.raises(ValueError):
            owner.validate_relational_reconstruction_comparison_v1(
                result, reference, candidate,
                expected_comparison_sha256=sha(b"different comparison"),
                **arguments(reference, candidate, left_raw, right_raw),
            )
        regenerate.assert_not_called()


def test_complete_output_ceiling_refuses_without_clipping_or_mutating_originals(base_request):
    result, reference, candidate, left_raw, right_raw = compare(base_request, base_request)
    before = deepcopy((reference, candidate))
    with patch.object(owner, "MAX_OUTPUT_BYTES", len(wire(result)) - 1):
        with pytest.raises(ValueError):
            owner.prepare_relational_reconstruction_comparison_v1(
                reference, candidate, **arguments(reference, candidate, left_raw, right_raw),
            )
    assert before == (reference, candidate)
    assert validate(result, reference, candidate, left_raw, right_raw) == result


def test_changed_self_source_pin_refuses_without_editing_a_source_file(base_fragment):
    fragment, raw = base_fragment
    with patch.object(owner, "_SELF_PIN", sha(b"substituted source identity")):
        with pytest.raises(ValueError):
            owner.prepare_relational_reconstruction_comparison_v1(
                fragment, fragment, **arguments(fragment, fragment, raw, raw),
            )


def test_public_import_uses_only_standard_library_and_writes_nothing(monkeypatch):
    name = "_relational_reconstruction_cold_public_source"
    spec = importlib.util.spec_from_file_location(name, Path(owner.__file__))
    assert spec is not None and spec.loader is not None
    cold = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, cold)
    attempts = []
    forbidden = ("ipfs_datasets_py", "numpy", "pyarrow", "multiformats", "torch", "transformers", "symai", "tensorflow")
    original_import, original_open, original_os_open = builtins.__import__, builtins.open, os.open
    def checked_import(import_name, *args, **kwargs):
        if any(import_name == root or import_name.startswith(root + ".") for root in forbidden):
            attempts.append(import_name)
            raise AssertionError("operation owner imported during public import")
        return original_import(import_name, *args, **kwargs)
    def checked_open(file, mode="r", *args, **kwargs):
        if type(mode) is str and any(flag in mode for flag in "wax+"):
            attempts.append("file write")
            raise AssertionError("public import wrote a file")
        return original_open(file, mode, *args, **kwargs)
    def checked_os_open(file, flags, *args, **kwargs):
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            attempts.append("descriptor write")
            raise AssertionError("public import wrote through os.open")
        return original_os_open(file, flags, *args, **kwargs)
    with patch.object(builtins, "__import__", checked_import), patch.object(builtins, "open", checked_open), patch.object(io, "open", checked_open), patch.object(os, "open", checked_os_open):
        spec.loader.exec_module(cold)
    assert attempts == []
    assert cold.SCHEMA == owner.SCHEMA and cold.PROFILE == owner.PROFILE
    assert all(hasattr(cold, name) for name in (
        "prepare_relational_reconstruction_comparison_v1", "validate_relational_reconstruction_comparison_v1",
        "relational_reconstruction_comparison_sha256",
    ))


# New opt-in source-withheld prose checks remain separate from the original
# source-pinned report comparison. No fixture supplies reviewed legal meaning.
from ipfs_datasets_py.logic.legal_ir.extended_decompiler import RELATIONAL_PROSE_PROFILE


def _prose_expression_request(*, reverse_roles=False, reverse_arguments=False,
                               reverse_scope=False, letter="O", exception_scope="outside"):
    builder = _FIXTURE.Builder()
    arguments = ("recipient", "actor") if reverse_arguments else ("actor", "recipient")
    action = builder.atom("Notify", *arguments)
    unless = ast.mk_not(builder.nid(), builder.atom("Exempt", "actor"))
    if exception_scope == "outside":
        body = builder.binary("implies", unless, builder.modal(letter, action))
    elif exception_scope == "inside":
        body = builder.modal(letter, builder.binary("implies", unless, action))
    elif exception_scope == "absent":
        # Use Exempt as an ordinary condition so declarations stay complete;
        # the difference is negation, rather than silent signature omission.
        body = builder.binary("implies", builder.atom("Exempt", "actor"),
                              builder.modal(letter, action))
    else:
        raise AssertionError("unsupported authored fixture variation")
    binders = [("actor", "forall"), ("recipient", "exists")]
    if reverse_scope:
        binders.reverse()
    labels = ("recipient", "actor") if reverse_roles else ("actor", "recipient")
    request = _FIXTURE.request_for(builder, body,
        [("Exempt", ("actor",)), ("Notify", labels)], binders)
    return ast.TypedExpression.from_dict(request["expression"]), request["argument_roles"]


def _compare_prose_inputs(reference, candidate, roles, candidate_roles):
    return owner.compare_relational_prose_structure_v1(reference, candidate,
        reference_argument_roles=roles, candidate_argument_roles=candidate_roles,
        profile=RELATIONAL_PROSE_PROFILE)


def test_prose_reconstruction_reports_complete_typed_structure_and_prose_separately():
    expression, roles = _prose_expression_request()
    before = deepcopy(expression.to_dict()), deepcopy(roles)
    result = owner.prepare_relational_prose_reconstruction_v1(expression,
        argument_roles=roles, profile=RELATIONAL_PROSE_PROFILE)
    assert result["schema"] == "legal-relational-prose-reconstruction/v1"
    assert result["normalized_prose"].startswith("Typed legal rule: tdfol/tdfol_default.\n")
    assert "it is not the case that (Exempt holds for actor: actor of type Object)" in result["normalized_prose"]
    assert "recipient: recipient of type Object" in result["normalized_prose"]
    assert result["measurements"]["typed_structure_equal"] is True
    assert result["measurements"]["canonical_prose_fixed_point"] is True
    assert result["measurements"]["exact_typed_expression_equal"] is False
    assert result["measurements"]["semantic_equivalence_verified"] is False
    assert result["measurements"]["source_semantics_verified"] is False
    reconstructed = ast.TypedExpression.from_dict(result["reconstructed_typed_expression"])
    comparison = _compare_prose_inputs(expression, reconstructed, roles,
                                      result["reconstructed_argument_roles"])
    assert comparison["typed_structure_equal"] is True
    assert comparison["canonical_prose_equal"] is True
    assert comparison["argument_roles_equal"] is True
    assert before == (expression.to_dict(), roles)


@pytest.mark.parametrize("variation", [
    {"reverse_roles": True}, {"reverse_arguments": True}, {"reverse_scope": True},
    {"letter": "P"}, {"letter": "F"}, {"exception_scope": "inside"},
    {"exception_scope": "absent"},
])
def test_prose_structure_comparison_detects_independently_authored_legal_facet_mutations(variation):
    reference, roles = _prose_expression_request()
    candidate, candidate_roles = _prose_expression_request(**variation)
    result = _compare_prose_inputs(reference, candidate, roles, candidate_roles)
    assert result["exact_typed_expression_equal"] is variation.get("reverse_roles", False)
    assert result["typed_structure_equal"] is False
    assert result["canonical_prose_equal"] is False
    assert result["argument_roles_equal"] is (not variation.get("reverse_roles", False))
    # Structural diagnostics establish no reviewed source or general legal
    # semantic-equivalence result, even when the two syntax trees differ.
    for key in ("semantic_equivalence_verified", "source_semantics_verified"):
        if key in result:
            assert result[key] is False


def test_prose_structure_ignores_only_named_transport_identifiers_and_declaration_order():
    reference, roles = _prose_expression_request()
    value = reference.to_dict()
    def rename(value):
        if type(value) is dict:
            for key, child in value.items():
                if key in {"node_id", "expression_id", "signature_id"}:
                    value[key] = "new-transport:" + child
                else:
                    rename(child)
        elif type(value) is list:
            for child in value:
                rename(child)
    rename(value)
    value.pop("content_digest")
    value["signature"]["symbols"].reverse()
    candidate = ast.TypedExpression.from_dict(value)
    result = _compare_prose_inputs(reference, candidate, roles, list(reversed(roles)))
    assert result["exact_typed_expression_equal"] is False
    assert result["typed_structure_equal"] is True
    assert result["canonical_prose_equal"] is True
    assert result["argument_roles_equal"] is True


def test_prose_structure_does_not_call_bound_variable_renaming_exact_typed_structure():
    reference, roles = _prose_expression_request()
    value = reference.to_dict()
    def rename(value):
        if type(value) is dict:
            if value.get("kind") == "variable" and value.get("symbol") == "actor":
                value["symbol"] = "officer"
            if value.get("name") == "actor" and "sort" in value:
                value["name"] = "officer"
            for child in value.values():
                rename(child)
        elif type(value) is list:
            for child in value:
                rename(child)
    rename(value["root"])
    value.pop("content_digest")
    candidate = ast.TypedExpression.from_dict(value)
    result = _compare_prose_inputs(reference, candidate, roles, roles)
    assert result["typed_structure_equal"] is False
    assert result["canonical_prose_equal"] is False
    assert result["argument_roles_equal"] is True


def test_prose_reconstruction_has_no_hidden_original_text_or_target_channel():
    expression, roles = _prose_expression_request()
    with pytest.raises(TypeError):
        owner.prepare_relational_prose_reconstruction_v1(expression,
            argument_roles=roles, profile=RELATIONAL_PROSE_PROFILE,
            original_text="Hidden original bytes, not formal semantics.")
    with pytest.raises(TypeError):
        owner.prepare_relational_prose_reconstruction_v1(expression,
            argument_roles=roles, profile=RELATIONAL_PROSE_PROFILE,
            reference_target=expression.to_dict())
    result = owner.prepare_relational_prose_reconstruction_v1(expression,
        argument_roles=roles, profile=RELATIONAL_PROSE_PROFILE)
    def keys(value):
        if type(value) is dict:
            for key, child in value.items():
                yield key
                yield from keys(child)
        elif type(value) is list:
            for child in value:
                yield from keys(child)
    assert {"original_text", "source_text", "reference_target", "hidden_ast"}.isdisjoint(set(keys(result)))
    assert "fixture:node:" not in result["normalized_prose"]
    assert "content_digest" not in result["normalized_prose"]


def test_prose_reconstruction_rejects_unsupported_source_metadata_as_whole_input():
    expression, roles = _prose_expression_request()
    source_bearing = ast.TypedExpression("fictional:source-bearing", expression.root,
        expression.signature, metadata={"source_text": "not a renderer channel"})
    with pytest.raises(ValueError):
        owner.prepare_relational_prose_reconstruction_v1(source_bearing,
            argument_roles=roles, profile=RELATIONAL_PROSE_PROFILE)
    with pytest.raises(ValueError):
        _compare_prose_inputs(expression, source_bearing, roles, roles)


def test_prose_reconstruction_public_opt_in_apis_are_additive_exports():
    assert owner.__all__[:4] == ["RelationalReconstructionError",
        "prepare_relational_reconstruction_comparison_v1",
        "relational_reconstruction_comparison_sha256", "validate_relational_reconstruction_comparison_v1"]
    assert owner.__all__[4:] == ["compare_relational_prose_structure_v1",
        "prepare_relational_prose_reconstruction_v1", "compare_relational_governing_fields_v1"]
    assert all(callable(getattr(owner, name)) for name in owner.__all__[4:])


@pytest.fixture
def fictional_governing_fields():
    return {
        "governing_context": {
            "jurisdiction": "fictional-jurisdiction", "instrument_id": "fixture:notification-act",
            "governing_edition": "fixture:edition-one", "legal_as_of_utc": "2030-06-15T00:00:00Z",
            "valid_from_utc": "2030-01-01T00:00:00Z", "valid_until_utc": None,
        },
        "definition_uses": [{
            "definition_unit_id": "fixture:definition-A", "defined_predicate": "Notify",
            "use_unit_id": "fixture:norm-A", "use_occurrence_cid": "fixture:occurrence-A",
            "target_typed_paths": ["/root/arguments/0/arguments/0/arguments/1/extension/children/0"],
            "applicability": "governing", "interpretation_id": "fixture:interpretation-A",
            "evidence_refs": [{"artifact_id": "fixture:definition-evidence-A", "sha256": "a" * 64}],
        }],
    }


@pytest.mark.parametrize("changed", ["valid_from_utc", "legal_as_of_utc", "definition_unit_id"])
def test_governing_fidelity_distinguishes_same_ast_with_different_legal_context(fictional_governing_fields, changed):
    expression, roles = _prose_expression_request()
    structure = _compare_prose_inputs(expression, expression, roles, roles)
    assert structure["exact_typed_expression_equal"] and structure["typed_structure_equal"]
    assert structure["canonical_prose_equal"]

    reference = fictional_governing_fields
    candidate = deepcopy(reference)
    date_changed = changed != "definition_unit_id"
    if date_changed:
        candidate["governing_context"][changed] = "2030-04-01T00:00:00Z"
    else:
        candidate["definition_uses"][0][changed] = "fixture:definition-B"
    comparison = owner.compare_relational_governing_fields_v1(reference, candidate)
    assert comparison["measurements"] == {
        "governing_context_exact": not date_changed, "definition_uses_exact": date_changed,
    }
    assert comparison["reference"] == reference and comparison["candidate"] == candidate
    assert comparison["authority"] == {"applicability_verified": False, "governing_use_verified": False}


@pytest.mark.parametrize("candidate, expected", [
    ({}, None), ({"definition_uses": None}, False), ({"definition_uses": []}, False),
])
def test_governing_fidelity_distinguishes_omitted_null_and_empty_uses(candidate, expected):
    result = owner.compare_relational_governing_fields_v1({}, candidate)
    assert result["measurements"] == {"governing_context_exact": None, "definition_uses_exact": expected}
    assert result["reference"] == {} and result["candidate"] == candidate


def test_governing_fidelity_preserves_ordered_competing_and_unresolved_uses(fictional_governing_fields):
    reference = fictional_governing_fields
    candidate = deepcopy(reference)
    competing = deepcopy(candidate["definition_uses"][0])
    competing["definition_unit_id"] = "fixture:definition-B"
    unresolved = {"definition_unit_id": None, "applicability": "unresolved", "target_typed_paths": None}
    candidate["definition_uses"].extend([competing, unresolved])
    comparison = owner.compare_relational_governing_fields_v1(reference, candidate)
    assert comparison["measurements"]["definition_uses_exact"] is False
    assert comparison["candidate"]["definition_uses"] == candidate["definition_uses"]
    assert not any(comparison["authority"].values())

    reversed_candidate = {**candidate, "definition_uses": list(reversed(candidate["definition_uses"]))}
    ordered = owner.compare_relational_governing_fields_v1(candidate, reversed_candidate)
    assert ordered["measurements"]["definition_uses_exact"] is False
    identical = owner.compare_relational_governing_fields_v1(candidate, candidate)
    assert identical["measurements"]["definition_uses_exact"] is True
    assert not any(identical["authority"].values())
    unresolved["applicability"] = "changed_after_comparison"
    assert identical["candidate"]["definition_uses"][2]["applicability"] == "unresolved"


def test_governing_fidelity_retains_unresolved_context_without_filling_missing_values():
    reference = {"governing_context": {"governing_edition": None}}
    result = owner.compare_relational_governing_fields_v1(reference, {"governing_context": {}})
    assert result["measurements"]["governing_context_exact"] is False
    assert result["reference"] == reference
    assert result["candidate"] == {"governing_context": {}}


@pytest.mark.parametrize("damage", [
    {"source_binding": {}}, {"governing_context": {"source_text": "hidden"}},
    {"governing_context": {"valid_from_utc": 2030}}, {"definition_uses": {}},
    {"definition_uses": [{"target_typed_paths": [True]}]},
    {"definition_uses": [{"evidence_refs": [{"raw_source": "hidden"}]}]},
    {"definition_uses": [{"applicability": ["governing"]}]},
])
def test_governing_fidelity_refuses_other_channels_and_invalid_field_types(damage):
    with pytest.raises(owner.RelationalReconstructionError):
        owner.compare_relational_governing_fields_v1({}, damage)
