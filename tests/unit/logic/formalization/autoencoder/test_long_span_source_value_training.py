"""Synthetic source-value training controls; no corpus or qualification evidence."""
from copy import deepcopy
import hashlib
import math
import time

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core
from ipfs_datasets_py.logic.formalization.autoencoder import long_span_count_exposure_training as previous
from ipfs_datasets_py.logic.formalization.autoencoder import long_span_source_value_training as subject
from ipfs_datasets_py.logic.formalization.autoencoder import source_value_decoder_experiment as values
from .test_long_span_cardinality_training import setup, evaluated


@pytest.fixture(autouse=True)
def one_cpu():
    old = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


def prepared(feature_kind="projected_source", guidance=True):
    original, _, train, tune, options = setup()
    model = values.bind_source_value_model(original, codec=options["codec"],
        feature_kind=feature_kind, guidance=guidance)
    return model, original, train, tune, options


@pytest.mark.parametrize("strategy", ["reference_ce", "semantic_fields"])
def test_unwrapped_zero_aux_repeated_clipped_updates_match_previous_exactly(strategy):
    model, _, train, tune, options = setup()
    options["curriculum"] = [dict(name="repeated", training_ids=[row["id"] for row in train], epochs=12)]
    options["config"].update(epochs=12, max_optimizer_steps=12, max_grad_norm=.005,
        validation_interval=12, patience=0)
    before = core.tensor_digest(model)
    expected = previous.train(model, train, tune, strategy=strategy,
        cardinality_weight=.25, count_exposure="balanced_all", **options)
    result = subject.train(model, train, tune, strategy=strategy, source_value_weight=0.,
        cardinality_weight=.25, count_exposure="balanced_all", **options)
    assert core.tensor_digest(model) == before
    for role in ("state_dict", "last_complete_attempt_state_dict"):
        for name, tensor in expected[role].items():
            assert torch.equal(tensor, result[role][name]), (role, name)
    assert expected["predictions"] == result["predictions"]
    assert expected["last_complete_attempt_predictions"] == result["last_complete_attempt_predictions"]
    for name in ("optimizer_steps", "row_presentations", "valid_target_token_presentations",
        "selected_epoch", "stopped_reason", "committed_count_batch_ids_sha256", "gradient_norms"):
        assert expected["report"][name] == result["report"][name], name
    for old, new in zip(expected["report"]["history"], result["report"]["history"]):
        for name in ("mean_minibatch_ce", "mean_minibatch_weighted_ce", "mean_minibatch_count_ce",
            "accepted", "rejection_reasons", "selected_epoch"):
            assert old[name] == new[name], name
    assert result["report"]["source_value_head"] is None
    assert result["report"]["source_value_presentations"] == 0
    assert all(row["source_values"] is None for row in result["report"]["history"])


@pytest.mark.parametrize("feature_kind", ["projected_source", "inherited_conditioning"])
def test_auxiliary_updates_head_and_inherited_decoder_preserving_frozen_projection_and_inputs(feature_kind):
    model, _, train, tune, options = prepared(feature_kind)
    before = core.tensor_digest(model)
    modes = {name: module.training for name, module in model.named_modules()}
    initial = deepcopy((train, tune, options))
    result = subject.train(model, train, tune, cardinality_weight=.25,
        source_value_weight=.25, count_exposure="balanced_all", **options)
    assert core.tensor_digest(model) == before
    assert {name: module.training for name, module in model.named_modules()} == modes
    assert (train, tune, options) == initial
    last = result["last_complete_attempt_state_dict"]
    assert last is not None
    assert torch.count_nonzero(last["source_value_head.weight"]) > 0
    assert torch.count_nonzero(last["source_value_head.bias"]) > 0
    assert any(not torch.equal(last[name], parameter) for name, parameter in model.named_parameters()
        if name.startswith("body.") and parameter.requires_grad)
    for name, parameter in model.named_parameters():
        if not parameter.requires_grad:
            assert torch.equal(parameter, last[name])
            assert torch.equal(parameter, result["state_dict"][name])
    report = result["report"]
    assert report["source_value_presentations"] == 16
    assert report["row_presentations"] == report["count_training_row_presentations"] == 3
    assert report["optimizer_instance_count"] == 1
    assert report["stage_reports"][0]["optimizer_state_end"] == report["stage_reports"][1]["optimizer_state_start"]
    digest = hashlib.sha256()
    for update in report["committed_updates"]:
        digest.update(core._raw(update["decoder_row_ids"]))
    assert digest.hexdigest() == report["committed_decoder_batch_ids_sha256"]
    assert all(report[key] is False for key in subject.FALSE)
    assert not report["source_value_validation_rows_used_for_training"]
    assert not report["source_value_reference_documents_passed_to_model"]
    assert not report["source_value_metrics_used_for_selection"]
    train_ids = {row["id"] for row in train}
    for update in report["committed_updates"]:
        assert set(update["decoder_row_ids"]) <= train_ids
        assert set(update["count_row_ids"]) <= train_ids
        expected = update["weighted_token_ce"] + .25*update["count_ce"] + .25*update["source_value_ce"]
        expected += report["config"]["reconstruction_weight"]*update["raw_reconstruction_mse"]
        assert update["objective"] == pytest.approx(expected, abs=1e-6)
    assert sum(row["source_value_presentations"] for row in report["committed_updates"]) == 16
    assert sum(row["target_token_presentations"] for row in report["committed_updates"]) == report["valid_target_token_presentations"]


