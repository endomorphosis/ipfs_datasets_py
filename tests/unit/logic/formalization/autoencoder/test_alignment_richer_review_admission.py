"""Isolated synthetic submissions exercise admission, never claim human review."""
from __future__ import annotations

import builtins
import hashlib
import json
from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import (
    alignment_richer_panel as panel_owner,
)
from ipfs_datasets_py.logic.formalization.autoencoder import (
    alignment_richer_review as preparation,
)
from ipfs_datasets_py.logic.formalization.autoencoder import (
    alignment_richer_review_admission as subject,
)

SIGNATURE_FIELDS = ("interpretation_status", "ambiguity", "unsupported_meaning", "normative_rules", "freeform_qualifier_scope")
AUTHORITY_FIELDS = ("qualified", "production_admitted", "independent_fidelity_available", "source_semantics_verified", "proof_authority")


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                     allow_nan=False).encode("utf-8")).hexdigest()


@pytest.fixture(scope="module")
def bundle():
    # Only the openly authored panel is constructed. No sealed corpus is read.
    return preparation.prepare_richer_review(panel_owner.build_alignment_richer_panel(),
        {"panel": {"path": "authored-development/panel.json", "sha256": "a" * 64, "bytes": 123},
         "evaluation_role": "exposed_development"})


def _rule(**changes):
    # This is a test annotation, not a claimed interpretation of a real item.
    result = {"modality": "O", "actor": "fixture_actor", "action": "fixture_action", "object": "fixture_object",
              "conditions": ["fixture_condition"], "exceptions": ["fixture_exception"], "temporal": ["fixture_time"]}
    result.update(changes)
    return result


def _annotation(reviewer="fixture-reviewer-A", *, status="normative"):
    result = {"interpretation_status": status, "ambiguity": status == "ambiguous", "unsupported_meaning": status == "unsupported",
              "normative_rules": [_rule()] if status == "normative" else [],
              "freeform_qualifier_scope": "Fixture: all conditions, any exception, and opaque time constraints apply to this rule.",
              "notes": None if status == "normative" else "Fixture rationale: explicit reviewed disposition, not a missing answer.",
              "reviewer_id": reviewer, "reviewed_at_utc": "2026-10-03T14:23:01Z"}
    return result


def _payload(bundle, reviewer="fixture-reviewer-A", *, complete=True, status="normative", item_ids=None):
    result = deepcopy(bundle["reviewer_payload"])
    if item_ids is not None:
        result["items"] = [item for item in result["items"] if item["item_id"] in item_ids]
    if complete:
        # Default: one invented fixture submission, remaining 33 items unanswered.
        result["items"][0]["annotation"] = _annotation(reviewer, status=status)
    return result


def _one_payload(bundle, reviewer="fixture-reviewer-A", *, status="normative"):
    identity = bundle["reviewer_payload"]["items"][0]["item_id"]
    return _payload(bundle, reviewer, status=status, item_ids={identity})


def _admit(bundle, *payloads):
    return subject.admit_richer_reviews(bundle, list(payloads))


def _item(receipt, identity):
    return next(item for item in receipt["items"] if item["item_id"] == identity)


def _assert_no_authority(receipt):
    assert all(receipt[field] is False for field in AUTHORITY_FIELDS)
    assert receipt["primary_independently_adjudicated_fidelity"] == {"status": "unavailable", "value": None}
    for name in ("reviewer_identity_evidence", "source_author_independence_evidence", "reviewer_attestation_evidence"):
        assert receipt[name] == {"status": "unavailable", "authenticated": False}
    assert receipt["automatic_adjudication"] is False
    for item in receipt["items"]:
        assert all(item[field] is False for field in AUTHORITY_FIELDS)
        assert item["external_adjudication_status"] == "pending"


def test_all_34_blank_inputs_remain_pending_without_invented_labels(bundle):
    blank = _payload(bundle, complete=False)
    before = deepcopy((bundle, blank))
    result = _admit(bundle, blank)
    assert len(result["items"]) == 34
    assert result["status_counts"]["pending"] == 34
    assert sum(result["status_counts"].values()) == 34
    assert all(item["complete_distinct_reviewer_count"] == 0 for item in result["items"])
    for item in result["items"]:
        submission = item["received_submissions"][0]
        assert submission["complete"] is False
        assert submission["semantic_signature_sha256"] is None
        assert all(value is None for value in submission["annotation"].values())
    assert (bundle, blank) == before
    _assert_no_authority(result)
    validated = subject.validate_richer_review_admission(result, bundle, [blank])
    assert validated["qualified"] is False


