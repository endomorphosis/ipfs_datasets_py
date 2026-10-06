"""Full-cohort refusal controls; authored fixtures establish transport only."""
import builtins
import copy
import hashlib
import json
import subprocess

import pytest

from ipfs_datasets_py.logic.legal_ir import canonical_qualifier_training_preflight as subject
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_formula_codec as word
from tests.unit.logic.legal_ir import test_canonical_byte_codec as byte_fixture
from tests.unit.logic.legal_ir import test_canonical_label_evidence_intake as review_fixture
from tests.unit.logic.legal_ir import test_canonical_statement_scope as scope_fixture


def example(identity="authored-train", split="train"):
    return {"id": identity, "split": split,
            "source_text": "The clerk must retain evidence if paid unless emergency within ten days.",
            "canonical_ir": {"rules": [{"modality": "O", "actor": "clerk", "action": "retain", "object": "evidence",
                "conditions": ["paid"], "exceptions": ["emergency"], "temporal": ["within_ten_days"]}]}}


def scoped(value=None):
    value = scope_fixture.scope_case(repeated=False) if value is None else value
    return {"id": "authored-scope", "split": "train", "source_text": value["request"]["source_text"],
            "context": value["request"]["context"], "scope_declaration": value["declaration"],
            "canonical_ir": {"rules": [{"modality": "O", "actor": "clerk", "action": "retain", "object": "evidence",
                "conditions": ["a"], "exceptions": ["x", "y"], "temporal": ["t"]}]}}


def run(rows=None, **kwargs):
    return subject.preflight_qualifier_cohort([example()] if rows is None else rows, **kwargs)


def test_all_seven_facets_fit_without_training_or_admission():
    row = example()
    original = copy.deepcopy(row)
    report = run([row])
    assert row == original
    assert report["cohort_word_representable"]
    assert report["qualifier_value_counts_observed"] == dict(conditions=1, exceptions=1, temporal=1)
    assert report["complete_rule_count_observed"] == 1
    assert report["rows"][0]["word_transport"]["required_target_token_count"] <= 64
    assert report["output_limit"] == report["source_context_limit_unchanged"] == 512
    assert not any(report[field] for field in subject._FALSE)
    assert report["review"]["status"] == "not_supplied"
    assert report["rows_discarded"] == 0


def test_tuning_target_does_not_enter_train_vocabulary():
    train, tuning = example(), example("authored-tuning", "tuning")
    tuning["source_text"] = "The clerk must retain evidence unless emergency within ten days if paid."
    tuning["canonical_ir"]["rules"][0]["conditions"] = ["unseen_qualifier"]
    report = run([train, tuning])
    assert report["word_supported_rows"] == 1
    assert report["complete_rule_count_observed"] == 2
    assert report["qualifier_value_counts_observed"] == dict(conditions=2, exceptions=2, temporal=2)
    assert "out-of-vocabulary typed atoms" in report["rows"][1]["word_transport"]["reason"]
    assert not report["cohort_word_representable"]
    assert report["qualifier_value_counts_observed"] == dict(conditions=2, exceptions=2, temporal=2)


def test_one_failed_train_row_blocks_complete_vocab_fit_without_filtering():
    rows = [example(), example("bad-train")]
    rows[1]["source_text"] += " additional"
    rows[1]["canonical_ir"]["rules"][0]["conditions"] = ["b", "a", "b"]
    report = run(rows)
    assert report["reported_row_count"] == report["cohort_row_count"] == 2
    assert report["word_codec_sha256"] is None
    assert "no failed row was discarded" in report["word_codec_error"]
    assert report["qualifier_value_counts_observed"]["conditions"] == 4
    assert report["word_supported_rows"] == report["rows_discarded"] == 0
    assert "normalization is forbidden" in report["rows"][1]["issues"][0]


