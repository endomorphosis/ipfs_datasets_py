"""Pure diagnostic protocol tests: no trained models, corpus or native calls."""
from collections import Counter
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[5]
SPEC = importlib.util.spec_from_file_location("rejected_decoder_controls_test_subject",
    ROOT/"scripts/ops/autoencoder/evaluate_rejected_decoder_controls.py")
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)


def plan():
    return dict(architecture_arms=["first_step", "every_step"],
        loss_arms=["reference_ce", "semantic_fields"], seed_order=[1729, 2718])


def manifest(tmp_path):
    result = dict(inputs={}, rejected_states={})
    def pinned(name):
        path = tmp_path/(name+".json")
        subject.save(path, {})
        result["inputs"][str(path)] = subject.sha(path)
        return str(path)
    result["source_run_summary"] = pinned("source")
    for arm, *_ in subject.arm_identities(plan()):
        result["rejected_states"][arm] = {key: pinned(arm+"-"+key) for key in ("state", "training", "predictions")}
    return result


def fixture(count=2, *, unicode=False, qualifiers=False):
    rules = [dict(modality="O", actor="registrar" if not unicode else "行政官é", action="preserve",
        object="archive", conditions=[], exceptions=[], temporal=[]) for _ in range(count)]
    if qualifiers:
        rules[0].update(conditions=["approved", "ready"], exceptions=["emergency"], temporal=["within 10 days"])
    target = dict(rules=rules)
    # Independent lexical encoder, using complete canonical JSON rather than
    # the scorer's recursive token/role traversal.
    wire = json.dumps(target, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|[{}\[\],:]', wire)
    assert "".join(tokens) == wire
    vocabulary = ["<pad>", "<bos>", "<eos>"] + sorted(set(tokens))
    row = dict(id="paragraph", source_text="Complete source", input=[0.]*384,
        target_ids=[1]+[vocabulary.index(token) for token in tokens]+[2])
    reference = dict(id=row["id"], source_text=row["source_text"], target=target, clause_count=count)
    return row, reference, dict(target_vocabulary=vocabulary), tokens


def records():
    lineage = dict(domain="legal_ir", teacher_checkpoint_sha256="a"*64)
    identities = subject.arm_identities(plan())
    identity = identities[0]
    exact_lineage = dict(lineage, student_lineage=identity[0])
    state = dict(schema="long-source-last-complete-diagnostic/v1", architecture=identity[1], selected=False,
        lineage=exact_lineage, model_state={"body.weight": [[1., 2.]]}, **subject.FALSE)
    state["weights_sha256"] = subject.digest(state["model_state"])
    training = dict(lineage=exact_lineage, last_complete_attempt_is_selected=False,
        last_complete_attempt_state_available=True, last_complete_attempt=dict(numerical={}, fidelity={}),
        optimizer_steps=340, valid_target_token_presentations=225840, strategy=identity[2])
    runs = [dict(arm=arm, architecture=architecture, strategy=strategy, seed=seed,
        budget_completed=True, training=deepcopy(training)) for arm, architecture, strategy, seed in identities]
    return identity, state, training, [dict(id="a", token_ids=[3])], dict(complete=True, runs=runs), lineage


def test_complete_diagnostic_manifest_requires_all_twenty_five_unique_pointers(tmp_path):
    value = manifest(tmp_path)
    before = deepcopy(value)
    assert subject.validate_diagnostic_inputs(value, plan()) is None
    assert len(value["inputs"]) == 25 and value == before


@pytest.mark.parametrize("mutation", ["missing_arm", "extra_arm", "missing_state", "extra_pointer", "unpinned",
    "relative", "changed", "duplicate_role", "missing_summary"])
def test_incomplete_or_drifted_diagnostic_inputs_fail_closed(tmp_path, mutation):
    value = manifest(tmp_path); arm = next(iter(value["rejected_states"])); record = value["rejected_states"][arm]
    if mutation == "missing_arm": value["rejected_states"].pop(arm)
    elif mutation == "extra_arm": value["rejected_states"]["unknown"] = deepcopy(record)
    elif mutation == "missing_state": record.pop("state")
    elif mutation == "extra_pointer": record["extra"] = record["state"]
    elif mutation == "unpinned": value["inputs"].pop(record["predictions"])
    elif mutation == "relative": record["state"] = "relative.json"
    elif mutation == "changed": Path(record["state"]).write_text('{"changed":true}')
    elif mutation == "duplicate_role": record["training"] = record["state"]
    elif mutation == "missing_summary": value.pop("source_run_summary")
    with pytest.raises(ValueError): subject.validate_diagnostic_inputs(value, plan())


@pytest.mark.parametrize("key, value", [("architecture_arms", ["every_step", "first_step"]),
    ("loss_arms", ["reference_ce"]), ("seed_order", [1729, 1729])])
def test_original_arm_protocol_cannot_be_silently_reinterpreted(key, value):
    recipe = plan(); recipe[key] = value
    with pytest.raises(ValueError): subject.arm_identities(recipe)


def test_saved_state_original_recipe_and_receipt_binding_is_nonmutating():
    values = records(); before = deepcopy(values)
    assert subject.validate_saved_candidate(*values) is None
    assert values == before


@pytest.mark.parametrize("mutation", ["selected", "schema", "architecture", "authority", "authority_integer",
    "weight", "lineage", "training_receipt", "incomplete", "duplicate_run", "duplicate_prediction",
    "selected_report", "unavailable_report", "wrong_budget"])
def test_saved_state_wrong_provenance_or_authority_refused(mutation):
    identity, state, training, predictions, summary, lineage = records()
    if mutation == "selected": state["selected"] = True
    elif mutation == "schema": state["schema"] = "production/checkpoint"
    elif mutation == "architecture": state["architecture"] = "every_step"
    elif mutation == "authority": state["qualified"] = True
    elif mutation == "authority_integer": state["qualified"] = 0
    elif mutation == "weight": state["model_state"]["body.weight"][0][0] = 3.
    elif mutation == "lineage": state["lineage"]["teacher_checkpoint_sha256"] = "b"*64
    elif mutation == "training_receipt": training["new"] = True
    elif mutation == "incomplete": summary["complete"] = False
    elif mutation == "duplicate_run": summary["runs"][1] = deepcopy(summary["runs"][0])
    elif mutation == "duplicate_prediction": predictions.append(deepcopy(predictions[0]))
    elif mutation == "selected_report": training["last_complete_attempt_is_selected"] = True
    elif mutation == "unavailable_report": training["last_complete_attempt_state_available"] = False
    elif mutation == "wrong_budget": training["optimizer_steps"] = 339
    with pytest.raises(ValueError): subject.validate_saved_candidate(identity, state, training, predictions, summary, lineage)


@pytest.mark.parametrize("count", [1, 2, 4, 8, 32])
def test_roles_cover_every_reference_token_and_exact_top_level_boundaries(count):
    row, reference, codec, tokens = fixture(count)
    before = deepcopy((row, reference, codec))
    roles = subject.reference_token_roles(row, reference, codec)
    assert len(roles) == len(row["target_ids"])-1
    counts = Counter(roles)
    assert counts["continue"] == count-1 and counts["stop"] == counts["eos"] == 1
    assert all(counts[key] == count for key in subject.FACETS[:4])
    assert all(counts[key] == 2*count for key in subject.FACETS[4:])
    assert all(token == "," for token, role in zip(tokens, roles) if role == "continue")
    assert [token for token, role in zip(tokens, roles) if role == "stop"] == ["]"]
    assert roles[-1] == "eos" and (row, reference, codec) == before


def test_qualifier_commas_are_not_rule_continue_and_unicode_is_complete():
    row, reference, codec, tokens = fixture(2, unicode=True, qualifiers=True)
    roles = subject.reference_token_roles(row, reference, codec)
    counts = Counter(roles)
    assert counts["continue"] == 1 and counts["stop"] == 1
    assert counts["conditions"] == 4  # Two atoms and one empty-list pair.
    assert counts["exceptions"] == counts["temporal"] == 3
    assert counts["actor"] == 2
    assert len(roles) == len(tokens)+1


@pytest.mark.parametrize("mutation", ["id", "source", "count", "boolean_count", "empty_rules", "extra_rule_key",
    "non_string_atom", "qualifier_scalar", "unknown_vocabulary", "duplicate_vocabulary", "bad_specials",
    "target_truncated", "target_extra", "boolean_token", "wrong_token"])
def test_token_diagnostics_refuse_unbound_partial_or_malformed_targets(mutation):
    row, reference, codec, _ = fixture()
    if mutation == "id": reference["id"] = "other"
    elif mutation == "source": reference["source_text"] = "Different source"
    elif mutation == "count": reference["clause_count"] = 4
    elif mutation == "boolean_count": reference["clause_count"] = True
    elif mutation == "empty_rules": reference["target"]["rules"] = []
    elif mutation == "extra_rule_key": reference["target"]["rules"][0]["unknown"] = "unknown"
    elif mutation == "non_string_atom": reference["target"]["rules"][0]["actor"] = 3
    elif mutation == "qualifier_scalar": reference["target"]["rules"][0]["conditions"] = "missing list"
    elif mutation == "unknown_vocabulary": codec["target_vocabulary"].pop()
    elif mutation == "duplicate_vocabulary": codec["target_vocabulary"].append(codec["target_vocabulary"][-1])
    elif mutation == "bad_specials": codec["target_vocabulary"][0] = "BAD"
    elif mutation == "target_truncated": row["target_ids"].pop()
    elif mutation == "target_extra": row["target_ids"].append(2)
    elif mutation == "boolean_token": row["target_ids"][0] = True
    elif mutation == "wrong_token": row["target_ids"][5] = 3
    with pytest.raises(ValueError): subject.reference_token_roles(row, reference, codec)


def test_nll_aggregation_retains_empty_categories_and_all_denominators():
    bins = subject._bins()
    subject._aggregate(bins, ["actor", "actor", "eos", "structure"], [1., 3., 2., 8.])
    subject._finish(bins)
    assert bins["actor"] == dict(nll_sum=4., token_count=2, mean_nll=2.)
    assert bins["continue"] == dict(nll_sum=0., token_count=0, mean_nll=None)
    assert sum(r["token_count"] for r in bins.values()) == 4


@pytest.mark.parametrize("roles, values", [(["actor"], []), (["unknown"], [1.]), (["actor"], [float("nan")]),
    (["actor"], [float("inf")]), (["actor"], [-1.]), (["actor"], [True])])
def test_invalid_nll_categories_values_and_widths_rejected(roles, values):
    with pytest.raises(ValueError): subject._aggregate(subject._bins(), roles, values)


def nll(mean):
    bins = subject._bins(); subject._aggregate(bins, ["actor", "stop", "eos"], [mean]*3); subject._finish(bins)
    return dict(complete=True, by_role=bins, by_length={"1": deepcopy(bins)}, target_token_count=3, mean_nll=mean)


def test_counterfactual_gap_sign_denominators_and_empty_role_are_explicit():
    result = subject.nll_gap(nll(1.), nll(2.5))
    assert result["mean_counterfactual_minus_conditioned"] == 1.5
    assert result["by_role"]["actor"]["counterfactual_minus_conditioned"] == 1.5
    assert result["by_role"]["continue"]["counterfactual_minus_conditioned"] is None


@pytest.mark.parametrize("mutation", ["incomplete", "role_count", "missing_role", "missing_length", "total_count"])
def test_counterfactual_gaps_refuse_incomplete_or_changed_reference_support(mutation):
    other = nll(2.)
    if mutation == "incomplete": other["complete"] = False
    elif mutation == "role_count": other["by_role"]["actor"]["token_count"] = 2
    elif mutation == "missing_role": other["by_role"].pop("actor")
    elif mutation == "missing_length": other["by_length"].clear()
    elif mutation == "total_count": other["target_token_count"] = 4
    with pytest.raises(ValueError): subject.nll_gap(nll(1.), other)


def test_sequence_control_ignores_reconstruction_but_detects_token_and_termination_changes():
    left = [dict(id="a", token_ids=[3], generation_status="eos", reconstructed_input=[1.]),
        dict(id="b", token_ids=[4], generation_status="output_limit")]
    right = deepcopy(left); right[0]["reconstructed_input"] = [2.]
    assert subject.prediction_changes(left, right)["generated_sequence_or_status_changed"] == 0
    right[1]["generation_status"] = "eos"
    assert subject.prediction_changes(left, list(reversed(right)))["changed_ids"] == ["b"]
    right[0]["token_ids"] = [5]
    assert subject.prediction_changes(left, right)["generated_sequence_or_status_changed"] == 2


@pytest.mark.parametrize("mutation", ["duplicate", "unknown", "empty"])
def test_counterfactual_prediction_identity_failures_rejected(mutation):
    left = [dict(id="a", token_ids=[3], generation_status="eos")]; right = deepcopy(left)
    if mutation == "duplicate": right += deepcopy(right)
    elif mutation == "unknown": right[0]["id"] = "other"
    elif mutation == "empty": right = []
    with pytest.raises(ValueError): subject.prediction_changes(left, right)


def test_exact_replay_covers_original_predictions_numeric_metrics_and_fidelity_hash():
    evaluation = dict(report=dict(complete=True, metrics={"ce": .25}), predictions=[dict(id="x")],
        source_fidelity=dict(metrics={"ordered_exact": 0}, report_sha256="a"*64, rows=[{}]))
    training = dict(last_complete_attempt=dict(numerical={"ce": .25}, fidelity={
        "metrics": {"ordered_exact": 0}, "report_sha256": "a"*64}))
    subject.validate_replay(evaluation, training, deepcopy(evaluation["predictions"]))
    for key in ("predictions", "numerical", "fidelity", "complete"):
        candidate = deepcopy(evaluation)
        if key == "predictions": candidate["predictions"][0]["id"] = "different"
        elif key == "numerical": candidate["report"]["metrics"]["ce"] += 1e-12
        elif key == "fidelity": candidate["source_fidelity"]["report_sha256"] = "b"*64
        elif key == "complete": candidate["report"]["complete"] = False
        with pytest.raises(ValueError): subject.validate_replay(candidate, training, evaluation["predictions"])


@pytest.mark.parametrize("label", subject.LABELS)
def test_diagnostic_writes_are_immutable_and_cannot_overwrite_training_report(tmp_path, label):
    subject.save(tmp_path/"training.json", {"optimizer_steps": 340})
    original = (tmp_path/"training.json").read_bytes()
    result = subject.save_evaluation(tmp_path, label, {"complete": True})
    assert Path(result["path"]).name == "evaluation-"+label+".json"
    assert (tmp_path/"training.json").read_bytes() == original
    with pytest.raises(FileExistsError): subject.save_evaluation(tmp_path, label, {})


@pytest.mark.parametrize("label", [None, 1, "../training", "training.json", "other", ""])
def test_diagnostic_invalid_label_writes_nothing(tmp_path, label):
    with pytest.raises(ValueError): subject.save_evaluation(tmp_path, label, {})
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("content", ['{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}', '{"a":-Infinity}'])
def test_input_reader_rejects_ambiguous_json_and_nonfinite_values(tmp_path, content):
    path = tmp_path/"bad.json"; path.write_text(content)
    with pytest.raises(ValueError): subject.read(path)