def test_no_submissions_subset_and_reordering_keep_all_item_accounting(bundle):
    empty = _admit(bundle)
    assert empty["status_counts"]["pending"] == 34
    assert all(item["received_submissions"] == [] for item in empty["items"])
    subset = _one_payload(bundle)
    result = _admit(bundle, subset)
    assert result["status_counts"]["single_review"] == 1
    assert result["status_counts"]["pending"] == 33
    reordered = _payload(bundle)
    reordered["items"].reverse()
    assert _admit(bundle, reordered)["status_counts"] == result["status_counts"]


def test_receipt_preserves_exact_available_source_and_context_without_reference_comparison(bundle):
    result = _admit(bundle, _payload(bundle))
    original = {item["item_id"]: item for item in bundle["reviewer_payload"]["items"]}
    for item in result["items"]:
        for field in ("source_text", "source_sha256", "context", "input_sha256"):
            assert json.dumps(item[field], sort_keys=True) == json.dumps(original[item["item_id"]][field], sort_keys=True)
        assert "authored_reference_diagnostic" not in item
        assert "authored_reference" not in item
        assert "target" not in item
    # The candidate-blind reviewer envelope itself has only these five inputs.
    for item in bundle["reviewer_payload"]["items"]:
        assert set(item) == {"item_id", "source_text", "source_sha256", "context", "input_sha256", "annotation"}
    _assert_no_authority(result)


def test_two_declared_reviewers_agree_only_as_unverified_submissions(bundle):
    first = _one_payload(bundle)
    second = _one_payload(bundle, "fixture-reviewer-B")
    second["items"][0]["annotation"]["notes"] = "Fixture-only additional explanation."
    second["items"][0]["annotation"]["reviewed_at_utc"] = "2026-10-03T14:24:01.123456+00:00"
    result = _admit(bundle, first, second)
    identity = first["items"][0]["item_id"]
    item = _item(result, identity)
    assert item["status"] == "agreed_multiple_reviews"
    assert item["complete_distinct_reviewer_count"] == 2
    assert item["semantic_signature_count"] == 1
    expected = _digest({key: first["items"][0]["annotation"][key] for key in SIGNATURE_FIELDS})
    assert {entry["semantic_signature_sha256"] for entry in item["received_submissions"]} == {expected}
    _assert_no_authority(result)


@pytest.mark.parametrize("status,expected", [("normative", "single_review"), ("no_normative_rule", "single_review"),
    ("ambiguous", "ambiguous"), ("unsupported", "unsupported")])
def test_explicit_interpretation_dispositions_preserve_reviewers_answer_without_adjudicating(bundle, status, expected):
    reviewed = _one_payload(bundle, status=status)
    result = _admit(bundle, reviewed)
    item = _item(result, reviewed["items"][0]["item_id"])
    assert item["status"] == expected
    assert item["consensus_interpretation_status"] == status
    assert item["received_submissions"][0]["annotation"] == reviewed["items"][0]["annotation"]
    _assert_no_authority(result)


def test_explicit_no_rule_empty_list_is_reviewed_but_null_is_pending(bundle):
    reviewed = _one_payload(bundle, status="no_normative_rule")
    receipt = _admit(bundle, reviewed)
    assert receipt["status_counts"]["single_review"] == 1
    reviewed["items"][0]["annotation"]["normative_rules"] = None
    partial = _admit(bundle, reviewed)
    item = _item(partial, reviewed["items"][0]["item_id"])
    assert item["status"] == "pending"
    assert "normative_rules" in item["received_submissions"][0]["missing_fields"]


def test_explicit_empty_object_and_scope_are_distinct_from_unanswered_nulls(bundle):
    reviewed = _one_payload(bundle)
    annotation = reviewed["items"][0]["annotation"]
    annotation["normative_rules"] = [_rule(object="", conditions=[], exceptions=[], temporal=[])]
    annotation["freeform_qualifier_scope"] = ""
    complete = _admit(bundle, reviewed)
    assert complete["status_counts"]["single_review"] == 1
    annotation["normative_rules"][0]["object"] = None
    partial = _admit(bundle, reviewed)
    item = _item(partial, reviewed["items"][0]["item_id"])
    assert item["status"] == "pending"
    assert any("object" in field for field in item["received_submissions"][0]["missing_fields"])