@pytest.mark.parametrize("split", [None, "unknown", True])
def test_unclassified_row_blocks_new_vocab_fit_and_keeps_label_counts(split):
    unknown = example("unclassified")
    unknown["source_text"] += " additional"
    if split is None:
        del unknown["split"]
    else:
        unknown["split"] = split
    report = run([example(), unknown])
    assert report["word_codec_sha256"] is None
    assert "unclassified" in report["word_codec_error"]
    assert report["reported_row_count"] == report["cohort_row_count"] == 2
    assert report["complete_rule_count_observed"] == 2
    assert report["qualifier_value_counts_observed"] == dict(conditions=2, exceptions=2, temporal=2)
    assert report["word_supported_rows"] == 0


def test_malformed_nonrow_cannot_be_filtered_while_fitting_train():
    report = run([example(), None])
    assert report["word_codec_sha256"] is None
    assert report["reported_row_count"] == 2
    assert report["rows_with_unavailable_qualifier_counts"] == 1
    assert report["qualifier_value_counts_observed"] == dict(conditions=1, exceptions=1, temporal=1)
    assert not report["cohort_word_representable"]


def test_explicit_invalid_tuning_is_reported_without_entering_train_vocab():
    invalid = example("invalid-tuning", "tuning")
    del invalid["canonical_ir"]["rules"][0]["conditions"]
    report = run([example(), invalid])
    assert report["word_codec_sha256"] == run()["word_codec_sha256"]
    assert report["word_supported_rows"] == 1
    assert report["reported_row_count"] == 2
    assert not report["cohort_word_representable"]


def test_exact_flat_scope_matches_every_target_leaf():
    report = run([scoped()])
    assert report["cohort_word_representable"]
    assert report["rows"][0]["scope_transport"]["supplied"]
    assert not report["train_eligible"]


def test_flat_target_cannot_drop_or_change_a_scope_leaf():
    row = scoped()
    row["canonical_ir"]["rules"][0]["exceptions"] = ["x"]
    report = run([row])
    assert "complete scope leaves differ" in report["rows"][0]["issues"][0]
    assert not report["cohort_word_representable"]


def test_repeated_occurrences_cannot_be_normalized_into_flat_target():
    row = scoped(scope_fixture.scope_case(repeated=True))
    row["canonical_ir"]["rules"][0]["conditions"] = ["a", "b"]
    report = run([row])
    assert "occurrence-aware transport required" in report["rows"][0]["issues"][0]
    assert not report["normalization_performed"]
    assert not report["cohort_word_representable"]
    issues = report["rows"][0]["scope_transport"]["compatibility"]["issues"]
    assert any(entry["code"] == "legacy_qualifier_sort_or_dedup_loses_occurrences" for entry in issues)


@pytest.mark.parametrize("op", ["not", "any"])
def test_changed_qualifier_operator_needs_occurrence_transport(op):
    value = scope_fixture.scope_case(repeated=False)
    value["declaration"]["rules"][0]["qualifiers"]["conditions"] = (
        {"op": "not", "child": scope_fixture.leaf("q1"), "operator_anchor": None}
        if op == "not" else scope_fixture.connective("any", [scope_fixture.leaf("q1")]))
    scope_fixture.seal(value["declaration"])
    report = run([scoped(value)])
    assert "occurrence-aware transport required" in report["rows"][0]["issues"][0]


def test_multiple_rules_remain_counted_and_unrepresentable():
    row = example()
    row["canonical_ir"]["rules"].append(copy.deepcopy(row["canonical_ir"]["rules"][0]))
    report = run([row])
    assert report["complete_rule_count_observed"] == 2
    assert report["qualifier_value_counts_observed"] == dict(conditions=2, exceptions=2, temporal=2)
    assert not report["cohort_word_representable"]
    assert "exactly one rule" in report["rows"][0]["issues"][0]


def test_duplicate_source_still_contributes_every_observable_qualifier():
    report = run([example(), example("duplicate", "tuning")])
    assert report["reported_row_count"] == 2
    assert report["complete_rule_count_observed"] == 2
    assert report["qualifier_value_counts_observed"] == dict(conditions=2, exceptions=2, temporal=2)
    assert not report["cohort_word_representable"]


