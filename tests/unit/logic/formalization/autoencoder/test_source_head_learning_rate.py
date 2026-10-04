"""Optional head optimizer rates preserve decoder objectives and fidelity gates."""
from copy import deepcopy

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core
from ipfs_datasets_py.logic.formalization.autoencoder import long_span_source_value_training as subject
from .test_ordered_clause_recurrent_training_runner import real_fixture


@pytest.fixture(autouse=True)
def one_cpu():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def fit(model, train, tune, options, contexts, **kwargs):
    return subject.train(model, train, tune, source_contexts=contexts, source_value_weight=.25,
        cardinality_weight=.25, count_exposure="balanced_all", action_contrastive_weight=.05,
        **options, **kwargs)


def longer(options, train, epochs=4):
    options = deepcopy(options)
    options["curriculum"] = [dict(name="first", training_ids=[row["id"] for row in train], epochs=epochs//2),
                             dict(name="second", training_ids=[row["id"] for row in train], epochs=epochs-epochs//2)]
    options["config"].update(epochs=epochs, max_optimizer_steps=epochs, validation_interval=epochs,
        patience=0, max_grad_norm=.001)
    return options


@pytest.mark.parametrize("explicit", [False, True])
def test_default_single_group_and_reports_stay_exact(monkeypatch, explicit):
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    options = longer(options, train)
    baseline = fit(model, train, tune, options, contexts)
    monkeypatch.setattr(subject, "_non_action_optimizer_groups", lambda *a: pytest.fail("default group split executed"))
    monkeypatch.setattr(subject, "_group_learning_rates", lambda *a: pytest.fail("default group telemetry executed"))
    original = torch.optim.AdamW
    seen = []
    def optimizer(parameters, **kwargs):
        assert all(isinstance(p, torch.nn.Parameter) for p in parameters)
        assert kwargs == dict(lr=options["config"].get("learning_rate", .001),
                              weight_decay=options["config"].get("weight_decay", .01), foreach=False)
        result = original(parameters, **kwargs)
        seen.append(result)
        return result
    monkeypatch.setattr(torch.optim, "AdamW", optimizer)
    actual = fit(model, train, tune, options, contexts,
                 **({"non_action_learning_rate_multiplier": 1.0} if explicit else {}))
    assert len(seen) == 1 and len(seen[0].param_groups) == 1
    for role in ("state_dict", "last_complete_attempt_state_dict"):
        assert all(torch.equal(value, actual[role][name]) for name, value in baseline[role].items())
    left, right = deepcopy(baseline["report"]), deepcopy(actual["report"])
    left.pop("elapsed_seconds"); right.pop("elapsed_seconds")
    assert left == right
    assert not any(key.startswith(("non_action_learning_rate", "optimizer_parameter_groups", "optimizer_group_"))
                   for key in actual["report"])
    assert not any("optimizer_group_learning_rates" in item for item in actual["report"]["committed_updates"])


@pytest.mark.parametrize("kind", ["factorized", "recurrent"])
def test_opt_in_exact_inventory_one_optimizer_original_clip_order_and_moments(monkeypatch, kind):
    model, donor, train, tune, options, contexts = real_fixture(monkeypatch)
    model = donor if kind == "factorized" else model
    options = longer(options, train)
    original_model = core.tensor_digest(model)
    modes = {name: module.training for name, module in model.named_modules()}
    inputs = deepcopy((train, tune, options, contexts))
    rng = torch.get_rng_state().clone()
    original_clip = torch.nn.utils.clip_grad_norm_
    original_groups = subject._non_action_optimizer_groups
    captured, clips = [], []
    def groups(working, trainable, specification, options, multiplier):
        result = original_groups(working, trainable, specification, options, multiplier)
        captured.append((working, [id(p) for p in trainable], result))
        return result
    def clip(parameters, *args, **kwargs):
        parameters = list(parameters)
        clips.append([id(p) for p in parameters])
        return original_clip(parameters, *args, **kwargs)
    monkeypatch.setattr(subject, "_non_action_optimizer_groups", groups)
    monkeypatch.setattr(torch.nn.utils, "clip_grad_norm_", clip)
    result = fit(model, train, tune, options, contexts, non_action_learning_rate_multiplier=10.)
    report = result["report"]
    assert len(captured) == 1 and len(clips) == 4
    assert all(order == captured[0][1] for order in clips)
    groups = report["optimizer_parameter_groups"]
    assert [group["name"] for group in groups] == ["base", "non_action_head"]
    expected = {"non_action_head."+suffix for suffix in (
        "source_projection.weight", "source_projection.bias", "field_readout.weight", "field_readout.bias")}
    assert set(groups[1]["parameter_names"]) == expected
    assert not (set(groups[0]["parameter_names"]) & expected)
    assert set(groups[0]["parameter_names"]) | expected == {name for name,p in model.named_parameters() if p.requires_grad}
    assert groups[0]["initial_learning_rate"] == .001 and groups[1]["initial_learning_rate"] == .01
    assert groups[1]["minimum_learning_rate"] == pytest.approx(10*groups[0]["minimum_learning_rate"])
    assert all(g["weight_decay"] == .01 for g in groups)
    assert report["optimizer_scheduler_epsilon"] == 0.
    assert report["optimizer_global_clip_parameter_order"] == "original_model_trainable_order"
    assert "per_step_shrinkage_is_learning_rate_times_weight_decay" in report["optimizer_weight_decay_policy"]
    assert report["optimizer_instance_count"] == 1 and not report["optimizer_reinitialized_between_stages"]
    stages = report["stage_reports"]
    assert stages[0]["optimizer_state_end"] == stages[1]["optimizer_state_start"]
    assert stages[0]["optimizer_group_learning_rates_end"] == stages[1]["optimizer_group_learning_rates_start"]
    assert core.tensor_digest(model) == original_model and torch.equal(rng, torch.get_rng_state())
    assert modes == {name: module.training for name,module in model.named_modules()}
    assert inputs == (train, tune, options, contexts)
    for name in report["frozen_parameter_names"]:
        assert torch.equal(model.state_dict()[name], result["last_complete_attempt_state_dict"][name])
    for row in report["committed_updates"]:
        assert row["learning_rate"] == row["optimizer_group_learning_rates"]["base"]
        assert row["optimizer_group_learning_rates"]["non_action_head"] == pytest.approx(10*row["learning_rate"])
        objective = row["weighted_token_ce"] + report["config"]["reconstruction_weight"]*row["raw_reconstruction_mse"]
        objective += .25*row["count_ce"]+.25*row["source_value_ce"]+.05*row["action_contrastive"]["loss"]
        assert row["objective"] == pytest.approx(objective, abs=1e-6)
    assert report["selection"] == "per_length_nonregression_then_fidelity_progress_then_reference_ce"
    assert not report["non_action_learning_rate_used_for_selection"]
    assert report["generation_temperature"] == 0 and report["encoder_context_changed"] is False
    assert all(report[key] is False for key in subject.FALSE)


def test_first_step_changes_only_requested_group_with_identical_gradients(monkeypatch):
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    options = deepcopy(options)
    options["config"].update(max_optimizer_steps=1, validation_interval=1)
    options["curriculum"][0]["epochs"] = 1
    reference = fit(model, train, tune, options, contexts)
    candidate = fit(model, train, tune, options, contexts, non_action_learning_rate_multiplier=10.)
    a, b = reference["last_complete_attempt_state_dict"], candidate["last_complete_attempt_state_dict"]
    assert a is not None and b is not None
    assert any(not torch.equal(a[name], b[name]) for name in a if name.startswith("non_action_head."))
    assert all(torch.equal(a[name], b[name]) for name in a if not name.startswith("non_action_head."))
    left, right = reference["report"]["committed_updates"][0], candidate["report"]["committed_updates"][0]
    assert {k:v for k,v in right.items() if k != "optimizer_group_learning_rates"} == left


@pytest.mark.parametrize("rate", [.001, 1e-12])
def test_plateau_scheduler_preserves_ratio_through_both_minima(monkeypatch, rate):
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    options = longer(options, train, epochs=12)
    options["config"].update(learning_rate=rate, plateau_patience=1, plateau_factor=.5,
        min_learning_rate_ratio=.125, validation_interval=1)
    original = torch.optim.lr_scheduler.ReduceLROnPlateau
    schedulers = []
    def scheduler(optimizer, **kwargs):
        assert kwargs["eps"] == 0. and kwargs["min_lr"] == pytest.approx([rate*.125,rate*10*.125])
        result = original(optimizer, **kwargs)
        ordinary_step = result.step
        result.step = lambda actual_metric: ordinary_step(1.)
        schedulers.append(result)
        return result
    monkeypatch.setattr(torch.optim.lr_scheduler, "ReduceLROnPlateau", scheduler)
    result = fit(model, train, tune, options, contexts, non_action_learning_rate_multiplier=10.)
    report = result["report"]
    assert len(schedulers) == 1
    for epoch in report["history"]:
        rates = epoch["optimizer_group_learning_rates"]
        assert rates["non_action_head"] == pytest.approx(rates["base"]*10, rel=1e-14, abs=0)
        assert epoch["learning_rate"] == rates["base"]
    assert report["optimizer_parameter_groups"][0]["final_learning_rate"] == rate*.125
    assert report["optimizer_parameter_groups"][1]["final_learning_rate"] == rate*10*.125
    # Commit telemetry precedes its epoch's scheduler update.
    assert report["committed_updates"][2]["optimizer_group_learning_rates"]["base"] == rate
    assert report["history"][2]["optimizer_group_learning_rates"]["base"] == rate*.5


@pytest.mark.parametrize("bad", [None, True, False, 0, .99, 10.01, float("nan"), float("inf"), "10", 10**1000])
def test_invalid_multiplier_rejected_before_model_copy(monkeypatch, bad):
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    monkeypatch.setattr(subject, "deepcopy", lambda *a: pytest.fail("copied before multiplier validation"))
    with pytest.raises(ValueError, match="multiplier must"):
        fit(model, train, tune, options, contexts, non_action_learning_rate_multiplier=bad)


def test_effective_rate_cap_rejected_before_model_copy(monkeypatch):
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    options["config"]["learning_rate"] = .02
    monkeypatch.setattr(subject, "deepcopy", lambda *a: pytest.fail("copied before effective rate check"))
    with pytest.raises(ValueError, match="effective rate"):
        fit(model, train, tune, options, contexts, non_action_learning_rate_multiplier=10.)


def test_underflowed_scheduler_floor_rejected_before_model_copy(monkeypatch):
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    options["config"].update(learning_rate=1e-323, min_learning_rate_ratio=.05)
    monkeypatch.setattr(subject, "deepcopy", lambda *a: pytest.fail("copied before floor validation"))
    with pytest.raises(ValueError, match="positive representable base minimum"):
        fit(model, train, tune, options, contexts, non_action_learning_rate_multiplier=10.)


@pytest.mark.parametrize("dimension", [8, 384, 768])
def test_same_head_parameter_scope_at_each_supported_dimension(dimension):
    from .test_action_factorized_clause_decoder_experiment import fixture
    model, _, codec, _ = fixture(dimension)
    specification = subject._head_specification(model, codec, .25)
    trainable = [p for p in model.parameters() if p.requires_grad]
    groups, inventory = subject._non_action_optimizer_groups(model, trainable, specification, core._config({}), 10.)
    assert len(groups) == 2 and inventory[1]["parameter_count"] == (dimension+1)*64 + 3*len(codec["target_vocabulary"])*65
    assert set(inventory[1]["parameter_names"]) == {"non_action_head."+suffix for suffix in (
        "source_projection.weight", "source_projection.bias", "field_readout.weight", "field_readout.bias")}
    assert {id(p) for p in trainable} == {id(p) for group in groups for p in group["params"]}


def test_unsupported_checked_architecture_cannot_receive_head_multiplier(monkeypatch):
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    monkeypatch.setattr(subject, "_head_specification", lambda *a: dict(schema="clause-source-decoder-development/v1"))
    monkeypatch.setattr(subject, "deepcopy", lambda *a: pytest.fail("copied unsupported architecture"))
    with pytest.raises(ValueError, match="checked factorized or recurrent"):
        fit(model, train, tune, options, contexts, non_action_learning_rate_multiplier=10.)


@pytest.mark.parametrize("mutation", ["extra", "missing", "duplicate_trainable", "reordered_trainable"])
def test_private_group_builder_fails_closed_on_inventory_change(monkeypatch, mutation):
    model, _, _, _, options, _ = real_fixture(monkeypatch)
    specification = subject._head_specification(model, options["codec"], .25)
    trainable = [p for p in model.parameters() if p.requires_grad]
    if mutation == "extra":
        model.non_action_head.register_parameter("extra", torch.nn.Parameter(torch.ones(1)))
    elif mutation == "missing":
        model.non_action_head.field_readout.bias.requires_grad_(False)
    elif mutation == "duplicate_trainable":
        trainable.append(trainable[0])
    else:
        trainable.reverse()
    with pytest.raises(ValueError):
        subject._non_action_optimizer_groups(model, trainable, specification, core._config(options["config"]), 10.)


def test_deadline_after_backward_clears_private_gradients_before_any_optimizer_step(monkeypatch):
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    before = core.tensor_digest(model)
    clock = [0.]
    captured = []
    original_group = subject._non_action_optimizer_groups
    original_backward = torch.Tensor.backward
    def groups(*args):
        captured.append(args[0])
        return original_group(*args)
    def backward(self, *args, **kwargs):
        result = original_backward(self, *args, **kwargs)
        clock[0] = 1000.
        return result
    monkeypatch.setattr(subject, "_non_action_optimizer_groups", groups)
    monkeypatch.setattr(torch.Tensor, "backward", backward)
    monkeypatch.setattr(subject.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(torch.optim.AdamW, "step", lambda *a, **k: pytest.fail("expired update committed"))
    result = fit(model, train, tune, options, contexts, non_action_learning_rate_multiplier=10.)
    report = result["report"]
    assert report["optimizer_steps"] == 0 and report["stopped_reason"] == "deadline"
    assert not report["committed_updates"]
    assert all(p.grad is None for p in captured[0].parameters())
    assert core.tensor_digest(model) == before
    assert all(group["final_learning_rate"] == group["initial_learning_rate"]
               for group in report["optimizer_parameter_groups"])


def test_unchanged_fidelity_gate_rejects_better_loss_when_semantics_regress(monkeypatch):
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    original = subject.fidelity.compare_nonregression
    calls = []
    def reject(*args, **kwargs):
        answer = original(*args, **kwargs)
        calls.append(answer)
        return dict(answer, accepted=False, reasons=["synthetic_source_fidelity_regression"])
    monkeypatch.setattr(subject.fidelity, "compare_nonregression", reject)
    result = fit(model, train, tune, options, contexts, non_action_learning_rate_multiplier=10.)
    assert calls and result["report"]["selected_epoch"] == 0
    assert "synthetic_source_fidelity_regression" in result["report"]["history"][-1]["rejection_reasons"]
    assert all(torch.equal(p, model.state_dict()[name]) for name,p in result["state_dict"].items())
