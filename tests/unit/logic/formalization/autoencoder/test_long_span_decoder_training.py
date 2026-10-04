"""Tiny synthetic CPU controls, not corpus, teacher, native, or proof evidence."""
from copy import deepcopy
import json
import time

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_source_fidelity as fidelity
from ipfs_datasets_py.logic.formalization.autoencoder import long_span_decoder_training as subject
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as numerical


@pytest.fixture(autouse=True)
def single_cpu():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def validate_rule(document):
    """A deliberately synthetic shape validator with no native authority."""
    rules = document.get("rules") if type(document) is dict else None
    valid = type(rules) is list and len(rules) == 1
    if valid:
        rule = rules[0]
        valid = (type(rule) is dict and set(rule) == set(fidelity.FACETS)
            and all(type(rule[key]) is str for key in fidelity.FACETS[:4])
            and rule["modality"] in ("O", "P", "F")
            and all(type(rule[key]) is list and all(type(value) is str for value in rule[key])
                for key in fidelity.FACETS[4:]))
    return {"valid": valid, "scope": "synthetic shape only"}


def setup():
    rule = dict(actor="officer", action="retain", object="file", modality="O",
                conditions=[], exceptions=[], temporal=[])
    other = dict(rule, actor="agency", action="disclose", modality="F", conditions=["requested"])
    targets = [{"rules": [rule]}, {"rules": [rule, other]}]
    vocabulary = ["<pad>", "<bos>", "<eos>"] + sorted({token for target in targets
        for token, _ in subject._tokens(target, semantic=False)})
    codec = dict(schema="synthetic-legal-multirule-test/v1", target_vocabulary=vocabulary)
    model = numerical._model({"dimension": 8}, codec,
        dict(seed=3517, projection_width=2, hidden_size=8, token_embedding_dim=8))
    model = core.bind_model(model, dimension=8)
    for name, parameter in model.named_parameters():
        if "projection_down" in name or "projection_up" in name:
            parameter.requires_grad_(False)

    def rows(split):
        records, references = [], []
        for index, target in enumerate(targets):
            source = f"{split} synthetic authored paragraph {index}"
            identity = f"{split}-{index}"
            ids = [1] + [vocabulary.index(token) for token, _ in subject._tokens(target, semantic=False)] + [2]
            records.append(dict(id=identity, source_text=source, input=[.1+index*.1]+[0.]*7,
                                target_ids=ids))
            references.append(dict(id=identity, source_text=source,
                                   clause_count=len(target["rules"]), target=deepcopy(target)))
        return records, references

    train, train_refs = rows("train")
    tune, tune_refs = rows("validation")
    options = dict(training_references=train_refs, validation_references=tune_refs,
        codec=codec, input_transform=dict(mode="none", origin="training_only", mean=[0.]*8, scale=1.),
        lineage=dict(teacher_checkpoint_sha256="a"*64, teacher_codec_sha256=core.digest(codec),
            input_provenance_sha256="b"*64, domain="legal_ir", teacher_lineage="synthetic-only",
            student_lineage="synthetic-new-source-trainer", teacher_output_limit=128,
            student_role="learned_formula_sidecar"),
        validate_rule=validate_rule, validator_id="synthetic-shape-only/v1",
        curriculum=[dict(name="all", training_ids=[row["id"] for row in train], epochs=1)],
        config=dict(epochs=1, max_optimizer_steps=4, batch_size=2, max_target_tokens=128,
                    max_seconds=20., validation_interval=1, learning_rate=.001))
    return model, train, tune, options


def generated(references, codec, *, mutate=None):
    result = []
    for reference in references:
        target = deepcopy(reference["target"])
        if mutate:
            mutate(target)
        tokens = [codec["target_vocabulary"].index(token)
                  for token, _ in subject._tokens(target, semantic=False)]
        result.append(dict(id=reference["id"], token_ids=tokens,
                           generation_status="eos", eos_reached=True))
    return result


def evaluation(options, *, ce=2., mse=.001, mutate=None):
    predictions = generated(options["validation_references"], options["codec"], mutate=mutate)
    score = fidelity.score_predictions(options["validation_references"], predictions,
        codec=options["codec"], validate_rule=validate_rule, output_limit=128,
        validator_id=options["validator_id"])
    return dict(numerical=dict(token_cross_entropy=ce, reconstructed_input_mse=mse, complete=True),
                fidelity=score, predictions=predictions)