def test_missing_qualifier_field_is_unavailable_instead_of_an_empty_list():
    row = example()
    del row["canonical_ir"]["rules"][0]["conditions"]
    report = run([row])
    assert report["rows_with_unavailable_qualifier_counts"] == 1
    assert report["rows"][0]["qualifier_facets_unavailable"] == ["/rules/0/conditions"]
    assert not report["cohort_word_representable"]


@pytest.mark.parametrize("role,text", [("declared_context", "Supplied context"), ("required_unavailable", "")])
def test_context_is_never_concatenated_or_implicitly_resolved(role, text):
    row = example()
    row["context"] = {"role": role, "text": text, "bindings": {}, "sha256": hashlib.sha256(text.encode()).hexdigest()}
    report = run([row])
    assert "no concatenation performed" in report["rows"][0]["issues"][0]
    assert not report["train_eligible"]


def test_byte_579_token_fixture_fails512_while_word_codec_fits_all_facets():
    proposal = byte_fixture.proposal()
    row = {"id": "authored-byte", "split": "train", "source_text": byte_fixture.SOURCE,
           "canonical_ir": copy.deepcopy(proposal["canonical_ir"]), "byte_proposal": proposal}
    report = run([row])
    assert report["cohort_word_representable"]
    assert report["rows"][0]["byte_transport"]["payload_bytes"] == 577
    assert report["rows"][0]["byte_transport"]["required_token_count"] == 579
    assert report["rows"][0]["byte_transport"]["configured_output_cap"] == 512
    assert not report["cohort_byte_representable"]
    assert report["qualifier_value_counts_observed"] == dict(conditions=2, exceptions=2, temporal=0)


def test_byte_proposal_must_match_complete_target_and_exact_source():
    proposal = byte_fixture.proposal()
    row = {"id": "bad-byte", "split": "train", "source_text": byte_fixture.SOURCE,
           "canonical_ir": copy.deepcopy(proposal["canonical_ir"]), "byte_proposal": proposal}
    proposal["canonical_ir"]["rules"][0]["exceptions"].pop()
    report = run([row])
    assert "complete seven-facet target" in report["rows"][0]["byte_transport"]["reason"]
    assert report["word_supported_rows"] == 1
    assert not report["train_eligible"]


def test_small_byte_transport_success_still_grants_no_native_authority():
    text = "A must B."
    rule = dict(modality="O", actor="a", action="b", object="", conditions=[], exceptions=[], temporal=[])
    anchors = []
    for facet, literal in (("actor", "A"), ("modality", "must"), ("action", "B")):
        start = text.index(literal)
        anchors.append(dict(field_path="/rules/0/" + facet, facet=facet, canonical_symbol=rule[facet],
                            start=start, end=start + len(literal), source_text=literal,
                            offset_unit="unicode_character_half_open"))
    proposal = dict(schema="canonical-anchored-byte-proposal/v1", source_sha256=hashlib.sha256(text.encode()).hexdigest(),
                    canonical_ir={"rules": [rule]}, anchors=sorted(anchors,key=lambda x:x["field_path"]),
                    facet_operators=dict(conditions="all", exceptions="any", temporal="all"), single_rule_scope=True,
                    **dict.fromkeys(byte_fixture.FALSE_FIELDS,False))
    report = run([dict(id="authored-small-byte",split="train",source_text=text,
                       canonical_ir={"rules": [rule]},byte_proposal=proposal)])
    assert report["cohort_byte_representable"]
    assert report["rows"][0]["byte_transport"]["required_token_count"] <= 512
    assert not any(report[field] for field in subject._FALSE)


@pytest.mark.parametrize("change", ["unknown_source", "source_overflow", "duplicate_source", "fake_authority"])
def test_invalid_cohort_row_is_retained(change):
    codec = word.fit_codec([
        {key: example()[key] for key in ("id", "source_text", "canonical_ir")}])
    row = example("second", "tuning")
    if change == "unknown_source":
        row["source_text"] += " unknownlexeme"
    elif change == "source_overflow":
        row["source_text"] = "clerk " * 65
    elif change == "fake_authority":
        row["train_eligible"] = True
    report = run([example(), row], word_codec=codec)
    assert report["reported_row_count"] == 2
    assert report["word_supported_rows"] == 1
    assert not report["cohort_word_representable"]
    assert not report["train_eligible"]


