"""Synthetic transition-schedule controls; no corpus or qualification evidence."""
from copy import deepcopy
import math
import random

import pytest

torch=pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import long_span_transition_training as subject
from ipfs_datasets_py.logic.formalization.autoencoder import long_span_gradient_trace_training as previous
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_gradient_replay as replay
from .test_long_span_cardinality_training import setup


@pytest.fixture(autouse=True)
def one_cpu():
    old=torch.get_num_threads();torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


def trace():return dict(enabled=True,threshold=0.,top_k=2,module_summaries=True)


@pytest.mark.parametrize("seed",[1729,2718])
@pytest.mark.parametrize("exposure",["current_stage","balanced_all"])
def test_unchanged_matches_prior_weights_adam_history_predictions_and_gates(seed,exposure):
    model,_,train,tune,options=setup()
    options["curriculum"][0]["epochs"]=4;options["curriculum"][1]["epochs"]=12
    options["config"].update(seed=seed,max_optimizer_steps=32,validation_interval=4,max_grad_norm=.005,patience=0)
    original=deepcopy((train,tune,options));before=core.tensor_digest(model)
    old=previous.train(model,train,tune,cardinality_weight=.25,count_exposure=exposure,
        strategy="semantic_fields",gradient_trace=trace(),**options)
    new=subject.train(model,train,tune,cardinality_weight=.25,count_exposure=exposure,
        strategy="semantic_fields",gradient_trace=trace(),transition_schedule="unchanged",**options)
    for key in ("state_dict","last_complete_attempt_state_dict"):
        assert replay.state_digest(old[key])==replay.state_digest(new[key])
    for key in ("predictions","last_complete_attempt_predictions"):assert old[key]==new[key]
    for key in ("history","stage_reports","gradient_norms","selected_epoch","selected_weights_sha256",
            "last_complete_attempt_weights_sha256","optimizer_steps","row_presentations",
            "valid_target_token_presentations","count_training_presentations_by_class","count_mean_loss_exposure_by_class"):
        assert old["report"][key]==new["report"][key]
    for left,right in zip(old["gradient_events"],new["gradient_events"]):
        for key in ("pre_step_model_sha256","pre_step_optimizer_sha256","poststep_tensor_sha256",
                "poststep_optimizer_sha256","clipped_gradient_sha256","losses"):
            assert left[key]==right[key]
    updates=new["report"]["transition_updates"]
    assert updates["ramp_start_optimizer_step"] is None and updates["ramp_committed_updates"]==0
    assert len(updates["steps"])==16 and not updates["uncommitted_steps"]
    assert all(row["ramp_factor"]==1. and row["committed"] for row in updates["steps"])
    assert all(new["report"][key] is False for key in subject.FALSE)
    assert core.tensor_digest(model)==before and (train,tune,options)==original


def expanded_options():
    model,_,train,tune,options=setup()
    options["curriculum"]=[dict(name="short",training_ids=[train[0]["id"]],epochs=1),
        dict(name="same",training_ids=[train[0]["id"]],epochs=1),
        dict(name="expanded",training_ids=[row["id"] for row in train],epochs=24)]
    options["config"].update(max_optimizer_steps=40,patience=0,validation_interval=1)
    return model,train,tune,options


def test_ramp_starts_at_first_proper_expansion_and_only_spans_twenty_commits():
    model,train,tune,options=expanded_options()
    result=subject.train(model,train,tune,cardinality_weight=.25,count_exposure="balanced_all",
        strategy="semantic_fields",transition_schedule="first_expansion_ramp20",**options)
    data=result["report"]["transition_updates"];steps=data["steps"]
    assert result["report"]["optimizer_steps"]==26
    assert data["ramp_start_optimizer_step"]==2 and data["ramp_stage"]=="expanded"
    assert data["ramp_committed_updates"]==20
    assert [row["ramp_index"] for row in steps]==[None,None]+list(range(20))+[None]*4
    assert [row["ramp_factor"] for row in steps[2:22]]==[.1+.9*j/19 for j in range(20)]
    for row in steps:
        assert row["effective_learning_rates"]==[base*row["ramp_factor"] for base in row["scheduler_base_learning_rates"]]
        norms=row["update_norms"]
        assert norms["global_summary"]["actual_update_norm"]>=0
        for key in ("projection_down","projection_up"):
            assert norms["groups"][key]["actual_update_norm"]==0.
    assert steps[0]["update_norms"]["groups"]["source_to_embedding"]["parameter_norm_before"]==0.
    assert steps[0]["update_norms"]["groups"]["source_to_embedding"]["update_to_parameter_ratio"] is None
    assert result["report"]["frozen_parameters_verified"]
    assert result["report"]["optimizer_instance_count"]==1


