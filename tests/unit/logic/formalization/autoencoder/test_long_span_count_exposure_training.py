"""Synthetic count-exposure controls; no corpus, holdout, or proof evidence."""
from collections import Counter
from copy import deepcopy
import math
import random
import time

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import long_span_count_exposure_training as subject
from ipfs_datasets_py.logic.formalization.autoencoder import long_span_cardinality_training as previous
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core
from .test_long_span_cardinality_training import setup, evaluated


@pytest.fixture(autouse=True)
def one_cpu():
    old = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


@pytest.mark.parametrize("strategy", ["reference_ce", "semantic_fields"])
def test_current_stage_repeated_clipped_updates_exactly_match_previous_owner(strategy):
    model, _, train, tune, options = setup()
    options["curriculum"] = [dict(name="repeated", training_ids=[row["id"] for row in train], epochs=128)]
    options["config"].update(epochs=128, max_optimizer_steps=128, max_grad_norm=.005,
                             validation_interval=128, patience=0)
    old = previous.train(model, train, tune, cardinality_weight=.25, strategy=strategy, **options)
    new = subject.train(model, train, tune, cardinality_weight=.25, strategy=strategy,
                        count_exposure="current_stage", **options)
    assert old["report"]["optimizer_steps"] == new["report"]["optimizer_steps"] == 128
    for key in ("state_dict", "last_complete_attempt_state_dict"):
        assert all(torch.equal(value, new[key][name]) for name, value in old[key].items())
    assert old["predictions"] == new["predictions"]
    assert old["last_complete_attempt_predictions"] == new["last_complete_attempt_predictions"]
    for left, right in zip(old["report"]["history"], new["report"]["history"]):
        for key in ("mean_minibatch_count_ce", "mean_minibatch_ce", "mean_minibatch_weighted_ce",
                    "accepted", "rejection_reasons", "selected_epoch"):
            assert left[key] == right[key]
    assert new["report"]["count_training_row_presentations"] == 256
    assert new["report"]["count_training_presentations_by_class"] == {"1": 128, "2": 128}
    assert new["report"]["count_mean_loss_exposure_by_class"] == {"1": 64., "2": 64.}
    norms = new["report"]["gradient_norms"]
    assert norms["optimizer_steps"] == norms["norm_exceeded_limit_steps"] == 128
    assert .005 < norms["mean_preclip_norm"] <= norms["max_preclip_norm"]


@pytest.mark.parametrize("seed", [1729, 2718])
def test_full_planned_decoder_schedule_gives_610_count_rows_and_85_mean_loss_exposure_per_class(seed):
    rows = [dict(id=f"train-{label}-{index}") for label in (1, 2, 4, 8) for index in range(12)]
    labels = {row["id"]: int(row["id"].split("-")[1])-1 for row in rows}
    selector = subject._BalancedCountSelector(rows, labels, seed)
    presentations, exposure = Counter(), Counter()
    snapshots, steps = [], 0
    for stage_rows in (12, 26, 36, 48):
        snapshots.append(selector.snapshot())
        for _ in range(20):
            for offset in range(0, stage_rows, 8):
                part = selector.take(min(8, stage_rows-offset))
                steps += 1
                for row in part:
                    label = labels[row["id"]]+1
                    presentations[label] += 1
                    exposure[label] += 1./len(part)
                assert max(presentations.values())-min(presentations.values()) <= 1
    assert steps == 340 and selector.draws == 2440
    assert presentations == {1: 610, 2: 610, 4: 610, 8: 610}
    assert exposure == {1: 85., 2: 85., 4: 85., 8: 85.}
    assert [value["drawn_rows"] for value in snapshots] == [0, 240, 760, 1480]
    replay = subject._BalancedCountSelector(rows, labels, seed)
    for offset in range(0, 2440, 128):
        replay.take(min(128, 2440-offset))
    assert replay.snapshot() == selector.snapshot()
    assert selector.snapshot()["validation_rows_available"] is False


def test_selector_replays_without_mutating_inputs_or_global_and_decoder_rngs():
    rows = [dict(id=f"train-{index}", input=[float(index)]) for index in range(10)]
    labels = {row["id"]: index % 2 for index, row in enumerate(rows)}
    inputs = deepcopy((rows, labels))
    random_before, torch_before = random.getstate(), torch.get_rng_state().clone()
    decoder = torch.Generator().manual_seed(55)
    decoder_before = decoder.get_state().clone()
    left = subject._BalancedCountSelector(rows, labels, 9)
    right = subject._BalancedCountSelector(rows, labels, 9)
    sequence = [row["id"] for row in left.take(100)]
    assert sequence == [row["id"] for row in right.take(100)]
    assert left.snapshot() == right.snapshot()
    assert random.getstate() == random_before and torch.equal(torch.get_rng_state(), torch_before)
    assert torch.equal(decoder.get_state(), decoder_before)
    assert (rows, labels) == inputs
    for label in (0, 1):
        first_cycle = [identity for identity in sequence if labels[identity] == label][:5]
        assert len(set(first_cycle)) == 5


