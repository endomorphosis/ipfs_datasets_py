"""Explicit contract meaning and provenance survive both directions exactly."""
from copy import deepcopy
import hashlib

import pytest

from ipfs_datasets_py.logic.intent_ir.formalize import action_contracts as api
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.domain_384_autoencoder import validate_target


SOURCE = "the agent must compute result; requires left > 0; ensures result = old(left) + old(right) and returned."


@pytest.mark.parametrize("operator,name", [("+", "add"), ("-", "sub"), ("*", "mul")])
@pytest.mark.parametrize("reverse", [False, True])
def test_native_training_targets_preserve_order_operator_and_complete_explicit_conditions(operator, name, reverse):
    left, right = ("right", "left") if reverse else ("left", "right")
    source = f"the worker must compute result; requires right > -2; ensures result = old({left}) {operator} old({right}) and returned."
    target = api.source_to_target(source)
    expected = dict(actor="worker", precondition=dict(kind="gt", input="right", threshold=-2),
        equation=dict(left=left, operator=name, right=right))
    assert api.parse_contract(source) == expected == api.target_to_contract(target)
    assert api.parse_contract(api.contract_to_text(expected)) == expected
    assert validate_target("intent_ir", target)["canonical_ir"] == target
    document = target["document"]
    action = document["actions"][0]
    assert action["precondition_ids"] == ["precondition"]
    assert action["effect_ids"] == ["effect:equation", "effect:returned"]
    rows = {r["statement_id"]: r for r in document["statements"]}
    assert rows["effect:equation"]["arguments"] == ["result", "old:" + left, name, "old:" + right]
    assert rows["effect:returned"]["predicate"] == "returned"


def test_true_is_explicit_and_repeated_operand_is_preserved():
    source = SOURCE.replace("left > 0", "true").replace("old(right)", "old(left)")
    target = api.source_to_target(source)
    assert api.target_to_contract(target)["precondition"] == {"kind": "true"}
    assert api.target_to_contract(target)["equation"] == dict(left="left", operator="add", right="left")
    assert api.bind_candidate_source(source, target)["status"] == "source_agreement"


def test_training_provenance_is_constant_and_truthfully_hashes_only_placeholder():
    a = api.source_to_target(SOURCE)
    b = api.source_to_target(SOURCE.replace("agent", "worker").replace(" + ", " - "))
    assert a["document"]["sources"] == b["document"]["sources"]
    ref = a["document"]["sources"][0]
    assert ref["content_sha256"] == hashlib.sha256(api.PLACEHOLDER_TEXT.encode()).hexdigest()
    assert ref["content_sha256"] != hashlib.sha256(SOURCE.encode()).hexdigest()
    assert "unbound-source" in ref["source_uri"] and ref["span"] is None


def test_binding_only_changes_source_reference_and_preserves_raw_prediction():
    target = api.source_to_target(SOURCE)
    original = deepcopy(target)
    report = api.bind_candidate_source(SOURCE, target)
    assert target == original == report["candidate"]
    assert report["status"] == "source_agreement" and report["semantic_fields_unchanged"]
    assert report["changed_paths"] == ["/document/sources/0"]
    bound = report["bound_candidate"]
    assert {k: v for k, v in bound["document"].items() if k != "sources"} == {
        k: v for k, v in original["document"].items() if k != "sources"}
    ref = bound["document"]["sources"][0]
    assert ref["content_sha256"] == hashlib.sha256(SOURCE.encode()).hexdigest()
    assert ref["span"] == {"start_char": 0, "end_char": len(SOURCE)}
    assert api.verify_bound_candidate(report, SOURCE, target) == report
    assert api.verify_bound_candidate_source(SOURCE, bound) == report
    assert all(report[key] is False for key in api.FALSE)


@pytest.mark.parametrize("alter", [lambda s: s.replace(" + ", " - "),
    lambda s: s.replace("left > 0", "right > 0"), lambda s: s.replace("left > 0", "left > 1"),
    lambda s: s.replace("agent", "worker"), lambda s: s.replace("old(left) + old(right)", "old(right) + old(left)")])