@pytest.mark.parametrize("field", ["interpretation_status", "ambiguity", "unsupported_meaning", "normative_rules", "freeform_qualifier_scope", "reviewer_id", "reviewed_at_utc"])
def test_unanswered_semantic_field_is_pending_and_never_coerced_to_absence(bundle, field):
    partial = _one_payload(bundle)
    partial["items"][0]["annotation"][field] = None
    result = _admit(bundle, partial)
    item = _item(result, partial["items"][0]["item_id"])
    assert item["status"] == "pending"
    assert item["received_submissions"][0]["complete"] is False
    assert item["received_submissions"][0]["semantic_signature_sha256"] is None


@pytest.mark.parametrize("facet", ["modality", "actor", "action", "object", "conditions", "exceptions", "temporal"])
def test_unanswered_nested_rule_facet_stays_pending_including_qualifier_null(bundle, facet):
    partial = _one_payload(bundle)
    partial["items"][0]["annotation"]["normative_rules"][0][facet] = None
    result = _admit(bundle, partial)
    item = _item(result, partial["items"][0]["item_id"])
    assert item["status"] == "pending"
    submission = item["received_submissions"][0]
    assert submission["complete"] is False
    assert submission["semantic_signature_sha256"] is None
    assert any(facet in field for field in submission["missing_fields"])


@pytest.mark.parametrize("facet", ["modality", "actor", "action", "object", "conditions", "exceptions", "temporal"])
def test_any_completed_facet_disagreement_remains_disputed(bundle, facet):
    first, second = _one_payload(bundle), _one_payload(bundle, "fixture-reviewer-B")
    rule = second["items"][0]["annotation"]["normative_rules"][0]
    rule[facet] = "P" if facet == "modality" else ["different_atom"] if facet in ("conditions", "exceptions", "temporal") else "different_atom"
    result = _admit(bundle, first, second)
    item = _item(result, first["items"][0]["item_id"])
    assert item["status"] == "disputed"
    assert item["semantic_signature_count"] == 2
    assert item["consensus_interpretation_status"] is None
    _assert_no_authority(result)


def test_identical_flat_facets_with_different_connective_or_binder_scope_dispute(bundle):
    first, second = _one_payload(bundle), _one_payload(bundle, "fixture-reviewer-B")
    second["items"][0]["annotation"]["freeform_qualifier_scope"] = "Fixture: either condition applies; the actor variable is universally scoped."
    assert first["items"][0]["annotation"]["normative_rules"] == second["items"][0]["annotation"]["normative_rules"]
    result = _admit(bundle, first, second)
    assert result["status_counts"]["disputed"] == 1
    _assert_no_authority(result)


@pytest.mark.parametrize("mutation", ["qualifier_order", "qualifier_multiplicity", "rule_multiplicity", "rule_attachment"])
def test_rule_and_qualifier_order_multiplicity_and_attachment_are_not_silently_normalized(bundle, mutation):
    first, second = _one_payload(bundle), _one_payload(bundle, "fixture-reviewer-B")
    first["items"][0]["annotation"]["normative_rules"] = [_rule(conditions=["a", "b"]), _rule(actor="second_actor", conditions=["c"])]
    second["items"][0]["annotation"]["normative_rules"] = deepcopy(first["items"][0]["annotation"]["normative_rules"])
    rules = second["items"][0]["annotation"]["normative_rules"]
    if mutation == "qualifier_order":
        rules[0]["conditions"].reverse()
    elif mutation == "qualifier_multiplicity":
        rules[0]["conditions"].append("a")
    elif mutation == "rule_multiplicity":
        rules.append(deepcopy(rules[0]))
    else:
        rules[0]["conditions"], rules[1]["conditions"] = rules[1]["conditions"], rules[0]["conditions"]
    result = _admit(bundle, first, second)
    item = _item(result, first["items"][0]["item_id"])
    assert item["status"] == "disputed"
    assert item["received_submissions"][1]["annotation"]["normative_rules"] == rules


@pytest.mark.parametrize("status", ["ambiguous", "unsupported", "no_normative_rule"])
def test_status_disagreement_is_not_overridden_by_authored_expectations(bundle, status):
    first, second = _one_payload(bundle), _one_payload(bundle, "fixture-reviewer-B", status=status)
    result = _admit(bundle, first, second)
    assert result["status_counts"]["disputed"] == 1
    _assert_no_authority(result)