def test_balanced_count_forward_uses_training_source_only_and_preserves_decoder_batches(monkeypatch):
    model, _, train, tune, options = setup()
    options["curriculum"][0]["epochs"] = 2
    source_calls, decoder_calls = [], []
    original_source, original_logits = subject._source_batch, core._logits
    def source_batch(torch_module, rows, transform):
        if torch.is_grad_enabled():
            source_calls.append([row["id"] for row in rows])
        return original_source(torch_module, rows, transform)
    def decoder_logits(torch_module, working, data, prefix, size):
        if torch.is_grad_enabled():
            decoder_calls.append((data.detach().clone(), prefix.detach().clone()))
        return original_logits(torch_module, working, data, prefix, size)
    monkeypatch.setattr(subject, "_source_batch", source_batch)
    monkeypatch.setattr(core, "_logits", decoder_logits)
    original = deepcopy((train, tune, options))
    before = core.tensor_digest(model)
    result = subject.train(model, train, tune, cardinality_weight=.25, count_exposure="balanced_all", **options)
    assert source_calls == [[train[0]["id"]], [train[1]["id"]], [train[0]["id"], train[1]["id"]]]
    assert len(decoder_calls) == 3
    assert torch.equal(decoder_calls[0][0], decoder_calls[1][0])
    assert torch.equal(decoder_calls[0][1], decoder_calls[1][1])
    assert decoder_calls[0][1].tolist() == [train[0]["target_ids"][:-1]]
    assert (train, tune, options) == original and core.tensor_digest(model) == before
    assert all(parameter.grad is None for parameter in model.parameters())
    report = result["report"]
    assert report["count_training_row_presentations"] == report["row_presentations"] == 4
    assert report["count_training_presentations_by_class"] == {"1": 2, "2": 2}
    assert report["count_mean_loss_exposure_by_class"] == {"1": 1.5, "2": 1.5}
    assert not report["count_validation_rows_used_for_training"]
    assert not report["count_reference_documents_passed_to_model"]
    assert report["frozen_parameters_verified"]
    for name, parameter in model.named_parameters():
        if not parameter.requires_grad:
            assert torch.equal(parameter, result["state_dict"][name])
            assert torch.equal(parameter, result["last_complete_attempt_state_dict"][name])
    first, second = report["stage_reports"]
    assert first["optimizer_state_end"] == second["optimizer_state_start"]
    assert first["count_selector_end"] == second["count_selector_start"]
    assert report["optimizer_instance_count"] == 1
    assert all(report[key] is False for key in subject.FALSE)


def test_count_posteriors_confusion_and_entropy_reconcile_and_remain_diagnostic():
    model, _, _, tune, options = setup()
    report = subject._count_evaluation(torch, model, tune, options["validation_references"],
        options["input_transform"], core._config(options["config"]), time.monotonic()+20.)
    assert sum(sum(row.values()) for row in report["confusion_matrix"].values()) == len(tune)
    assert report["confusion_matrix"]["1"]["1"] == report["confusion_matrix"]["2"]["1"] == 1
    assert report["mean_predictive_entropy"] == pytest.approx(math.log(32), abs=1e-6)
    assert report["mean_max_probability"] == 1./32
    assert not report["used_for_selection"] and not report["reference_count_supplied_to_generation"]
    for row in report["predictions"]:
        assert len(row["logits"]) == len(row["probabilities"]) == 32
        assert row["logits"] == [0.]*32
        assert sum(row["probabilities"]) == pytest.approx(1.)
        assert 0 <= row["predictive_entropy"] <= math.log(32)+1e-6


def test_history_omits_posterior_rows_while_final_diagnostics_keep_them():
    model, _, train, tune, options = setup()
    result = subject.train(model, train, tune, cardinality_weight=.25, count_exposure="balanced_all", **options)
    for epoch in result["report"]["history"]:
        assert "predictions" not in epoch["source_count"]
        assert "confusion_matrix" in epoch["source_count"]
    for role in ("baseline", "selected", "last_complete_attempt"):
        assert len(result["report"][role]["source_count"]["predictions"]) == len(tune)


@pytest.mark.parametrize("policy", [None, True, "balanced_validation", "all", 0])
def test_closed_exposure_policy_rejects_unsupported_values(policy):
    model, _, train, tune, options = setup()
    with pytest.raises(ValueError, match="count exposure"):
        subject.train(model, train, tune, count_exposure=policy, **options)