def test_scheduler_receives_base_not_ramped_rate_and_ramp_does_not_restart():
    parameter=torch.nn.Parameter(torch.ones(1));optimizer=torch.optim.AdamW([parameter],lr=.01)
    controller=subject.TransitionSchedule("first_expansion_ramp20",optimizer)
    scheduler=torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer,patience=0,factor=.5)
    controller.enter_stage(["a"],0,"first");controller.enter_stage(["a"],1,"same")
    assert controller.ramp_start is None
    controller.enter_stage(["a","b"],2,"expanded")
    model=torch.nn.Linear(1,1)
    ticket=controller.before_step(model,optimizer,2,metadata={})
    assert optimizer.param_groups[0]["lr"]==.001
    controller.after_step(ticket,model,optimizer)
    assert optimizer.param_groups[0]["lr"]==.01
    controller.restore_base(optimizer);scheduler.step(1.);controller.observe_scheduler(optimizer)
    controller.restore_base(optimizer);scheduler.step(2.);controller.observe_scheduler(optimizer)
    assert controller.base==[.005]
    controller.enter_stage(["a","b","c"],3,"another_expansion")
    ticket=controller.before_step(model,optimizer,3,metadata={})
    assert ticket[0]["ramp_index"]==1
    assert optimizer.param_groups[0]["lr"]==.005*(.1+.9/19)
    controller.abort_step(ticket,optimizer,"synthetic_abort")
    assert optimizer.param_groups[0]["lr"]==.005
    assert controller.factor_at(3)==(.1+.9/19,1)
    assert controller.factor_at(22)==(1.,None)


def test_actual_update_norms_use_float64_parameter_differences_not_gradients():
    model=torch.nn.Linear(2,1,bias=True)
    with torch.no_grad():model.weight.copy_(torch.tensor([[3.,4.]]));model.bias.zero_()
    before={name:p.detach().clone() for name,p in model.named_parameters()}
    with torch.no_grad():model.weight.add_(torch.tensor([[.5,-.25]]));model.bias.add_(2.)
    for p in model.parameters():p.grad=torch.full_like(p,999.)
    result=subject.TransitionSchedule._update_norms(before,model)
    assert result["global_summary"]["parameter_norm_before"]==5.
    assert result["global_summary"]["actual_update_norm"]==pytest.approx(math.sqrt(.5**2+.25**2+2.**2))
    assert result["global_summary"]["update_to_parameter_ratio"]==pytest.approx(math.sqrt(4.3125)/5.)


def test_ramped_capture_remains_exactly_replayable_before_base_restoration():
    model,train,tune,options=expanded_options()
    options["curriculum"][-1]["epochs"]=1
    # Retain all three toy events to guarantee observing the first ramped step.
    configuration={**trace(),"top_k":4}
    result=subject.train(model,train,tune,cardinality_weight=.25,count_exposure="balanced_all",
        strategy="semantic_fields",transition_schedule="first_expansion_ramp20",gradient_trace=configuration,**options)
    event=next(event for event in result["gradient_events"] if event["optimizer_step_before"]==2)
    assert event["optimizer_state_dict"]["param_groups"][0]["lr"]==.001*.1
    observed=replay.replay_event(model,event,train,options["training_references"],options["codec"],
        options["input_transform"],validate_rule=options["validate_rule"],max_seconds=20.)
    assert observed["poststep_optimizer_digest_exact"] and observed["attribution_valid"]
    assert result["report"]["transition_updates"]["scheduler_base_learning_rates_final"]==[.001]