def test_supplied_receipt_or_row_never_authenticates_labels():
    report = run(review_inputs={"receipt": {"train_eligible": True, "qualified": True}})
    assert report["review"]["status"] == "invalid"
    assert "receipt alone" in report["review"]["reason"]
    assert report["cohort_word_representable"]
    assert not report["train_eligible"]


def test_existing_review_intake_replays_pending_zero_masks():
    value = review_fixture.case(empty=True)
    report = run(review_inputs=value)
    assert report["review"]["replayed"]
    assert report["review"]["verification_status"] == report["review"]["admission_status"] == "pending"
    assert set(report["review"]["masks"].values()) == {0}
    assert not report["review"]["train_eligible"]
    assert not report["train_eligible"]
    assert not report["review_to_cohort_binding_assessed"]
    assert not report["review_replay_is_training_authority"]


def test_declared_agreement_and_adjudication_do_not_enable_training():
    value = review_fixture.case()
    review_fixture.add_adjudication(value)
    report = run(review_inputs=value)
    assert report["review"]["replayed"]
    assert report["review"]["declared_package_item_count"] == 1
    assert report["review"]["formal_targets_admitted"] == 0
    assert not report["train_eligible"]


def test_resealed_forged_review_mask_is_not_an_authoritative_intake():
    value = review_fixture.case(empty=True)
    receipt = value["recording"]["receipt"]
    receipt["items"][0]["masks"]["weak_decoder_fit"] = 1
    receipt["receipt_sha256"] = review_fixture.digest({key:entry for key,entry in receipt.items() if key != "receipt_sha256"})
    value["expected_bindings"]["receipt"] = review_fixture.binding(receipt)
    value["package"]["recording_binding"] = copy.deepcopy(value["expected_bindings"]["receipt"])
    review_fixture.seal(value["package"])
    report = run(review_inputs=value)
    assert report["review"]["status"] == "invalid"
    assert not report["train_eligible"]


def test_all_eight_native_requirements_remain_separate_from_codec_success():
    report = run()
    assert [row["requirement_id"] for row in report["minimum_native_family_floor"]] == [
        "FOL", "DFOL", "TFOL", "TDFOL", "CEC", "DCEC", "frame_logic", "propositional"]
    assert not report["native_family_floor_assessed"]
    assert not report["family_applicability_assessed"]
    assert not report["source_codec_profile_is_native_family_evidence"]


def test_transport_does_not_infer_deadline_clock_or_lean_threshold():
    row = example()
    row["canonical_ir"]["rules"][0]["temporal"] = ["within 10 days"]
    report = run([row])
    assert report["cohort_word_representable"]
    assert not report["Lean_admitted"]
    assert not report["Lake_executed"]
    assert not report["source_semantics_verified"]


def test_no_model_import_or_native_process_during_preflight(monkeypatch):
    original = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name.split(".")[0] in {"torch", "transformers", "sentence_transformers", "huggingface_hub"}:
            raise AssertionError("model import forbidden")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded)
    def forbidden(*args, **kwargs):
        raise AssertionError("native process forbidden")
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    report = run()
    assert report["cohort_word_representable"]
    assert not report["model_executed"]


def test_fresh_reports_and_seals_do_not_alias_input():
    first = run()
    seal = first.pop("content_sha256")
    assert hashlib.sha256(json.dumps(first,sort_keys=True,separators=(",", ":"),ensure_ascii=False).encode()).hexdigest() == seal
    first["minimum_native_family_floor"].clear()
    assert len(run()["minimum_native_family_floor"]) == 8


@pytest.mark.parametrize("rows", [[], [example()] * 65, {"rows": [example()]}, [float("nan")]])
def test_envelope_limits_fail_without_partial_dispatch(rows):
    with pytest.raises(ValueError):
        run(rows)
