"""Synthetic scorer tests: no model, compiler, native tool, or proof authority."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
SPEC = importlib.util.spec_from_file_location("decoder_fidelity_subject",
    ROOT / "ipfs_datasets_py/logic/formalization/autoencoder/decoder_source_fidelity.py")
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)


def rule(actor="Agency", **updates):
    value = dict(modality="O", actor=actor, action="retain", object="file",
        conditions=[], exceptions=[], temporal=["at least 20 days"])
    return {**value, **updates}


def validator(target):
    item = target["rules"][0]
    return {"valid": set(item) == set(subject.FACETS) and item["modality"] in ("O", "P", "F")}


def text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def inputs(gold=None, actual=None):
    gold = gold if gold is not None else [[rule()], [rule("Officer"), rule("Court")]]
    actual = deepcopy(gold if actual is None else actual)
    rows = [dict(id="row-"+str(i), clause_count=len(rules), target={"rules": rules},
        source_text="Source clause "+str(i)) for i, rules in enumerate(gold)]
    strings = [value if type(value) is str else text({"rules": value}) for value in actual]
    vocabulary = ["<pad>", "<bos>", "<eos>"] + sorted(set(strings+["unused content"]))
    predictions = [dict(id=row["id"], token_ids=[vocabulary.index(value)],
        eos_reached=True, generation_status="eos") for row, value in zip(rows, strings)]
    return rows, predictions, {"target_vocabulary": vocabulary}


def score(rows, predictions, codec, **kwargs):
    return subject.score_predictions(rows, predictions, codec=codec, validate_rule=validator, **kwargs)


def test_exact_scores_all_lengths_and_facets_with_no_authority_or_mutation():
    args = inputs(); original = deepcopy(args); result = score(*args)
    assert args == original
    assert result["metrics"]["ordered_exact"] == 2
    assert result["metrics"]["expected_rules"] == 3
    assert result["by_length"]["2"]["metrics"]["rows"] == 1
    for facet in subject.FACETS:
        assert result["by_facet"][facet] == dict(correct=3, total=3, unordered_correct=3)
    assert all(result[key] is False for key in subject.FALSE)
    assert result["source_text_used_for_decoding"] is False
    assert result["rows"][0]["source_provenance"]["use"] == "evaluation_provenance_only"


@pytest.mark.parametrize("facet", subject.FACETS)
def test_each_changed_facet_scored_separately_and_against_original_position(facet):
    first = rule(); altered = deepcopy(first)
    altered[facet] = ["changed"] if facet in subject.FACETS[4:] else "changed"
    if facet == "modality": altered[facet] = "P"
    result = score(*inputs(gold=[[first]], actual=[[altered]]))
    assert result["metrics"]["ordered_exact"] == 0
    assert result["metrics"]["whole_rules_missing"] == result["metrics"]["whole_rules_extra"] == 1
    for field in subject.FACETS:
        assert result["by_facet"][field]["correct"] == int(field != facet)


def test_rule_multiplicity_omissions_extras_and_reordering_are_distinct():
    a,b = rule("A"),rule("B")
    result = score(*inputs(gold=[[a,a,b]], actual=[[a,b,b]]))
    assert result["metrics"]["whole_rules_missing"] == result["metrics"]["whole_rules_extra"] == 1
    assert result["metrics"]["duplicate_rules"] == 1
    assert result["by_facet"]["actor"]["correct"] == 2
    reordered = score(*inputs(gold=[[a,b]], actual=[[b,a]]))
    assert reordered["metrics"]["all_rules_preserved"] == 1
    assert reordered["metrics"]["ordered_exact"] == 0
    assert reordered["metrics"]["order_mismatch_rows"] == 1
    assert reordered["by_facet"]["actor"] == dict(correct=0,total=2,unordered_correct=2)


def test_missing_middle_rule_does_not_realign_using_gold():
    a,b,c = rule("A"),rule("B"),rule("C")
    result = score(*inputs(gold=[[a,b,c]], actual=[[a,c]]))
    assert result["metrics"]["whole_rules_missing"] == 1
    assert result["by_facet"]["actor"]["correct"] == 1
    assert result["by_facet"]["actor"]["total"] == 3


@pytest.mark.parametrize("malformed", ["{", '{"rules":[],"rules":[]}', '{"rules":NaN}',
    '{"rules":Infinity}', '{"rules":1e999}', '{"rules":"wrong"}', '{"unexpected":[]}',
    'null', '[1,2]', '{"rules":[{"actor":"\\ud800"}]}'])
def test_malformed_generated_json_never_uses_gold_or_disappears(malformed):
    result = score(*inputs(gold=[[rule()]],actual=[malformed]))
    assert result["metrics"]["ordered_exact"] == 0
    assert result["metrics"]["whole_rules_missing"] == 1
    assert result["metrics"]["invalid_rows"] == 1
    assert all(field["correct"] == 0 for field in result["by_facet"].values())
    assert result["rows"][0]["errors"]


@pytest.mark.parametrize("bad_id", [-1,0,1,2,True,3.0,None,"3",float("nan"),100000])
def test_bad_content_token_ids_fail_closed_without_python_negative_indexing(bad_id):
    rows,predictions,codec=inputs(gold=[[rule()]])
    predictions[0]["token_ids"]=[bad_id]
    result=score(rows,predictions,codec)
    assert result["metrics"]["ordered_exact"] == 0
    assert result["metrics"]["whole_rules_missing"] == 1
    assert result["rows"][0]["generated_ir"] is None


def test_invalid_rule_retained_as_extra_and_neighbor_valid_rule_still_visible():
    good,bad=rule(),rule("Invalid",modality="X")
    result=score(*inputs(gold=[[good,rule("Other")]],actual=[[good,bad]]))
    assert result["metrics"]["whole_rules_missing"] == 1
    assert result["metrics"]["whole_rules_extra"] == 1
    assert result["metrics"]["invalid_rule_count"] == 1
    assert result["by_facet"]["actor"]["correct"] == 1
    assert result["rows"][0]["generated_ir"]["rules"][1] == bad


def test_empty_rules_missing_all_and_not_syntax_valid():
    result=score(*inputs(gold=[[rule()]],actual=[[]]))
    assert result["metrics"]["whole_rules_missing"] == 1
    assert result["metrics"]["syntax_valid"] == 0


def test_missing_prediction_kept_in_denominator_and_cannot_pass_comparison():
    rows,predictions,codec=inputs()
    baseline=score(rows,predictions,codec)
    candidate=score(rows,predictions[:1],codec)
    assert candidate["complete_evaluation"] is False
    assert candidate["metrics"]["rows"] == 2
    assert candidate["metrics"]["prediction_missing_rows"] == 1
    assert candidate["metrics"]["whole_rules_missing"] == 2
    assert subject.compare_nonregression(candidate,baseline)["accepted"] is False


@pytest.mark.parametrize("which", ["duplicate", "unknown"])
def test_ambiguous_prediction_identity_refused(which):
    rows,predictions,codec=inputs()
    predictions[1]["id"] = predictions[0]["id"] if which == "duplicate" else "other"
    with pytest.raises(ValueError,match="prediction identity"):score(rows,predictions,codec)


def test_eos_separate_from_content_and_contradictions_rejected():
    rows,predictions,codec=inputs(gold=[[rule()]])
    predictions[0].update(eos_reached=False,generation_status="output_limit")
    result=score(rows,predictions,codec)
    assert result["metrics"]["ordered_exact"] == result["metrics"]["eos_count"] == 0
    assert result["by_facet"]["actor"]["correct"] == 1
    predictions[0]["eos_reached"]=True
    result=score(rows,predictions,codec)
    assert result["rows"][0]["generated_ir"] is None
    assert "contradicts" in result["rows"][0]["errors"][0]


def test_budget_includes_bos_and_eos_and_cannot_be_exceeded():
    rows,predictions,codec=inputs(gold=[[rule()]])
    predictions[0]["token_ids"]*=3
    result=score(rows,predictions,codec,output_limit=4)
    assert "EOS exceeds" in result["rows"][0]["errors"][0]


def test_no_reference_or_source_fallback_even_when_prediction_provides_fake_ir():
    rows,predictions,codec=inputs(gold=[[rule()]])
    predictions[0].update(token_ids=[],target=rows[0]["target"],generated_ir=rows[0]["target"])
    result=score(rows,predictions,codec)
    assert result["metrics"]["ordered_exact"] == 0
    assert result["rows"][0]["generated_ir"] is None


def test_control_formats_preserve_ids_and_gold_and_declare_no_verified_execution():
    rows,predictions,codec=inputs()
    for kind,assignment in (("conditioned",{"row-0":"row-0","row-1":"row-1"}),
            ("zero_condition",{"row-0":"row-0","row-1":"row-1"}),
            ("source_shuffle",{"row-0":"row-1","row-1":"row-0"})):
        result=score(rows,predictions,codec,control=dict(kind=kind,source_assignment=assignment))
        assert result["metrics"]["ordered_exact"] == 2
        assert result["control_execution_verified"] is False
        assert result["control"]["source_assignment"]==assignment
    with pytest.raises(ValueError,match="derangement"):
        score(rows,predictions,codec,control=dict(kind="source_shuffle",source_assignment={"row-0":"row-0","row-1":"row-1"}))


def test_comparison_neutral_no_progress_and_no_weight_selection():
    result=score(*inputs());comparison=subject.compare_nonregression(result,result,result)
    assert comparison["accepted"] is True and comparison["strict_progress"] is False
    assert comparison["weight_selection_performed"] is False


def test_improvement_one_length_cannot_pay_for_other_length_regression():
    rows,predictions,codec=inputs()
    baseline_predictions=deepcopy(predictions);baseline_predictions[0]["token_ids"]=[]
    candidate_predictions=deepcopy(predictions);candidate_predictions[1]["token_ids"]=[]
    baseline=score(rows,baseline_predictions,codec);candidate=score(rows,candidate_predictions,codec)
    comparison=subject.compare_nonregression(candidate,baseline)
    assert comparison["accepted"] is False
    assert any("length=2" in reason for reason in comparison["reasons"])


def test_every_facet_guard_can_reject_without_aggregate_exact_change():
    gold=rule();wrong_actor=rule("Other");wrong_action=rule(action="destroy")
    rows,predictions,codec=inputs(gold=[[gold],[gold]],actual=[[wrong_actor],[wrong_action]])
    # Both candidate documents are available in one unchanged codec.
    baseline_predictions=deepcopy(predictions[:1]);baseline_predictions[0]["id"]="row-0"
    candidate_predictions=deepcopy(predictions[1:]);candidate_predictions[0]["id"]="row-0"
    baseline=score(rows[:1],baseline_predictions,codec);candidate=score(rows[:1],candidate_predictions,codec)
    assert baseline["metrics"]["ordered_exact"] == candidate["metrics"]["ordered_exact"] == 0
    comparison=subject.compare_nonregression(candidate,baseline)
    assert comparison["accepted"] is False
    assert any("action regressed" in reason for reason in comparison["reasons"])


def test_incumbent_guard_retains_improvement_over_baseline():
    rows,predictions,codec=inputs();bad=deepcopy(predictions)
    bad[0]["token_ids"]=[]
    baseline=score(rows,bad,codec);incumbent=score(rows,predictions,codec)
    comparison=subject.compare_nonregression(incumbent,baseline)
    assert comparison["accepted"] and comparison["strict_progress"]
    result=subject.compare_nonregression(baseline,baseline,incumbent)
    assert not result["accepted"]
    assert any(reason.startswith("incumbent/") for reason in result["reasons"])


def test_report_mutation_and_comparison_identity_changes_refused():
    rows,predictions,codec=inputs();baseline=score(rows,predictions,codec)
    altered=deepcopy(baseline);altered["metrics"]["ordered_exact"]+=1
    with pytest.raises(ValueError,match="modified"):subject.compare_nonregression(altered,baseline)
    changed=score(rows,predictions,codec,validator_id="different-owner")
    with pytest.raises(ValueError,match="identity"):subject.compare_nonregression(changed,baseline)


@pytest.mark.parametrize("mutation", ["source", "count", "reference", "duplicate_row"])
def test_bad_reference_metadata_refused(mutation):
    rows,predictions,codec=inputs()
    if mutation=="source":rows[0]["source_sha256"]="a"*64
    if mutation=="count":rows[0]["clause_count"]+=1
    if mutation=="reference":rows[0]["target"]["rules"][0]["actor"]=False
    if mutation=="duplicate_row":rows[1]["id"]=rows[0]["id"]
    with pytest.raises(ValueError):score(rows,predictions,codec)


def test_validator_cannot_normalize_or_mutate_reference_or_output():
    rows,predictions,codec=inputs();original=deepcopy(rows)
    def mutator(target):
        target["rules"][0]["actor"]="normalized"
        return {"valid":True}
    with pytest.raises(ValueError,match="mutated"):
        subject.score_predictions(rows,predictions,codec=codec,validate_rule=mutator)
    assert rows==original


def test_unicode_json_and_source_hash_preserved():
    rows,predictions,codec=inputs(gold=[[rule("L’agence")]])
    rows[0]["source_text"]="L’agence doit conserver le dossier."
    rows[0]["source_sha256"]=hashlib.sha256(rows[0]["source_text"].encode()).hexdigest()
    result=score(rows,predictions,codec)
    assert result["metrics"]["ordered_exact"]==1
    assert result["rows"][0]["generated_ir"]["rules"][0]["actor"]=="L’agence"


def test_hash_only_source_provenance_remains_bound_to_comparison():
    rows,predictions,codec=inputs()
    for row in rows:
        row["source_sha256"]=hashlib.sha256(row.pop("source_text").encode()).hexdigest()
    baseline=score(rows,predictions,codec)
    rows[0]["source_sha256"]="a"*64
    changed=score(rows,predictions,codec)
    with pytest.raises(ValueError,match="identity"):
        subject.compare_nonregression(changed,baseline)
    assert baseline["rows"][0]["source_provenance"]["source_text"] is None
    assert baseline["source_semantics_verified"] is False