def test_deadline_after_parameter_copy_never_commits_an_update(monkeypatch):
    model,train,tune,options=expanded_options();clock=[0.]
    monkeypatch.setattr(subject.time,"monotonic",lambda:clock[0])
    original=subject.TransitionSchedule.before_step
    def expire(self,*args,**kwargs):
        result=original(self,*args,**kwargs);clock[0]=21.;return result
    monkeypatch.setattr(subject.TransitionSchedule,"before_step",expire)
    result=subject.train(model,train,tune,cardinality_weight=.25,transition_schedule="first_expansion_ramp20",**options)
    report=result["report"];updates=report["transition_updates"]
    assert report["optimizer_steps"]==report["count_training_row_presentations"]==0
    assert updates["steps"]==[] and len(updates["uncommitted_steps"])==1
    assert updates["uncommitted_steps"][0]["uncommitted_reason"]=="deadline_after_parameter_copy"
    assert not updates["uncommitted_steps"][0]["committed"]
    assert report["last_complete_attempt_weights_sha256"]==core.tensor_digest(model)


def test_deadline_after_update_measurement_counts_committed_step_but_no_stale_export(monkeypatch):
    model,train,tune,options=expanded_options();clock=[0.]
    monkeypatch.setattr(subject.time,"monotonic",lambda:clock[0])
    original=subject.TransitionSchedule.after_step
    def expire(self,*args,**kwargs):
        original(self,*args,**kwargs);clock[0]=21.
    monkeypatch.setattr(subject.TransitionSchedule,"after_step",expire)
    result=subject.train(model,train,tune,cardinality_weight=.25,transition_schedule="first_expansion_ramp20",**options)
    report=result["report"]
    assert report["optimizer_steps"]==1 and report["stopped_reason"]=="deadline_after_optimizer_step"
    assert report["transition_updates"]["steps"][0]["committed"]
    assert result["last_complete_attempt_state_dict"] is None
    assert report["last_complete_attempt_weights_sha256"] is None
    assert report["selected_weights_sha256"]==core.tensor_digest(model)


@pytest.mark.parametrize("policy",[None,True,"ramp10","restart_adam",0])
def test_closed_transition_policy_refuses_unplanned_schedules(policy):
    model,_,train,tune,options=setup()
    with pytest.raises(ValueError,match="transition schedule"):
        subject.train(model,train,tune,transition_schedule=policy,**options)


def test_update_observer_does_not_add_backward_clipping_or_rng_consumption(monkeypatch):
    model,_,train,tune,options=setup();counts=dict(backward=0,clip=0)
    backward,clip=torch.Tensor.backward,torch.nn.utils.clip_grad_norm_
    def count_backward(self,*args,**kwargs):counts["backward"]+=1;return backward(self,*args,**kwargs)
    def count_clip(*args,**kwargs):counts["clip"]+=1;return clip(*args,**kwargs)
    monkeypatch.setattr(torch.Tensor,"backward",count_backward);monkeypatch.setattr(torch.nn.utils,"clip_grad_norm_",count_clip)
    before=torch.get_rng_state().clone();python_before=random.getstate()
    result=subject.train(model,train,tune,cardinality_weight=.25,transition_schedule="first_expansion_ramp20",**options)
    assert counts==dict(backward=2,clip=2)
    assert torch.equal(before,torch.get_rng_state()) and python_before==random.getstate()
    assert len(result["report"]["transition_updates"]["steps"])==2


def test_update_memory_preflight_refuses_before_private_model_copy(monkeypatch):
    model,_,train,tune,options=setup();options["config"].update(max_memory_bytes=1048576,max_optimizer_steps=100000)
    original=subject.deepcopy
    def checked(value):
        assert not isinstance(value,torch.nn.Module),"model copied before memory refusal"
        return original(value)
    monkeypatch.setattr(subject,"deepcopy",checked)
    with pytest.raises(ValueError,match="trace work exceeds budget"):
        subject.train(model,train,tune,transition_schedule="first_expansion_ramp20",**options)