def test_explicit_problem_reviews_can_preserve_tentative_rules_and_both_flags(bundle):
    reviewed = _one_payload(bundle, status="unsupported")
    annotation = reviewed["items"][0]["annotation"]
    annotation["ambiguity"] = True
    annotation["normative_rules"] = [_rule()]
    result = _admit(bundle, reviewed)
    assert result["status_counts"]["unsupported"] == 1
    stored = _item(result, reviewed["items"][0]["item_id"])["received_submissions"][0]["annotation"]
    assert stored == annotation


def test_same_source_contexts_have_distinct_bound_items_and_cannot_be_swapped(bundle):
    contextual = [item for item in bundle["reviewer_payload"]["items"] if item["context"]["role"] == "explicit_assumptions"]
    assert len(contextual) == 2
    assert contextual[0]["source_text"] == contextual[1]["source_text"]
    assert contextual[0]["source_sha256"] == contextual[1]["source_sha256"]
    assert contextual[0]["input_sha256"] != contextual[1]["input_sha256"]
    reviewed = _payload(bundle, item_ids={contextual[0]["item_id"]})
    reviewed["items"][0]["context"] = deepcopy(contextual[1]["context"])
    reviewed["items"][0]["input_sha256"] = contextual[1]["input_sha256"]
    with pytest.raises(ValueError):
        _admit(bundle, reviewed)


@pytest.mark.parametrize("field", ["source_text", "source_sha256", "input_sha256", "item_id", "context"])
def test_exact_input_binding_rejects_source_context_or_pseudonym_replacement(bundle, field):
    changed = _one_payload(bundle)
    item = changed["items"][0]
    if field == "source_text":
        item[field] += "\n"
        item["source_sha256"] = hashlib.sha256(item[field].encode()).hexdigest()
    elif field == "context":
        item[field]["bindings"]["forged"] = {"kind": "actor_atom", "value": "guessed_actor"}
    elif field in ("source_sha256", "input_sha256"):
        item[field] = "0" * 64
    else:
        item[field] = "unknown-item"
    with pytest.raises(ValueError):
        _admit(bundle, changed)


@pytest.mark.parametrize("fault", ["schema", "instructions", "payload_field", "item_field", "annotation_field", "rule_field", "missing_facet"])
def test_closed_review_schema_rejects_gold_hints_and_authority_claims(bundle, fault):
    changed = _one_payload(bundle)
    item = changed["items"][0]
    if fault == "schema":
        changed["schema"] = "autoformal-source-facet-reviewer/v1"
    elif fault == "instructions":
        changed["instructions"]["task"] = "Copy the organizer answer."
    elif fault == "payload_field":
        changed["authored_reference"] = _rule()
    elif fault == "item_field":
        item["compiler_outcome"] = "accepted"
    elif fault == "annotation_field":
        item["annotation"]["reviewer_authenticated"] = True
    elif fault == "rule_field":
        item["annotation"]["normative_rules"][0]["proof_verified"] = True
    else:
        del item["annotation"]["normative_rules"][0]["conditions"]
    with pytest.raises(ValueError):
        _admit(bundle, changed)


@pytest.mark.parametrize("field,value", [("interpretation_status", "accepted"), ("ambiguity", 0), ("unsupported_meaning", 1),
    ("normative_rules", "none"), ("freeform_qualifier_scope", False), ("notes", []), ("reviewer_id", " "),
    ("reviewer_id", "fixture-reviewer-A "), ("reviewed_at_utc", "2026-10-03"), ("reviewed_at_utc", "2026-10-03T14:23:01"),
    ("reviewed_at_utc", "2026-10-03T14:23:01+01:00"), ("reviewed_at_utc", "2026-02-30T14:23:01Z"),
    ("reviewed_at_utc", True)])
def test_malformed_values_and_non_utc_or_invalid_calendar_timestamps_fail_closed(bundle, field, value):
    changed = _one_payload(bundle)
    changed["items"][0]["annotation"][field] = value
    with pytest.raises(ValueError):
        _admit(bundle, changed)


@pytest.mark.parametrize("facet,value", [("modality", "obligation"), ("modality", True), ("actor", ""), ("action", False),
    ("object", []), ("conditions", "none"), ("exceptions", [""]), ("temporal", [1])])
def test_present_typed_rule_values_are_strict_without_model_interpretation(bundle, facet, value):
    changed = _one_payload(bundle)
    changed["items"][0]["annotation"]["normative_rules"][0][facet] = value
    with pytest.raises(ValueError):
        _admit(bundle, changed)