def test_full_tokens_all_scalar_types_and_empty_absence_have_positive_weight():
    value = {"strings": ["x", "escaped\nvalue"], "true": True, "false": False,
             "none": None, "integer": 20, "float": 1.25, "empty": [], "nested": {"k": "v"}}
    weighted = subject._tokens(value, semantic=True)
    plain = subject._tokens(value, semantic=False)
    assert "".join(token for token, _ in weighted) == subject._json(value)
    assert [token for token, _ in weighted] == [token for token, _ in plain]
    assert all(weight == 1 for _, weight in plain)
    for token in ('"x"', '"escaped\\nvalue"', "true", "false", "null", "20", "1.25", '"v"'):
        assert (token, 4.) in weighted
    for key in value:
        assert (json.dumps(key), .25) in weighted
    start = weighted.index(('"empty"', .25))
    assert weighted[start+2:start+4] == [("[", 1.), ("]", 1.)]
    assert all(weight > 0 for _, weight in weighted)


@pytest.mark.parametrize("strategy", ["reference_ce", "semantic_fields"])
def test_reference_weights_preserve_every_content_token_eos_and_qualifier(strategy):
    _, train, _, options = setup()
    weights = subject.reference_weights(train, options["training_references"], options["codec"],
        strategy=strategy, validate_rule=validate_rule)
    for row, reference in zip(train, options["training_references"]):
        values = weights[row["id"]]
        assert len(values) == len(row["target_ids"])
        assert values[0] == 0 and values[-1] == 1 and all(value > 0 for value in values[1:])
        expected = subject._tokens(reference["target"], semantic=strategy == "semantic_fields")
        assert values[1:-1] == [weight for _, weight in expected]
    assert max(weights[train[0]["id"]]) == (1 if strategy == "reference_ce" else 4)


@pytest.mark.parametrize("strategy", ["reference_ce", "semantic_fields"])
def test_actual_update_full_mask_loss_matches_v1_ce_and_manual_weighting(strategy):
    model, train, tune, options = setup()
    data, labels = core._batch(torch, train, options["input_transform"])
    _, logits = core._logits(torch, model, data, labels[:, :-1], len(options["codec"]["target_vocabulary"]))
    _, v1_ce, _ = core._loss(torch, logits, None, labels[:, 1:], 0.)
    weights = subject.reference_weights(train, options["training_references"], options["codec"],
        strategy=strategy, validate_rule=validate_rule)
    padded = torch.tensor([weights[row["id"]]+[0.]*(labels.shape[1]-len(weights[row["id"]]))
                          for row in train])[:, 1:]
    per_token = torch.nn.functional.cross_entropy(logits.flatten(0, 1), labels[:, 1:].flatten(),
        reduction="none", ignore_index=0).reshape_as(padded)
    expected_weighted = (per_token*padded).sum()/padded.sum()
    assert (padded[labels[:, 1:] == 0] == 0).all()
    assert (padded[labels[:, 1:] == 2] == 1).all()
    result = subject.train(model, train, tune, strategy=strategy, **options)
    epoch = result["report"]["history"][0]
    assert epoch["mean_minibatch_ce"] == pytest.approx(v1_ce.item(), abs=5e-7)
    assert epoch["mean_minibatch_weighted_ce"] == pytest.approx(expected_weighted.item(), abs=5e-7)
    assert result["report"]["valid_target_token_presentations"] == sum(len(row["target_ids"])-1 for row in train)
    assert result["report"]["optimizer_steps"] == 1


def test_real_training_keeps_caller_model_inputs_modes_and_projection_immutable():
    model, train, tune, options = setup()
    model.eval()
    model.body.decoder.train()
    before = core.tensor_digest(model)
    modes = {name: module.training for name, module in model.named_modules()}
    frozen = {name: parameter.detach().clone() for name, parameter in model.named_parameters()
              if not parameter.requires_grad}
    inputs = deepcopy((train, tune, options))
    result = subject.train(model, train, tune, **options)
    report = result["report"]
    assert core.tensor_digest(model) == before == report["initial_weights_sha256"]
    assert modes == {name: module.training for name, module in model.named_modules()}
    assert (train, tune, options) == inputs
    assert all(parameter.grad is None for parameter in model.parameters())
    assert frozen and set(report["frozen_parameter_names"]) == set(frozen)
    assert all(torch.equal(result["state_dict"][name], value) for name, value in frozen.items())
    assert all(not value.requires_grad for value in result["state_dict"].values())
    assert report["frozen_parameters_verified"]
    assert report["generation_temperature"] == 0 and report["full_targets_truncated"] is False
    assert report["scope"] == "exposed_development_only"
    assert all(report[name] is False for name in subject.FALSE)


