"""Genuine synthetic numerical controls for the opt-in F18 v2 runtime.

These cases require a fresh original-owned numerical admission. They construct
real CPU float32 F18 models and Adam optimizers from invented inputs, never a
retained checkpoint, source export, teacher capture, or evaluation reference.
The test rates are fixtures, not selected experiment rates. No capture, retained
632-row parity, fit, statistical gain, or legal qualification is established.
"""
import copy
import hashlib
import os
from pathlib import Path
import sys
import types

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    legal_span_conditions_fullspan_optimizer_recipe_v1 as recipes,
    legal_span_conditions_fullspan_training_v1 as base,
    legal_span_conditions_fullspan_training_v2 as subject,
)


ROOT = Path(__file__).resolve().parents[4]
FIXTURE_PATH = ROOT / "tests/unit/optimizers/logic_theorem_optimizer/test_legal_span_conditions_fullspan_training_v1.py"
FIXTURE_SHA256 = "bbed34c8d81ecac7ecf020e682e37dc550fc29a8839775107eacb43496b7d50a"
SELECTED = ("start.weight", "start.bias", "end.weight", "end.bias")
INACTIVE = [0, 1, 2, 4, 5]
FALSE_FLAGS = ("admitted", "formalized", "promoted", "qualified", "semantic_review_performed", "model_gain_claimed")


@pytest.fixture(scope="module")
def synthetic_template():
    # Execute only the pinned existing fixture owner, at qualification time.
    # Compiling the verified bytes avoids a second read and source-tree pycache.
    raw = FIXTURE_PATH.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == FIXTURE_SHA256
    name = "_f18_v2_existing_synthetic_fixture_owner"
    owner = types.ModuleType(name)
    owner.__file__ = str(FIXTURE_PATH)
    sys.modules[name] = owner
    exec(compile(raw, str(FIXTURE_PATH), "exec"), owner.__dict__)
    return owner._checkpoint_case(actual_model=True)


@pytest.fixture
def case(synthetic_template):
    return copy.deepcopy(synthetic_template)


def _kwargs(case, *, learning_rate=0.002, margin_weight=0.25):
    return {
        **case,
        "recipe": recipes.build_optimizer_recipe(
            donor_config=case["provenance"]["config"],
            expected_bindings=case["expected_bindings"],
            learning_rate=learning_rate, margin_weight=margin_weight),
        "learning_rate": learning_rate,
        "margin_weight": margin_weight,
    }


def _same_bytes(torch, left, right):
    return torch.equal(left.detach().contiguous().reshape(-1).view(torch.uint8),
                       right.detach().contiguous().reshape(-1).view(torch.uint8))


def _assert_partition(torch, runtime, donor, *, steps):
    named, optimizer = runtime["named"], runtime["optimizer"]
    assert tuple(name for name in named if named[name].requires_grad) == SELECTED
    assert len(named) == 42 and len(base.FROZEN) == 38
    assert [id(p) for p in optimizer.param_groups[0]["params"]] == [id(named[n]) for n in SELECTED]
    for name in base.FROZEN:
        expected = torch.tensor(donor[name], dtype=torch.float32)
        assert _same_bytes(torch, named[name], expected)
        assert named[name].grad is None and named[name] not in optimizer.state
    for name in SELECTED:
        parameter = named[name]
        expected = torch.tensor(donor[name], dtype=torch.float32)
        assert _same_bytes(torch, parameter[INACTIVE], expected[INACTIVE])
        if parameter.grad is not None:
            assert torch.count_nonzero(parameter.grad[INACTIVE]) == 0
        if steps:
            moment = optimizer.state[parameter]
            assert int(moment["step"]) == steps
            assert torch.count_nonzero(moment["exp_avg"][INACTIVE]) == 0
            assert torch.count_nonzero(moment["exp_avg_sq"][INACTIVE]) == 0
        else:
            assert parameter not in optimizer.state


def _assert_false(value):
    assert all(value[name] is False for name in FALSE_FLAGS)


def _forbid_model(monkeypatch):
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("invalid input reached the actual model constructor")

    monkeypatch.setattr(base.f18, "_model", forbidden)
    return calls