def test_zero_aux_guidance_off_creates_no_head_gradient_or_adam_state(monkeypatch):
    model, original, train, tune, options = prepared(guidance=False)
    copies, observed = [], []
    old_copy, old_step = subject.deepcopy, torch.optim.AdamW.step
    def copy(value):
        result = old_copy(value)
        if isinstance(value, torch.nn.Module):
            copies.append(result)
        return result
    def step(optimizer, *args, **kwargs):
        head = copies[0].source_value_head
        assert head.weight.grad is None and head.bias.grad is None
        result = old_step(optimizer, *args, **kwargs)
        assert head.weight not in optimizer.state and head.bias not in optimizer.state
        observed.append(1)
        return result
    monkeypatch.setattr(subject, "deepcopy", copy)
    monkeypatch.setattr(torch.optim.AdamW, "step", step)
    result = subject.train(model, train, tune, source_value_weight=0., cardinality_weight=.25,
        count_exposure="balanced_all", **options)
    assert len(observed) == result["report"]["optimizer_steps"] == 2
    assert not result["last_complete_attempt_state_dict"]["source_value_head.weight"].any()
    assert not result["last_complete_attempt_state_dict"]["source_value_head.bias"].any()


def test_zero_initial_head_reports_raw_present_metrics_absence_and_class_recall():
    model, _, _, tune, options = prepared()
    labels = values.reference_source_values(tune, options["validation_references"], options["codec"],
        validate_rule=options["validate_rule"])
    report = subject._source_value_evaluation(torch, model, tune, labels, options["input_transform"],
        core._config(options["config"]), options["codec"], time.monotonic()+10)
    assert report["present_values"] == 12 and report["correct"] == 0
    assert report["absent_slots_unscored"] == 52
    assert report["cross_entropy"] == pytest.approx(math.log(len(options["codec"]["target_vocabulary"])), abs=1e-6)
    assert sum(value["present_values"] for value in report["by_field"].values()) == 12
    assert sum(value["present_values"] for value in report["by_length"].values()) == 12
    for row in report["predictions"]:
        assert len(row["raw_logits"]) == 8
        assert row["predicted_token_ids"] == [[0]*4 for _ in range(8)]
        for slot in row["raw_logits"]:
            assert slot == [[0.]*len(options["codec"]["target_vocabulary"]) for _ in range(4)]
    for field in report["by_field"].values():
        assert field["macro_class_recall"] == 0.
        assert sum(cls["expected"] for cls in field["classes"].values()) == field["present_values"]
    assert not report["used_for_selection"] and not report["references_passed_to_model"]


def test_lower_auxiliary_loss_cannot_override_actual_generated_source_regression(monkeypatch):
    model, _, train, tune, options = prepared()
    rows = [evaluated(options, ce=2.), evaluated(options, ce=.1,
        mutate=lambda target: target["rules"][0].update(actor="agency"))]
    rows[0]["source_values"] = dict(cross_entropy=10., predictions=[])
    rows[1]["source_values"] = dict(cross_entropy=.001, predictions=[])
    sequence = iter(rows)
    monkeypatch.setattr(subject, "_evaluate", lambda *args: next(sequence))
    options["curriculum"] = options["curriculum"][:1]
    options["curriculum"][0]["training_ids"] = [row["id"] for row in train]
    result = subject.train(model, train, tune, source_value_weight=.25, cardinality_weight=.25, **options)
    assert result["report"]["selected_epoch"] == 0
    assert any("actor" in reason for reason in result["report"]["history"][0]["rejection_reasons"])
    assert result["report"]["last_complete_attempt_weights_sha256"] != result["report"]["selected_weights_sha256"]


@pytest.mark.parametrize("bad", [True, -1., float("nan"), float("inf"), 1.01, None, "0.25"])
def test_closed_auxiliary_weight_validation(bad):
    model, _, train, tune, options = prepared()
    with pytest.raises(ValueError, match="source-value weight"):
        subject.train(model, train, tune, source_value_weight=bad, **options)


def test_positive_auxiliary_requires_real_source_head():
    model, _, train, tune, options = setup()
    with pytest.raises(ValueError, match="requires source head"):
        subject.train(model, train, tune, source_value_weight=.25, **options)