def test_single_adam_state_continues_across_cumulative_stages():
    model, train, tune, options = setup()
    options["curriculum"] = [dict(name="short", training_ids=[train[0]["id"]], epochs=1),
        dict(name="cumulative", training_ids=[row["id"] for row in train], epochs=1)]
    result = subject.train(model, train, tune, **options)
    report = result["report"]
    first, second = report["stage_reports"]
    assert first["optimizer_step_start"] == 0 and first["optimizer_step_end"] == 1
    assert second["optimizer_step_start"] == 1 and second["optimizer_step_end"] == 2
    assert first["optimizer_state_end"] == second["optimizer_state_start"]
    assert first["optimizer_state_end"] != first["optimizer_state_start"]
    assert second["optimizer_state_end"] != second["optimizer_state_start"]
    assert all(stage["status"] == "complete" for stage in report["stage_reports"])
    assert report["optimizer_instance_count"] == 1 and not report["optimizer_reinitialized_between_stages"]
    assert report["row_presentations"] == 3
    assert report["valid_target_token_presentations"] == 2*(len(train[0]["target_ids"])-1)+len(train[1]["target_ids"])-1


@pytest.mark.parametrize("mutation,reason", [
    (lambda target: target["rules"][0].update(modality="F"), "modality"),
    (lambda target: target["rules"][0].update(actor="agency"), "actor"),
    (lambda target: target["rules"].reverse(), "ordered_exact"),
    (lambda target: target["rules"].pop() if len(target["rules"]) > 1 else None, "whole_rules_missing"),
])
def test_lower_loss_cannot_select_source_field_order_or_clause_regression(monkeypatch, mutation, reason):
    model, train, tune, options = setup()
    before = core.tensor_digest(model)
    results = iter([evaluation(options, ce=2.), evaluation(options, ce=.1, mutate=mutation)])
    monkeypatch.setattr(subject, "_evaluate", lambda *args: next(results))
    result = subject.train(model, train, tune, **options)
    report = result["report"]
    assert report["optimizer_steps"] == 1 and report["selected_epoch"] == 0
    assert report["selected_weights_sha256"] == before
    assert not report["last_complete_attempt_is_selected"]
    assert report["last_complete_attempt_state_available"]
    assert report["last_complete_attempt"]["numerical"]["token_cross_entropy"] == .1
    assert any(reason in value for value in report["history"][0]["rejection_reasons"])
    assert result["predictions"] != result["last_complete_attempt_predictions"]


def test_mse_regression_blocks_otherwise_improving_loss(monkeypatch):
    model, train, tune, options = setup()
    results = iter([evaluation(options, ce=2., mse=.001), evaluation(options, ce=.1, mse=1.)])
    monkeypatch.setattr(subject, "_evaluate", lambda *args: next(results))
    report = subject.train(model, train, tune, **options)["report"]
    assert report["selected_epoch"] == 0
    assert "initial_reconstruction_regression" in report["history"][0]["rejection_reasons"]


def test_equal_fidelity_lower_ce_selects_actual_candidate_and_retains_no_authority(monkeypatch):
    model, train, tune, options = setup()
    results = iter([evaluation(options, ce=2.), evaluation(options, ce=1.)])
    monkeypatch.setattr(subject, "_evaluate", lambda *args: next(results))
    result = subject.train(model, train, tune, **options)
    report = result["report"]
    assert report["selected_epoch"] == 1 and report["last_complete_attempt_is_selected"]
    assert report["selected_weights_sha256"] != core.tensor_digest(model)
    assert all(report[name] is False for name in subject.FALSE)


def test_incomplete_validation_cannot_select_or_claim_current_weights_evaluated(monkeypatch):
    model, train, tune, options = setup()
    original = subject._evaluate
    calls = []
    def bounded(*args):
        calls.append(1)
        return original(*args) if len(calls) == 1 else None
    monkeypatch.setattr(subject, "_evaluate", bounded)
    result = subject.train(model, train, tune, **options)
    report = result["report"]
    assert len(calls) == 2 and report["optimizer_steps"] == 1
    assert report["selected_epoch"] == 0 and report["stopped_reason"] == "deadline_during_validation"
    assert report["history"][0]["rejection_reasons"] == ["incomplete_validation"]
    assert report["selected_weights_sha256"] == core.tensor_digest(model)
    assert report["last_complete_attempt_state_available"] is False
    assert result["last_complete_attempt_state_dict"] is None


def test_incomplete_baseline_is_unvalidated_initial_state_with_no_training(monkeypatch):
    model, train, tune, options = setup()
    monkeypatch.setattr(subject, "_evaluate", lambda *args: None)
    result = subject.train(model, train, tune, **options)
    report = result["report"]
    assert report["optimizer_steps"] == 0 and report["selected_epoch"] is None
    assert report["baseline"] is None and report["selected"] is None
    assert report["exported_state_role"] == "unvalidated_initial_state"
    assert report["stopped_reason"] == "deadline_before_complete_baseline"
    assert result["predictions"] == [] and result["last_complete_attempt_state_dict"] is None