def _manual_trajectory(torch, case, *, learning_rate, margin_weight, count):
    """Independent original-model/Adam oracle; never calls a v2 runtime API."""
    with torch.random.fork_rng(devices=[]):
        model = base.f18._model(torch, case["provenance"]["config"])
        model.load_state_dict({name: torch.tensor(value, dtype=torch.float32)
                               for name, value in case["state"].items()}, strict=True)
    named = dict(model.named_parameters())
    assert tuple(named) == base.f18.MODEL_PARAMETER_NAMES
    for name, parameter in named.items():
        parameter.requires_grad_(name in SELECTED)
        parameter.grad = None
        if name in SELECTED:
            parameter.register_hook(lambda gradient: base._mask_gradient(gradient, 3))
    selected = [named[name] for name in SELECTED]
    optimizer = torch.optim.Adam(selected, lr=learning_rate, betas=(0.9, 0.999),
                                 eps=1e-8, weight_decay=0.0, foreach=False)
    assert optimizer.state == {}
    progress = {"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0}
    trace = []
    with torch.enable_grad():
        for _ in range(count):
            indices = base.f18.targeted._batch_indices(168, progress, 12, 1729)
            batch = [case["records"][index] for index in indices]
            model.train()
            optimizer.zero_grad(set_to_none=True)
            output = model(*base.f18.span._batch(torch, batch))
            objective = base.compose_objective_for_state(
                torch, output, batch, indices, case["teacher"], case["weights"],
                case["state"], case["provenance"], margin_weight=margin_weight)
            original, details = base.f18._loss(torch, output, batch, indices,
                base.f18._policy("modality-conditions-retention-ce"), case["teacher"], case["weights"])
            assert _same_bytes(torch, original, objective["f18_ce_plus_kl"])
            objective["loss"].backward()
            base.clip_selected_gradients(torch, selected)
            optimizer.step()
            progress = base.f18.targeted._advance_progress(progress, len(indices), 168)
            trace.append({"indices": indices, "loss": float(objective["loss"].detach()),
                "f18_ce_plus_kl": float(original.detach()), "details": copy.deepcopy(details),
                "margin": {key: float(value.detach()) if key in ("loss", "weighted_loss") else copy.deepcopy(value)
                           for key, value in objective["margin"].items()}})
    model.eval()
    return {"model": model, "optimizer": optimizer, "named": named, "selected": selected}, progress, trace


def _assert_same_runtime(torch, left, right):
    for name in base.f18.MODEL_PARAMETER_NAMES:
        assert _same_bytes(torch, left["named"][name], right["named"][name])
    for name in SELECTED:
        a = left["optimizer"].state[left["named"][name]]
        b = right["optimizer"].state[right["named"][name]]
        for key in ("step", "exp_avg", "exp_avg_sq"):
            assert _same_bytes(torch, a[key], b[key])


@pytest.mark.parametrize("learning_rate", [0.002, 0.004], ids=["lr002", "lr004"])
def test_fresh_changed_rate_adam_preserves_donor_config_and_mask(case, learning_rate):
    import torch
    kwargs = _kwargs(case, learning_rate=learning_rate)
    offered = base._checkpoint_raw(kwargs)
    checkpoint = subject.build_checkpoint(**kwargs)
    rng = torch.get_rng_state().clone()
    runtime = subject.restore_optimizer(torch, checkpoint, **kwargs)
    other = subject.restore_optimizer(torch, checkpoint, **kwargs)
    assert torch.equal(rng, torch.get_rng_state())
    assert checkpoint["schema"] == "conditions-fullspan-f18-four-tensor-checkpoint/v2"
    assert checkpoint["lineage_id"] == "conditions_fullspan_f18_four_tensor_v2"
    assert checkpoint["training_policy"] == kwargs["recipe"]
    assert runtime["recipe_sha256"] == subject.checkpoint_digest(kwargs["recipe"])
    assert runtime["config"]["learning_rate"] == 0.001
    assert runtime["recipe"]["base_policy"]["optimizer"]["learning_rate"] == 0.001
    assert runtime["learning_rate"] == learning_rate
    for controls in (runtime["optimizer"].defaults, runtime["optimizer"].param_groups[0]):
        assert controls["lr"] == learning_rate and controls["betas"] == (0.9, 0.999)
        assert controls["eps"] == 1e-8 and controls["weight_decay"] == 0.0 and controls["foreach"] is False
    assert runtime["optimizer"].state == {} and other["optimizer"].state == {}
    assert all(runtime["named"][n] is not other["named"][n] for n in runtime["named"])
    assert runtime["model"].training is False and runtime["model_forwards"] == 0
    assert all(value == 0 for value in runtime["model"]._actor_forward_accounting.values())
    assert all(value == 0 for value in runtime["model"]._conditions_forward_accounting.values())
    _assert_partition(torch, runtime, case["state"], steps=0)
    _assert_false(checkpoint["authority"])
    assert base._checkpoint_raw(kwargs) == offered


@pytest.mark.parametrize("learning_rate", [0.002, 0.004], ids=["lr002", "lr004"])
def test_first_step_matches_independent_adam_equations(case, learning_rate):
    import torch
    kwargs = _kwargs(case, learning_rate=learning_rate)
    checkpoint = subject.build_checkpoint(**kwargs)
    runtime = subject.restore_optimizer(torch, checkpoint, **kwargs)
    before = {name: value.detach().clone() for name, value in runtime["named"].items()}
    # Known small derivative avoids clipping and independently exposes actual LR.
    loss = 0.01 * sum(parameter.sum() for parameter in runtime["selected"])
    loss.backward()
    assert float(base.clip_selected_gradients(torch, runtime["selected"])) < 5.0
    runtime["optimizer"].step()
    g, beta1, beta2, eps = 0.01, 0.9, 0.999, 1e-8
    first_moment, second_moment = (1 - beta1) * g, (1 - beta2) * g * g
    update = learning_rate * (first_moment / (1 - beta1)) / ((second_moment / (1 - beta2)) ** 0.5 + eps)
    for name in SELECTED:
        parameter = runtime["named"][name]
        expected = torch.tensor([float(value) - update for value in before[name][3].reshape(-1)],
                                dtype=torch.float32).reshape(parameter[3].shape)
        assert torch.allclose(parameter[3], expected, rtol=1e-6, atol=2e-7)
        moment = runtime["optimizer"].state[parameter]
        assert torch.allclose(moment["exp_avg"][3], torch.full_like(parameter[3], first_moment), rtol=2e-6, atol=1e-10)
        assert torch.allclose(moment["exp_avg_sq"][3], torch.full_like(parameter[3], second_moment), rtol=2e-6, atol=1e-10)
    _assert_partition(torch, runtime, case["state"], steps=1)
    assert runtime["model_forwards"] == 0


@pytest.mark.parametrize("margin_weight", [0.0, 0.25], ids=["arm0", "arm025"])
def test_actual_mixed_batch_update_matches_original_objective(case, margin_weight):
    import torch
    kwargs = _kwargs(case, margin_weight=margin_weight)
    manual, progress, trace = _manual_trajectory(torch, case,
        learning_rate=0.002, margin_weight=margin_weight, count=1)
    checkpoint = subject.build_checkpoint(**kwargs)
    trained, report = subject.run_admitted_updates(checkpoint, torch=torch, **kwargs, max_steps=1, max_seconds=32)
    restored = subject.restore_optimizer(torch, trained, **kwargs)
    _assert_same_runtime(torch, manual, restored)
    _assert_partition(torch, restored, case["state"], steps=1)
    saved, expected = report["batch_trace"][0], trace[0]
    assert saved["indices"] == expected["indices"]
    assert saved["loss"] == expected["loss"] and saved["f18_ce_plus_kl"] == expected["f18_ce_plus_kl"]
    assert saved["f18_objective_details"]["weighted_CE"] == expected["details"]["weighted_CE"]
    assert saved["f18_objective_details"]["retention"] == expected["details"]["retention"]
    assert saved["f18_objective_details"]["weighted_CE"]["batch_denominator"] == 12
    assert saved["f18_objective_details"]["weighted_CE"]["outer_denominator"] == 8
    assert saved["f18_objective_details"]["retention"]["denominator"] == 72
    assert saved["conditions_margin"]["batch_size"] == 12
    assert 0 < saved["conditions_margin"]["present_count"] < 12
    assert report["after_progress"] == progress and report["training_model_forwards"] == 1
    assert report["learning_rate"] == 0.002 and report["donor_config_learning_rate"] == 0.001
    _assert_false(report)


@pytest.mark.parametrize("margin_weight", [0.0, 0.25], ids=["arm0", "arm025"])
def test_disk_resume_matches_independent_manual_and_uninterrupted(case, tmp_path, margin_weight):
    import torch
    kwargs = _kwargs(case, margin_weight=margin_weight)
    offered = base._checkpoint_raw(kwargs)
    manual, progress, trace = _manual_trajectory(torch, case,
        learning_rate=0.002, margin_weight=margin_weight, count=2)
    checkpoint = subject.build_checkpoint(**kwargs)
    rng = torch.get_rng_state().clone()
    with torch.no_grad():
        whole, whole_report = subject.run_admitted_updates(checkpoint, torch=torch, **kwargs, max_steps=2, max_seconds=32)
        first, first_report = subject.run_admitted_updates(checkpoint, torch=torch, **kwargs, max_steps=1, max_seconds=32)
        ref = subject.save_checkpoint(first, tmp_path / "after-one.json", **kwargs)
        loaded = subject.load_checkpoint(ref["path"], expected_sha256=ref["sha256"], **kwargs)
        resumed, second_report = subject.run_admitted_updates(loaded, torch=torch, **kwargs, max_steps=1, max_seconds=32)
        resumed_runtime = subject.restore_optimizer(torch, resumed, **kwargs)
        whole_runtime = subject.restore_optimizer(torch, whole, **kwargs)
        assert torch.is_grad_enabled() is False and torch.equal(rng, torch.get_rng_state())
    assert subject.validate_checkpoint(resumed, **kwargs) is None
    _assert_same_runtime(torch, manual, resumed_runtime)
    _assert_same_runtime(torch, manual, whole_runtime)
    _assert_partition(torch, resumed_runtime, case["state"], steps=2)
    assert resumed["progress"] == whole["progress"] == progress
    assert resumed["initial_checkpoint_sha256"] == whole["initial_checkpoint_sha256"] == checkpoint["initial_checkpoint_sha256"]
    assert first["parent_checkpoint_sha256"] == subject.checkpoint_digest(checkpoint)
    assert resumed["parent_checkpoint_sha256"] == subject.checkpoint_digest(first)
    assert whole["parent_checkpoint_sha256"] == subject.checkpoint_digest(checkpoint)
    assert [row["indices"] for row in whole_report["batch_trace"]] == [row["indices"] for row in trace]
    assert [row["indices"] for row in first_report["batch_trace"] + second_report["batch_trace"]] == [row["indices"] for row in trace]
    assert all(r["learning_rate"] == 0.002 for r in (whole_report, first_report, second_report))
    for report in (whole_report, first_report, second_report):
        assert report["teacher_model_forwards"] == 0 and report["tuning_or_evaluation_references_used"] is False
        _assert_false(report)
    assert base._checkpoint_raw(kwargs) == offered


@pytest.mark.parametrize("damage", ["learning_rate", "margin_weight", "bindings", "donor", "source"])
def test_cross_recipe_inputs_refused_before_model(case, monkeypatch, damage):
    import torch
    kwargs = _kwargs(case)
    checkpoint = subject.build_checkpoint(**kwargs)
    if damage == "learning_rate":
        kwargs = _kwargs(case, learning_rate=0.004)
    elif damage == "margin_weight":
        kwargs = _kwargs(case, margin_weight=0.0)
    elif damage == "bindings":
        changed = copy.deepcopy(case)
        changed["expected_bindings"]["context_contract_sha256"] = "f" * 64
        kwargs = _kwargs(changed)
    elif damage == "donor":
        kwargs["state"] = copy.deepcopy(kwargs["state"])
        kwargs["state"]["start.bias"][3] += 0.125
    else:
        checkpoint["implementation"] = {"schema": "different-source-generation/v1"}
    calls = _forbid_model(monkeypatch)
    with pytest.raises(ValueError):
        subject.restore_optimizer(torch, checkpoint, **kwargs)
    assert calls == []


@pytest.mark.parametrize("damage", ["inactive_selected", "nonbinary_selected", "negative_second_moment", "inactive_moment"])
def test_numeric_checkpoint_tamper_refused_before_model(case, monkeypatch, damage):
    import torch
    kwargs = _kwargs(case)
    initial = subject.build_checkpoint(**kwargs)
    checkpoint, _ = subject.run_admitted_updates(initial, torch=torch, **kwargs, max_steps=1, max_seconds=32)
    if damage in ("inactive_selected", "nonbinary_selected"):
        row = 0 if damage == "inactive_selected" else 3
        checkpoint["selected_state"]["start.weight"][row][0] = 0.125 if row == 0 else 0.1
        reconstructed = copy.deepcopy(case["state"])
        reconstructed.update(copy.deepcopy(checkpoint["selected_state"]))
        checkpoint["model_state_sha256"] = subject.checkpoint_digest(reconstructed)
    elif damage == "negative_second_moment":
        checkpoint["optimizer_state"]["parameters"]["start.weight"]["exp_avg_sq"][3][0] = -0.125
    else:
        checkpoint["optimizer_state"]["parameters"]["start.weight"]["exp_avg"][0][0] = 0.125
    calls = _forbid_model(monkeypatch)
    with pytest.raises(ValueError):
        subject.restore_optimizer(torch, checkpoint, **kwargs)
    assert calls == []


@pytest.mark.parametrize("boundary", ["zero_steps", "zero_seconds", "cumulative", "boolean_steps", "negative_seconds"])
def test_finite_budget_boundaries_refuse_or_noop_before_model(case, monkeypatch, boundary):
    import torch
    kwargs = _kwargs(case)
    checkpoint = subject.build_checkpoint(**kwargs)
    if boundary == "cumulative":
        checkpoint, _ = subject.run_admitted_updates(checkpoint, torch=torch, **kwargs, max_steps=1, max_seconds=32)
    before = base._checkpoint_raw(checkpoint)
    calls = _forbid_model(monkeypatch)
    options = {"max_steps": 1, "max_seconds": 32}
    options.update({"zero_steps": {"max_steps": 0}, "zero_seconds": {"max_seconds": 0},
                    "cumulative": {"max_steps": 32}, "boolean_steps": {"max_steps": True},
                    "negative_seconds": {"max_seconds": -1}}[boundary])
    if boundary.startswith("zero_"):
        returned, report = subject.run_admitted_updates(checkpoint, torch=torch, **kwargs, **options)
        assert base._checkpoint_raw(returned) == before
        assert report["optimizer_steps"] == report["training_model_forwards"] == 0
        assert report["before_progress"] == report["after_progress"] == checkpoint["progress"]
        assert report["training_executed"] is False
    else:
        with pytest.raises(ValueError):
            subject.run_admitted_updates(checkpoint, torch=torch, **kwargs, **options)
    assert calls == [] and base._checkpoint_raw(checkpoint) == before


@pytest.mark.parametrize("damage", ["TRAIN", "teacher", "mask"])
def test_synthetic_prepared_input_contamination_refused_before_model(case, monkeypatch, damage):
    import torch
    changed = copy.deepcopy(case)
    if damage == "TRAIN":
        changed["records"][0]["id"] = changed["records"][1]["id"]
        changed["expected_bindings"]["prepared_training_records_sha256"] = subject.checkpoint_digest(changed["records"])
    elif damage == "teacher":
        changed["teacher"]["teacher_model_forwards"] = 1
        changed["expected_bindings"]["teacher_training_sha256"] = subject.checkpoint_digest(changed["teacher"])
    else:
        changed["weights"]["candidate_predictions_used"] = True
        changed["expected_bindings"]["row_weight_training_sha256"] = subject.checkpoint_digest(changed["weights"])
    kwargs = _kwargs(changed)
    calls = _forbid_model(monkeypatch)
    with pytest.raises(ValueError):
        subject.build_checkpoint(**kwargs)
    assert calls == []


@pytest.mark.parametrize("outcome", ["success", "exception"])
def test_caller_context_preserved_on_success_and_exception(case, monkeypatch, outcome):
    import torch
    kwargs = _kwargs(case)
    checkpoint = subject.build_checkpoint(**kwargs)
    before = base._checkpoint_raw(kwargs)
    runtimes = []
    original_restore = subject.restore_optimizer

    def record_runtime(*args, **kwargs):
        runtime = original_restore(*args, **kwargs)
        runtimes.append(runtime)
        return runtime

    monkeypatch.setattr(subject, "restore_optimizer", record_runtime)
    if outcome == "exception":
        def fail_objective(*args, **kwargs):
            raise RuntimeError("synthetic objective failure after genuine model forward")
        monkeypatch.setattr(base, "compose_objective_for_state", fail_objective)
    rng = torch.get_rng_state().clone()
    with torch.no_grad():
        if outcome == "exception":
            with pytest.raises(RuntimeError, match="synthetic objective failure"):
                subject.run_admitted_updates(checkpoint, torch=torch, **kwargs, max_steps=1, max_seconds=32)
        else:
            subject.run_admitted_updates(checkpoint, torch=torch, **kwargs, max_steps=1, max_seconds=32)
        assert torch.is_grad_enabled() is False and torch.equal(rng, torch.get_rng_state())
    assert len(runtimes) == 1 and runtimes[0]["model"].training is False
    assert all(parameter.grad is None for parameter in runtimes[0]["named"].values())
    assert base._checkpoint_raw(kwargs) == before


@pytest.mark.parametrize("fixture", ["hash", "symlink", "fifo"])
def test_strict_persistence_guards(case, tmp_path, fixture):
    import torch
    kwargs = _kwargs(case)
    checkpoint = subject.build_checkpoint(**kwargs)
    ref = subject.save_checkpoint(checkpoint, tmp_path / "source-checkpoint.json", **kwargs)
    assert subject.load_checkpoint(ref["path"], expected_sha256=ref["sha256"], **kwargs) == checkpoint
    if fixture == "hash":
        with pytest.raises(ValueError):
            subject.load_checkpoint(ref["path"], expected_sha256="f" * 64, **kwargs)
        return
    path = tmp_path / ("checkpoint-link.json" if fixture == "symlink" else "checkpoint.fifo")
    if fixture == "symlink":
        path.symlink_to(Path(ref["path"]))
    else:
        os.mkfifo(path, 0o600)
    try:
        with pytest.raises(ValueError):
            subject.load_checkpoint(path, expected_sha256=ref["sha256"], **kwargs)
    finally:
        path.unlink()


def test_source_drift_refused_before_model(case, monkeypatch):
    import torch
    kwargs = _kwargs(case)
    checkpoint = subject.build_checkpoint(**kwargs)
    original = subject._source

    def observed_source(path, maximum):
        return "f" * 64 if Path(path) == Path(base.__file__) else original(path, maximum)

    monkeypatch.setattr(subject, "_source", observed_source)
    calls = _forbid_model(monkeypatch)
    with pytest.raises(ValueError, match="source"):
        subject.restore_optimizer(torch, checkpoint, **kwargs)
    assert calls == []


def test_v1_checkpoint_schema_refused_before_model(case, monkeypatch):
    import torch
    kwargs = _kwargs(case)
    checkpoint = base.build_checkpoint(**{key: value for key, value in kwargs.items()
                                         if key not in ("recipe", "learning_rate")})
    calls = _forbid_model(monkeypatch)
    with pytest.raises(ValueError):
        subject.restore_optimizer(torch, checkpoint, **kwargs)
    assert calls == []


# Capture controls extend the exact 32-case numerical prefix above.
def _source_rows(case, count=2):
    return [{"id": "v2-source-%03d" % index,
             "source_text": case["records"][index]["source_text"],
             "latent": list(case["records"][index]["latent"])}
            for index in range(count)]


def _capture_setup(torch, case, *, margin_weight=0.25):
    kwargs = _kwargs(case, margin_weight=margin_weight)
    checkpoint = subject.build_checkpoint(**kwargs)
    runtime = subject.restore_optimizer(torch, checkpoint, **kwargs)
    return kwargs, checkpoint, runtime


@pytest.mark.parametrize("margin_weight", [0.0, 0.25], ids=["arm0", "arm025"])
def test_v2_capture_matches_original_v1_heads_and_complete_readout(case, monkeypatch, margin_weight):
    import torch
    kwargs, checkpoint, runtime = _capture_setup(torch, case, margin_weight=margin_weight)
    rows = _source_rows(case)
    original_kwargs = {**case, "margin_weight": margin_weight}
    original_checkpoint = base.build_checkpoint(**original_kwargs)
    original_runtime = base.restore_optimizer(torch, original_checkpoint, **original_kwargs)
    reference = base.captured_inference(original_runtime, original_checkpoint, rows, **original_kwargs)
    before = base._checkpoint_raw(base.f18.span._pack(runtime["model"], runtime["optimizer"]))
    offered = base._checkpoint_raw(rows)
    rng, grad_mode = torch.get_rng_state().clone(), torch.is_grad_enabled()

    def forbidden_restore(*args, **kwargs):
        raise AssertionError("capture attempted another restore")

    monkeypatch.setattr(subject, "restore_optimizer", forbidden_restore)
    result = subject.captured_inference(runtime, checkpoint, rows, **kwargs)
    assert result["schema"] == "conditions-fullspan-four-tensor-target-free-head-capture/v2"
    assert result["inference"]["schema"] == "conditions-fullspan-four-tensor-inference/v2"
    assert result["inference"]["rows"] == reference["inference"]["rows"]
    assert result["occurrences"] == reference["occurrences"]
    assert result["actual_source_forwards"] == result["cumulative_source_forwards"] == 2
    assert result["extra_capture_forwards"] == 0
    assert all(v == 2 for table in result["forward_counter_deltas"].values() for v in table.values())
    assert result["inference"]["recipe_sha256"] == subject.checkpoint_digest(kwargs["recipe"])
    assert result["inference"]["learning_rate"] == 0.002
    assert result["inference"]["donor_config_learning_rate"] == 0.001
    assert before == base._checkpoint_raw(base.f18.span._pack(runtime["model"], runtime["optimizer"]))
    assert offered == base._checkpoint_raw(rows)
    assert torch.equal(rng, torch.get_rng_state()) and torch.is_grad_enabled() is grad_mode
    assert not runtime["model"].training and not runtime["model"]._forward_hooks
    assert result["target_access"] is result["teacher_forcing"] is result["training_executed"] is False
    _assert_false(result)
    _assert_false(result["inference"])


def test_v2_capture_reuses_one_runtime_for_128_and_40_source_rows(case):
    import torch
    kwargs, checkpoint, runtime = _capture_setup(torch, case)
    rows = _source_rows(case, 168)
    with torch.no_grad():
        first = subject.captured_inference(runtime, checkpoint, rows[:128], **kwargs)
        second = subject.captured_inference(runtime, checkpoint, rows[128:], **kwargs)
        assert torch.is_grad_enabled() is False
    assert first["actual_source_forwards"] == first["cumulative_source_forwards"] == 128
    assert second["actual_source_forwards"] == 40 and second["cumulative_source_forwards"] == 168
    assert all(v == 40 for table in second["forward_counter_deltas"].values() for v in table.values())
    assert [v["id"] for v in first["occurrences"] + second["occurrences"]] == [v["id"] for v in rows]
    assert runtime["optimizer_steps"] == 0 and runtime["optimizer"].state == {}
    assert runtime["model_forwards"] == 168
    _assert_partition(torch, runtime, case["state"], steps=0)


@pytest.mark.parametrize("damage", ["labels", "reference", "duplicate", "nonfinite", "empty", "over128"])
def test_v2_capture_rejects_target_or_invalid_rows_before_forward(case, damage):
    import torch
    kwargs, checkpoint, runtime = _capture_setup(torch, case)
    valid = _source_rows(case)
    rows = copy.deepcopy(valid)
    if damage in ("labels", "reference"):
        rows[0][damage] = "unpermitted target"
    elif damage == "duplicate":
        rows[1]["id"] = rows[0]["id"]
    elif damage == "nonfinite":
        rows[0]["latent"][0] = float("nan")
    elif damage == "empty":
        rows = []
    else:
        rows = _source_rows(case, 129)
    with pytest.raises(ValueError):
        subject.captured_inference(runtime, checkpoint, rows, **kwargs)
    assert runtime["model_forwards"] == 0
    assert all(v == 0 for v in runtime["model"]._conditions_forward_accounting.values())
    assert subject.captured_inference(runtime, checkpoint, valid[:1], **kwargs)["actual_source_forwards"] == 1


@pytest.mark.parametrize("damage", ["state", "learning_rate", "progress", "local_hook", "global_hook", "callable", "decoder_code", "named_parameter"])
def test_v2_capture_runtime_and_hooks_are_refused_before_forward(case, monkeypatch, damage):
    import torch
    kwargs, checkpoint, runtime = _capture_setup(torch, case)
    model = runtime["model"]
    handle = None
    if damage == "state":
        with torch.no_grad():
            runtime["named"]["start.bias"][3] += 0.125
    elif damage == "learning_rate":
        runtime["optimizer"].param_groups[0]["lr"] = 0.004
    elif damage == "progress":
        runtime["progress"]["optimizer_steps"] = 1
    elif damage == "local_hook":
        handle = model.register_forward_hook(lambda *args: None)
    elif damage == "global_hook":
        handle = torch.nn.modules.module.register_module_forward_hook(lambda *args: None)
    elif damage == "callable":
        monkeypatch.setattr(model, "forward", lambda *args: None)
    elif damage == "decoder_code":
        original = base._CAPTURE_DECODE
        monkeypatch.setattr(original, "__code__", (lambda *args, **kwargs: None).__code__)
    else:
        runtime["named"]["start.bias"] = torch.nn.Parameter(runtime["named"]["start.bias"].detach().clone())
    try:
        with pytest.raises(ValueError):
            subject.captured_inference(runtime, checkpoint, _source_rows(case), **kwargs)
        assert runtime["model_forwards"] == 0
        assert all(v == 0 for v in model._conditions_forward_accounting.values())
    finally:
        if handle is not None:
            handle.remove()


@pytest.mark.parametrize("damage", ["source", "counter"])
def test_v2_capture_closing_fence_retains_context_and_refuses_failed_runtime(case, monkeypatch, damage):
    import torch
    kwargs, checkpoint, runtime = _capture_setup(torch, case)
    rows = _source_rows(case)
    original_copy = subject._copy
    rng = torch.get_rng_state().clone()

    def mutate_late(value):
        detached = original_copy(value)
        if isinstance(value, dict) and value.get("schema") == subject.CAPTURE_SCHEMA:
            if damage == "source":
                rows[0]["source_text"] += " changed after capture"
            else:
                runtime["model_forwards"] += 1
        return detached

    monkeypatch.setattr(subject, "_copy", mutate_late)
    with torch.no_grad():
        with pytest.raises(ValueError):
            subject.captured_inference(runtime, checkpoint, rows, **kwargs)
        assert torch.is_grad_enabled() is False and torch.equal(rng, torch.get_rng_state())
    assert runtime["_capture_failed"] is True
    assert not runtime["model"].training and not runtime["model"]._forward_hooks
    assert all(p.grad is None for p in runtime["named"].values())
    count = dict(runtime["model"]._conditions_forward_accounting)
    with pytest.raises(ValueError, match="prior capture failed"):
        subject.captured_inference(runtime, checkpoint, _source_rows(case), **kwargs)
    assert runtime["model"]._conditions_forward_accounting == count


def test_v2_capture_accepts_a_restored_updated_v2_checkpoint_without_updating_it(case):
    import torch
    kwargs = _kwargs(case)
    initial = subject.build_checkpoint(**kwargs)
    updated, report = subject.run_admitted_updates(initial, torch=torch, **kwargs, max_steps=1, max_seconds=32)
    runtime = subject.restore_optimizer(torch, updated, **kwargs)
    before = base._checkpoint_raw(base.f18.span._pack(runtime["model"], runtime["optimizer"]))
    captured = subject.captured_inference(runtime, updated, _source_rows(case), **kwargs)
    assert captured["inference"]["checkpoint_sha256"] == subject.checkpoint_digest(updated)
    assert captured["inference"]["model_state_sha256"] == updated["model_state_sha256"]
    assert captured["actual_source_forwards"] == 2 and runtime["optimizer_steps"] == 1
    assert report["optimizer_steps"] == 1
    assert before == base._checkpoint_raw(base.f18.span._pack(runtime["model"], runtime["optimizer"]))
    subject.validate_checkpoint(updated, **kwargs)
    _assert_partition(torch, runtime, case["state"], steps=1)