@pytest.mark.parametrize("change", [
    lambda train, tune, opts: opts["training_references"][0]["target"]["rules"][0].update(actor="agency"),
    lambda train, tune, opts: tune[0].update(source_text=train[0]["source_text"]),
    lambda train, tune, opts: opts["training_references"][0].update(source_text="unbound source"),
    lambda train, tune, opts: train[0].update(input=[float("nan")]*8),
])
def test_reference_or_split_tampering_refuses_before_copy(change, monkeypatch):
    model, _, train, tune, options = prepared()
    change(train, tune, options)
    old_copy = subject.deepcopy
    def checked(value):
        assert not isinstance(value, torch.nn.Module)
        return old_copy(value)
    monkeypatch.setattr(subject, "deepcopy", checked)
    with pytest.raises(ValueError):
        subject.train(model, train, tune, source_value_weight=.25, **options)


def test_memory_bound_rejects_before_private_model_copy(monkeypatch):
    model, _, train, tune, options = prepared()
    options["config"].update(batch_size=128, max_memory_bytes=1048576)
    old_copy = subject.deepcopy
    def checked(value):
        assert not isinstance(value, torch.nn.Module)
        return old_copy(value)
    monkeypatch.setattr(subject, "deepcopy", checked)
    with pytest.raises(ValueError, match="tensor work"):
        subject.train(model, train, tune, source_value_weight=.25, **options)


def test_deadline_after_auxiliary_forward_does_not_commit_update_or_exposure(monkeypatch):
    model, _, train, tune, options = prepared()
    clock = [0.]
    monkeypatch.setattr(subject.time, "monotonic", lambda: clock[0])
    old = subject._source_value_logits
    def expire(*args):
        result = old(*args)
        if torch.is_grad_enabled():
            clock[0] = 21.
        return result
    monkeypatch.setattr(subject, "_source_value_logits", expire)
    result = subject.train(model, train, tune, source_value_weight=.25, cardinality_weight=.25,
        count_exposure="balanced_all", **options)
    report = result["report"]
    assert report["stopped_reason"] == "deadline"
    assert report["optimizer_steps"] == report["row_presentations"] == report["source_value_presentations"] == 0
    assert report["committed_updates"] == []
    assert report["selected_epoch"] == 0
    assert report["selected_weights_sha256"] == core.tensor_digest(model)


def test_incomplete_source_readout_rejects_whole_validation(monkeypatch):
    model, _, train, tune, options = prepared()
    calls, old = [], subject._source_value_evaluation
    def incomplete(*args):
        calls.append(1)
        return old(*args) if len(calls) == 1 else None
    monkeypatch.setattr(subject, "_source_value_evaluation", incomplete)
    result = subject.train(model, train, tune, source_value_weight=.25, **options)
    assert result["report"]["stopped_reason"] == "deadline_during_validation"
    assert result["report"]["selected_epoch"] == 0
    assert result["last_complete_attempt_state_dict"] is None
    assert result["report"]["last_complete_attempt_weights_sha256"] is None


def test_history_keeps_compact_diagnostics_and_final_reports_retain_raw_logits():
    model, _, train, tune, options = prepared()
    result = subject.train(model, train, tune, source_value_weight=.25, **options)
    for epoch in result["report"]["history"]:
        assert "predictions" not in epoch["source_values"]
        assert "by_field" in epoch["source_values"]
    for role in ("baseline", "selected", "last_complete_attempt"):
        assert len(result["report"][role]["source_values"]["predictions"]) == len(tune)


def test_caller_gradients_trainability_and_global_rng_are_unchanged():
    model, _, train, tune, options = prepared()
    for index, parameter in enumerate(model.parameters()):
        if index % 2:
            parameter.grad = torch.full_like(parameter, .125)
    before = {name: (parameter.requires_grad, None if parameter.grad is None else parameter.grad.clone())
        for name, parameter in model.named_parameters()}
    random_state = torch.get_rng_state().clone()
    subject.train(model, train, tune, source_value_weight=.25, **options)
    assert torch.equal(torch.get_rng_state(), random_state)
    for name, parameter in model.named_parameters():
        assert parameter.requires_grad == before[name][0]
        if before[name][1] is None:
            assert parameter.grad is None
        else:
            assert torch.equal(parameter.grad, before[name][1])


@pytest.mark.parametrize("malformed", ["shape", "nan", "dtype"])
def test_auxiliary_logits_must_match_finite_cpu_geometry(malformed):
    class Broken:
        def source_value_logits(self, projected):
            data = torch.zeros(len(projected), 8, 4, 16)
            if malformed == "shape":
                return data[:, :7]
            if malformed == "nan":
                data[0, 0, 0, 0] = float("nan")
                return data
            return data.double()
    with pytest.raises(ValueError, match="source-value logits"):
        subject._source_value_logits(torch, Broken(), torch.zeros(2, 8), 16)