@pytest.mark.parametrize("change", [
    lambda t,v,o: o["training_references"][0].update(id=v[0]["id"]),
    lambda t,v,o: o["training_references"][0].update(clause_count=True),
    lambda t,v,o: o["training_references"][0]["target"]["rules"].append(deepcopy(o["training_references"][0]["target"]["rules"][0])),
    lambda t,v,o: v[0].update(source_text=t[0]["source_text"]),
    lambda t,v,o: t[0].update(input=[float("nan")]*8),
])
def test_count_training_cannot_bypass_reference_source_or_split_validation(change):
    model, _, train, tune, options = setup()
    change(train,tune,options)
    with pytest.raises(ValueError):
        subject.train(model, train, tune, cardinality_weight=.25, count_exposure="balanced_all", **options)


def test_partial_count_evaluation_keeps_selected_state_and_digest_roles(monkeypatch):
    model, _, train, tune, options = setup()
    calls, original = [], subject._count_evaluation
    def incomplete(*args):
        calls.append(1)
        return original(*args) if len(calls) == 1 else None
    monkeypatch.setattr(subject,"_count_evaluation",incomplete)
    result=subject.train(model,train,tune,cardinality_weight=.25,count_exposure="balanced_all",**options)
    report=result["report"]
    assert report["selected_epoch"]==0 and report["stopped_reason"]=="deadline_during_validation"
    assert report["selected_weights_sha256"]==core.tensor_digest(model)
    assert result["last_complete_attempt_state_dict"] is None
    assert report["last_complete_attempt_weights_sha256"] is None
    assert report["count_training_row_presentations"]==report["row_presentations"]==1


def test_improved_count_cannot_override_source_fidelity_regression(monkeypatch):
    model, _, train, tune, options=setup()
    results=iter([evaluated(options,ce=2.,count_ce=2.),
        evaluated(options,ce=.1,count_ce=.01,mutate=lambda target:target["rules"][0].update(actor="agency"))])
    monkeypatch.setattr(subject,"_evaluate",lambda *args:next(results))
    options["curriculum"]=options["curriculum"][:1]
    options["curriculum"][0]["training_ids"]=[row["id"] for row in train]
    result=subject.train(model,train,tune,cardinality_weight=.25,count_exposure="balanced_all",**options)
    assert result["report"]["selected_epoch"]==0
    assert any("actor" in reason for reason in result["report"]["history"][0]["rejection_reasons"])
    diagnostic=deepcopy(model);diagnostic.load_state_dict(result["last_complete_attempt_state_dict"],strict=True)
    assert result["report"]["last_complete_attempt_weights_sha256"]==core.tensor_digest(diagnostic)
    assert result["report"]["last_complete_attempt_weights_sha256"]!=result["report"]["selected_weights_sha256"]


def test_memory_refusal_precedes_model_copy(monkeypatch):
    model, _, train,tune,options=setup()
    options["config"].update(batch_size=128,max_memory_bytes=1048576)
    original=subject.deepcopy
    def checked(value):
        assert not isinstance(value,torch.nn.Module)
        return original(value)
    monkeypatch.setattr(subject,"deepcopy",checked)
    with pytest.raises(ValueError,match="tensor work"):
        subject.train(model,train,tune,count_exposure="balanced_all",**options)


def test_deadline_after_balanced_draw_does_not_count_uncommitted_exposure(monkeypatch):
    model, _, train,tune,options=setup()
    clock=[0.]
    monkeypatch.setattr(subject.time,"monotonic",lambda:clock[0])
    original=subject._count_logits
    def expire_after_forward(*args):
        result=original(*args)
        if torch.is_grad_enabled():
            clock[0]=21.
        return result
    monkeypatch.setattr(subject,"_count_logits",expire_after_forward)
    result=subject.train(model,train,tune,cardinality_weight=.25,count_exposure="balanced_all",**options)
    report=result["report"]
    assert report["stopped_reason"]=="deadline"
    assert report["optimizer_steps"]==report["row_presentations"]==report["count_training_row_presentations"]==0
    assert report["count_training_presentations_by_class"]=={"1":0,"2":0}
    assert report["count_mean_loss_exposure_by_class"]=={"1":0.,"2":0.}
    assert report["count_selector_final"]["drawn_rows"]==1
    assert report["count_selector_draws_may_include_uncommitted_final_batch"]
    assert report["gradient_norms"]["optimizer_steps"]==0
    assert report["gradient_norms"]["mean_preclip_norm"] is None
    assert report["selected_weights_sha256"]==core.tensor_digest(model)