@pytest.mark.parametrize("fault", ["normative_empty", "normative_ambiguity", "normative_unsupported", "no_normative_nonempty",
    "no_normative_no_reason", "ambiguous_false", "unsupported_false", "qualified_no_scope", "problem_no_reason"])
def test_completed_disposition_contract_does_not_accept_contradictory_flags_or_missing_reason(bundle, fault):
    reviewed = _one_payload(bundle, status="normative" if fault.startswith(("normative", "qualified")) else
                            "ambiguous" if fault.startswith(("ambiguous", "problem")) else
                            "unsupported" if fault.startswith("unsupported") else "no_normative_rule")
    annotation = reviewed["items"][0]["annotation"]
    if fault == "normative_empty":
        annotation["normative_rules"] = []
    elif fault == "normative_ambiguity":
        annotation["ambiguity"] = True
    elif fault == "normative_unsupported":
        annotation["unsupported_meaning"] = True
    elif fault == "no_normative_nonempty":
        annotation["normative_rules"] = [_rule()]
    elif fault.endswith("no_reason"):
        annotation["notes"] = ""
    elif fault == "ambiguous_false":
        annotation["ambiguity"] = False
    elif fault == "unsupported_false":
        annotation["unsupported_meaning"] = False
    else:
        annotation["freeform_qualifier_scope"] = ""
    with pytest.raises(ValueError):
        _admit(bundle, reviewed)


@pytest.mark.parametrize("field", ["reviewer_id", "freeform_qualifier_scope", "notes", "actor", "conditions"])
@pytest.mark.parametrize("bad", ["bad\x00text", "bad\ud800text"])
def test_nul_and_non_utf8_annotation_strings_are_rejected(bundle, field, bad):
    reviewed = _one_payload(bundle)
    annotation = reviewed["items"][0]["annotation"]
    if field == "actor":
        annotation["normative_rules"][0][field] = bad
    elif field == "conditions":
        annotation["normative_rules"][0][field] = [bad]
    else:
        annotation[field] = bad
    with pytest.raises(ValueError):
        _admit(bundle, reviewed)


def test_valid_unicode_is_preserved_exactly_without_implicit_normalization(bundle):
    first, second = _one_payload(bundle), _one_payload(bundle, "fixture-reviewer-B")
    first["items"][0]["annotation"]["freeform_qualifier_scope"] = "Fixture scope: café condition applies."
    second["items"][0]["annotation"]["freeform_qualifier_scope"] = "Fixture scope: cafe\u0301 condition applies."
    result = _admit(bundle, first, second)
    item = _item(result, first["items"][0]["item_id"])
    assert item["status"] == "disputed"
    assert [entry["annotation"]["freeform_qualifier_scope"] for entry in item["received_submissions"]] == [
        first["items"][0]["annotation"]["freeform_qualifier_scope"], second["items"][0]["annotation"]["freeform_qualifier_scope"]]


def test_duplicate_items_payloads_and_declared_reviewer_per_item_do_not_inflate_counts(bundle):
    first = _one_payload(bundle)
    duplicate = deepcopy(first)
    duplicate["items"].append(deepcopy(duplicate["items"][0]))
    with pytest.raises(ValueError):
        _admit(bundle, duplicate)
    with pytest.raises(ValueError):
        _admit(bundle, first, deepcopy(first))
    second = deepcopy(first)
    second["items"][0]["annotation"]["notes"] = "Same declared reviewer, different file."
    with pytest.raises(ValueError):
        _admit(bundle, first, second)


def test_same_declared_reviewer_can_submit_disjoint_item_subsets(bundle):
    identities = [item["item_id"] for item in bundle["reviewer_payload"]["items"][:2]]
    first = _payload(bundle, item_ids={identities[0]})
    second = _payload(bundle, item_ids={identities[1]})
    result = _admit(bundle, first, second)
    assert result["status_counts"]["single_review"] == 2
    assert result["status_counts"]["pending"] == 32


def test_rule_and_qualifier_and_submission_budgets_are_enforced(bundle):
    reviewed = _one_payload(bundle)
    reviewed["items"][0]["annotation"]["normative_rules"] = [_rule()] * 33
    with pytest.raises(ValueError):
        _admit(bundle, reviewed)
    reviewed = _one_payload(bundle)
    reviewed["items"][0]["annotation"]["normative_rules"][0]["conditions"] = ["atom"] * 129
    with pytest.raises(ValueError):
        _admit(bundle, reviewed)
    with pytest.raises(ValueError):
        subject.admit_richer_reviews(bundle, [_one_payload(bundle, f"fixture-reviewer-{index}") for index in range(21)])


