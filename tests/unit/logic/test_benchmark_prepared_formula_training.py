"""Fail-closed controls for the paired throughput benchmark, without training."""
import copy
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def runner():
    path=Path(__file__).resolve().parents[3]/"scripts/ops/legal_ir/benchmark_prepared_formula_training.py"
    spec=importlib.util.spec_from_file_location("prepared_benchmark_test",path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def observed(runner):
    return {"checkpoint":{"model_state":{"weight":1.},"optimizer_state":{"moment":.5},"progress":{"optimizer_steps":1000}},
            "report":{"optimizer_steps":1000,"batch_losses":[{"token_count":93,"token_cross_entropy":.1} for _ in range(1000)],
                      "parameter_evidence":{"projection":{"gradient_norm_max":.5}},
                      "formula_projection_gradient_norm_max":.4,
                      "training_before":{"complete":True},"training_after":{"complete":True},
                      "tuning":{"complete":True},"progress":{"optimizer_steps":1000},"stopped_reason":"optimizer_step_budget"}}


def test_rates_count_optimizer_presentations_and_actual_tokens(runner):
    value=runner.rates(observed(runner)["report"],10.,6)
    assert value["optimizer_steps_per_second"]==100
    assert value["row_presentations"]==6000
    assert value["row_presentations_per_second"]==600
    assert value["actual_loss_tokens"]==93000
    assert value["loss_tokens_per_second"]==9300


@pytest.mark.parametrize("elapsed",[0.,-1.,float("nan"),float("inf"),True])
def test_nonfinite_or_invalid_timing_is_not_faster_training(runner,elapsed):
    with pytest.raises(RuntimeError,match="wall time"):
        runner.rates(observed(runner)["report"],elapsed,6)


@pytest.mark.parametrize("change",["steps","history","metrics","tokens"])
def test_incomplete_training_does_not_enter_throughput_comparison(runner,change):
    report=observed(runner)["report"]
    if change=="steps": report["optimizer_steps"]-=1
    if change=="history": report["batch_losses"].pop()
    if change=="metrics": report["training_after"]["complete"]=False
    if change=="tokens":
        for row in report["batch_losses"]: row["token_count"]=0
    with pytest.raises(RuntimeError): runner.rates(report,10.,6)


@pytest.mark.parametrize("change",["weight","adam","progress","loss","gradient"])
def test_numeric_identity_requires_weights_moments_progress_losses_and_telemetry(runner,change):
    left=observed(runner);right=copy.deepcopy(left)
    if change=="weight": right["checkpoint"]["model_state"]["weight"]+=.001
    if change=="adam": right["checkpoint"]["optimizer_state"]["moment"]+=.001
    if change=="progress": right["checkpoint"]["progress"]["optimizer_steps"]-=1
    if change=="loss": right["report"]["batch_losses"][0]["token_cross_entropy"]+=.001
    if change=="gradient": right["report"]["formula_projection_gradient_norm_max"]+=.001
    with pytest.raises(RuntimeError,match="differs"):
        runner.require_exact(left,right)


def test_input_artifact_hash_and_size_are_both_verified(runner,tmp_path):
    ref=runner.write(tmp_path/"input.json",{"training_only":True})
    assert runner.read_reference(ref)=={"training_only":True}
    (tmp_path/"input.json").write_text("{}")
    with pytest.raises(RuntimeError,match="changed"):
        runner.read_reference(ref)


def test_equal_zero_step_timeouts_cannot_pass_resume_evidence(runner):
    original=observed(runner)
    original["report"]["optimizer_steps"]=0
    with pytest.raises(RuntimeError,match="did not execute"):
        runner.require_resumed_update(original,copy.deepcopy(original))


def test_wrong_profile_pin_fails_before_head_or_inputs_open(runner,tmp_path,monkeypatch):
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES","")
    runner.write(tmp_path/"report.json",{})
    monkeypatch.setattr(runner,"read_reference",lambda ref:pytest.fail("read inputs before profile pin verification"))
    with pytest.raises(RuntimeError,match="profile receipt differs"):
        runner.run(tmp_path,tmp_path/"output","0"*64)
    assert not (tmp_path/"output").exists()