def test_post_evaluation_deadline_rejects_selection_commit(monkeypatch):
    model, train, tune, options = setup()
    clock = [0.]
    monkeypatch.setattr(subject.time, "monotonic", lambda: clock[0])
    calls = []
    def bounded(*args):
        calls.append(1)
        value = evaluation(options, ce=2. if len(calls) == 1 else .1)
        if len(calls) == 2:
            clock[0] = 21.
        return value
    monkeypatch.setattr(subject, "_evaluate", bounded)
    report = subject.train(model, train, tune, **options)["report"]
    assert report["selected_epoch"] == 0 and report["optimizer_steps"] == 1
    assert report["stopped_reason"] == "deadline_before_selection_commit"
    assert "deadline_before_selection_commit" in report["history"][0]["rejection_reasons"]


def test_generation_depends_on_input_not_reference_target_or_source_string():
    model, _, tune, options = setup()
    alternate = deepcopy(tune)
    alternate_refs = deepcopy(options["validation_references"])
    for row, reference in zip(alternate, alternate_refs):
        row["target_ids"] = list(reversed(row["target_ids"][1:-1]))
        row["target_ids"] = [1]+row["target_ids"]+[2]
        row["source_text"] = "different evaluation provenance " + row["id"]
        reference["source_text"] = row["source_text"]
    config = core._config(options["config"])
    first = subject._evaluate(torch, model, tune, options["validation_references"],
        options["input_transform"], config, options["codec"], time.monotonic()+20., validate_rule, options["validator_id"])
    second = subject._evaluate(torch, model, alternate, alternate_refs,
        options["input_transform"], config, options["codec"], time.monotonic()+20., validate_rule, options["validator_id"])
    for left, right in zip(first["predictions"], second["predictions"]):
        assert left["token_ids"] == right["token_ids"]
        assert left["generation_status"] == right["generation_status"]
        assert left["reconstructed_input"] == right["reconstructed_input"]
    assert not first["fidelity"]["source_semantics_verified"]


@pytest.mark.parametrize("mutation,reason", [
    (lambda t, v, o: o.update(strategy="skip_structure"), "unknown source loss strategy"),
    (lambda t, v, o: o.update(config=[]), "configuration must be a mapping"),
    (lambda t, v, o: o["config"].update(alpha=.1), "unqualified teacher"),
    (lambda t, v, o: o["lineage"].update(domain="intent_ir"), "Legal rule-facet"),
    (lambda t, v, o: o["training_references"][0].update(id="foreign"), "reference IDs"),
    (lambda t, v, o: o["training_references"][0].update(source_text="wrong source"), "reference source"),
    (lambda t, v, o: o["training_references"][0]["target"]["rules"][0].update(actor="agency"), "numerical tokens differ"),
    (lambda t, v, o: o["training_references"][0].update(clause_count=2), "complete bounded Legal"),
    (lambda t, v, o: o["training_references"].pop(), "complete reference inventory"),
    (lambda t, v, o: o.update(validate_rule=lambda target: {"valid": False}), "failed supplied syntax"),
    (lambda t, v, o: t[0]["target_ids"].insert(2, 0), "complete BOS"),
    (lambda t, v, o: o["config"].update(max_target_tokens=32), "without truncation"),
    (lambda t, v, o: v[0].update(source_text=t[0]["source_text"].upper()), "training/validation overlap"),
])
def test_bad_training_inputs_fail_closed(mutation, reason):
    model, train, tune, options = setup()
    mutation(train, tune, options)
    with pytest.raises(ValueError, match=reason):
        subject.train(model, train, tune, **options)


def test_tensor_memory_preflight_precedes_model_copy(monkeypatch):
    model, train, tune, options = setup()
    options["config"]["max_memory_bytes"] = 1024*1024
    options["config"]["batch_size"] = 128
    original = subject.deepcopy
    def checked(value):
        assert not isinstance(value, torch.nn.Module), "model was copied before memory refusal"
        return original(value)
    monkeypatch.setattr(subject, "deepcopy", checked)
    with pytest.raises(ValueError, match="trial tensor work exceeds budget"):
        subject.train(model, train, tune, **options)


def test_optimizer_limit_retains_complete_baseline_and_partial_stage():
    model, train, tune, options = setup()
    options["config"].update(batch_size=1, max_optimizer_steps=1)
    result = subject.train(model, train, tune, **options)
    report = result["report"]
    assert report["optimizer_steps"] == 1 and report["stopped_reason"] == "optimizer_step_limit"
    assert report["selected_epoch"] == 0 and report["stage_reports"][0]["status"] == "partial"
    assert report["history"][0]["complete_epoch"] is False
    assert result["last_complete_attempt_state_dict"] is None