def test_changed_authored_reference_never_supplies_annotations_or_resolves_disagreement(bundle):
    panel = deepcopy(bundle["organizer_payload"]["source_panel"])
    row = next(row for row in panel["rows"] if row["split"] == "validation" and row["row_kind"] == "positive")
    row["target"]["rules"][0]["modality"] = "P" if row["target"]["rules"][0]["modality"] != "P" else "F"
    row["target_sha256"] = _digest(row["target"])
    panel["integrity"] = panel_owner._integrity(panel)
    other = preparation.prepare_richer_review(panel, bundle["organizer_payload"]["source_bindings"])
    assert other["reviewer_payload"] == bundle["reviewer_payload"]
    first, second = _one_payload(bundle), _one_payload(bundle, "fixture-reviewer-B")
    second["items"][0]["annotation"]["freeform_qualifier_scope"] = "Fixture competing scope."
    before, after = _admit(bundle, first, second), _admit(other, first, second)
    assert before["status_counts"] == after["status_counts"]
    for left, right in zip(before["items"], after["items"], strict=True):
        assert left["received_submissions"] == right["received_submissions"]
        assert left["status"] == right["status"]
    _assert_no_authority(after)


def test_preparation_is_required_to_be_blank_and_original_binding_cannot_be_resealed_locally(bundle):
    changed = deepcopy(bundle)
    changed["reviewer_payload"]["items"][0]["annotation"]["reviewer_id"] = "fabricated"
    changed["reviewer_manifest"]["payload_sha256"] = _digest(changed["reviewer_payload"])
    with pytest.raises(ValueError):
        _admit(changed)
    changed = deepcopy(bundle)
    changed["organizer_payload"]["reviewer_key"][0]["original_id"] = "different"
    with pytest.raises(ValueError):
        _admit(changed)


@pytest.mark.parametrize("mutation", ["extra", "status_count", "boolean_alias", "complete_alias", "float_count", "source", "signature"])
def test_validator_reconstructs_closed_receipt_even_if_attacker_reseals_it(bundle, mutation):
    reviewed = _one_payload(bundle)
    receipt = _admit(bundle, reviewed)
    changed = deepcopy(receipt)
    item = _item(changed, reviewed["items"][0]["item_id"])
    if mutation == "extra":
        changed["reviewer_authenticated"] = True
    elif mutation == "status_count":
        changed["status_counts"]["pending"] -= 1
    elif mutation == "boolean_alias":
        changed["qualified"] = 0
    elif mutation == "complete_alias":
        item["received_submissions"][0]["complete"] = 1
    elif mutation == "float_count":
        item["complete_distinct_reviewer_count"] = 1.0
    elif mutation == "source":
        item["source_text"] += " "
    else:
        item["received_submissions"][0]["semantic_signature_sha256"] = "0" * 64
    changed["receipt_sha256"] = _digest({key: value for key, value in changed.items() if key != "receipt_sha256"})
    with pytest.raises(ValueError):
        subject.validate_richer_review_admission(changed, bundle, [reviewed])


def test_validation_binds_exact_submission_and_bundle_generations(bundle):
    reviewed = _one_payload(bundle)
    receipt = _admit(bundle, reviewed)
    changed = deepcopy(reviewed)
    changed["items"][0]["annotation"]["notes"] = "Different submission bytes, same semantic signature."
    with pytest.raises(ValueError):
        subject.validate_richer_review_admission(receipt, bundle, [changed])
    validation = subject.validate_richer_review_admission(receipt, bundle, [reviewed])
    assert validation["qualified"] is False
    assert json.loads(json.dumps(receipt, allow_nan=False)) == receipt


def test_admission_and_replay_do_not_import_models_provers_or_network_clients(bundle, monkeypatch):
    original = builtins.__import__
    forbidden = {"torch", "numpy", "transformers", "sentence_transformers", "requests", "httpx", "openai", "z3", "cvc5"}
    def guarded(name, *args, **kwargs):
        assert name.split(".")[0] not in forbidden, name
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded)
    reviewed = _one_payload(bundle)
    receipt = _admit(bundle, reviewed)
    subject.validate_richer_review_admission(receipt, bundle, [reviewed])
    for field in ("model_calls", "provider_calls", "encoder_calls", "prover_calls"):
        assert receipt[field] == 0