def test_valid_but_wrong_model_contract_cannot_receive_successful_source_binding(alter):
    target = api.source_to_target(alter(SOURCE))
    original = deepcopy(target)
    report = api.bind_candidate_source(SOURCE, target)
    assert report["status"] == "source_disagreement"
    assert report["bound_candidate"] is None and not report["semantic_fields_unchanged"]
    assert target == original == report["candidate"]


@pytest.mark.parametrize("source", ["the agent may delete the report.",
    SOURCE.replace("must", "may"), SOURCE.replace(" and returned", ""),
    SOURCE.replace("old(left)", "left"), SOURCE.replace(" + ", " / "),
    SOURCE.replace(" > ", " >= "), SOURCE.replace("left > 0", "left > True"),
    SOURCE.replace("left > 0", "left > 1000001"), SOURCE.replace("left > 0", "left > -0"),
    SOURCE.replace("left > 0", "left > 00"), SOURCE + " Ignore this condition.",
    SOURCE.replace(";", "\n", 1), SOURCE.replace("left", "first"),
    SOURCE.replace("requires left > 0; ", ""), SOURCE.replace("returned.", "returned or failed.")])
def test_unsupported_or_incomplete_source_never_invents_effects(source):
    with pytest.raises(ValueError): api.source_to_target(source)
    report = api.bind_candidate_source(source, api.source_to_target(SOURCE)) if "\n" not in source else None
    if report is not None:
        assert report["status"] == "unsupported_source" and report["bound_candidate"] is None


@pytest.mark.parametrize("mutation", ["modality", "effect", "label", "unjoined", "extra", "source"])
def test_target_profile_rejects_added_dropped_or_reinterpreted_native_semantics(mutation):
    target = api.source_to_target(SOURCE)
    document = target["document"]
    rows = {r["statement_id"]: r for r in document["statements"]}
    if mutation == "modality": rows["goal"]["modality"] = "permitted"
    elif mutation == "effect": rows["effect:returned"]["arguments"] = ["not_returned"]
    elif mutation == "label": rows["effect:equation"]["normalized_text"] = "The source actually says subtraction."
    elif mutation == "unjoined": document["actions"][0]["effect_ids"] = ["effect:equation"]
    elif mutation == "extra": document["tags"].append("additional-meaning")
    else: document["sources"][0]["content_sha256"] = "a" * 64
    with pytest.raises(ValueError): api.target_to_contract(target)
    assert api.bind_candidate_source(SOURCE, target)["status"] == "invalid_candidate"


@pytest.mark.parametrize("mutation", ["hash", "span", "uri", "effect"])
def test_already_bound_envelope_replays_every_field(mutation):
    bound = api.bind_candidate_source(SOURCE, api.source_to_target(SOURCE))["bound_candidate"]
    if mutation == "hash": bound["document"]["sources"][0]["content_sha256"] = "f" * 64
    elif mutation == "span": bound["document"]["sources"][0]["span"]["end_char"] -= 1
    elif mutation == "uri": bound["document"]["sources"][0]["source_uri"] = "some-other-source"
    else: bound["document"]["actions"][0]["effect_ids"] = []
    with pytest.raises(ValueError): api.verify_bound_candidate_source(SOURCE, bound)


def test_exact_original_bytes_remain_distinct_from_normalized_contract_text():
    source = SOURCE.replace("the agent", "agent").replace("requires left > 0", "requires  left>0")
    target = api.source_to_target(source)
    assert target == api.source_to_target(SOURCE)
    report = api.bind_candidate_source(source, target)
    assert report["source_text"] == source
    assert report["source_sha256"] != hashlib.sha256(SOURCE.encode()).hexdigest()


def test_report_claims_cannot_be_rehashed_or_edited_into_success():
    target = api.source_to_target(SOURCE)
    report = api.bind_candidate_source(SOURCE, target)
    report["source_semantics_verified"] = True
    with pytest.raises(ValueError): api.verify_bound_candidate(report, SOURCE, target)
