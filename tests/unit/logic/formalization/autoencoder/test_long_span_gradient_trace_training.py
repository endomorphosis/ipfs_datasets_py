"""Synthetic live-observer controls; recorded gradients confer no authority."""
from copy import deepcopy
import random

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import long_span_gradient_trace_training as subject
from ipfs_datasets_py.logic.formalization.autoencoder import long_span_count_exposure_training as previous
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_gradient_replay as replay
from .test_long_span_cardinality_training import setup


@pytest.fixture(autouse=True)
def one_cpu():
    old = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


def trace_config(**overrides):
    return dict(dict(enabled=True,threshold=0.,top_k=2,module_summaries=True),**overrides)


@pytest.mark.parametrize("exposure",["current_stage","balanced_all"])
@pytest.mark.parametrize("enabled",[False,True])
def test_observer_preserves_exact_live_updates_and_selection(exposure,enabled):
    model,_,train,tune,options=setup()
    options["curriculum"]=[dict(name="repeated",training_ids=[row["id"] for row in train],epochs=64)]
    options["config"].update(epochs=64,max_optimizer_steps=64,validation_interval=64,max_grad_norm=.005,patience=0)
    old=previous.train(model,train,tune,cardinality_weight=.25,count_exposure=exposure,strategy="semantic_fields",**options)
    new=subject.train(model,train,tune,cardinality_weight=.25,count_exposure=exposure,strategy="semantic_fields",
        gradient_trace=trace_config() if enabled else None,**options)
    for key in ("state_dict","last_complete_attempt_state_dict"):
        assert all(torch.equal(value,new[key][name]) for name,value in old[key].items())
    assert old["predictions"]==new["predictions"]
    assert old["last_complete_attempt_predictions"]==new["last_complete_attempt_predictions"]
    for key in ("optimizer_steps","row_presentations","count_training_presentations_by_class",
                "count_mean_loss_exposure_by_class","selected_epoch","gradient_norms"):
        assert old["report"][key]==new["report"][key]
    for left,right in zip(old["report"]["history"],new["report"]["history"]):
        for key in ("mean_minibatch_ce","mean_minibatch_weighted_ce","mean_minibatch_count_ce",
                    "accepted","rejection_reasons","selected_epoch"):
            assert left[key]==right[key]
    observer=new["report"]["gradient_trace"]
    if enabled:
        assert len(observer["steps"])==64
        eligible=sorted(observer["steps"],key=lambda row:(-row["preclip_norm"],row["optimizer_step_before"]))[:2]
        assert [event["optimizer_step_before"] for event in new["gradient_events"]]==[row["optimizer_step_before"] for row in eligible]
        assert observer["observer_elapsed_seconds"]>=observer["capture_seconds"]>=0
        assert observer["total_observer_seconds"] == (observer["observer_elapsed_seconds"]
            +observer["initialization_seconds"]+observer["report_construction_seconds"])
    else:
        assert observer["steps"]==new["gradient_events"]==new["uncommitted_gradient_events"]==[]
        assert observer["observer_elapsed_seconds"]==0


def test_capture_binds_private_prestep_moments_and_poststep_model_optimizer():
    model,_,train,tune,options=setup()
    before=core.tensor_digest(model)
    inputs=deepcopy((train,tune,options))
    result=subject.train(model,train,tune,cardinality_weight=.25,gradient_trace=trace_config(),**options)
    events=sorted(result["gradient_events"],key=lambda event:event["optimizer_step_before"])
    assert len(events)==2 and [event["optimizer_step_before"] for event in events]==[0,1]
    first,second=events
    assert first["pre_step_model_sha256"]==before
    assert first["optimizer_state_dict"]["state"]=={}
    assert second["optimizer_state_dict"]["state"]
    assert first["poststep_tensor_sha256"]==second["pre_step_model_sha256"]
    assert first["poststep_optimizer_sha256"]==second["pre_step_optimizer_sha256"]
    assert second["poststep_tensor_sha256"]==result["report"]["last_complete_attempt_weights_sha256"]
    for event in events:
        assert event["complete"] and event["committed"]
        assert replay.validate_gradient_event(event)["valid"]
        assert replay.state_digest(event["optimizer_state_dict"])==event["pre_step_optimizer_sha256"]
        assert replay.event_digest(event)==event["event_sha256"]
        assert event["trainable_parameter_names"]==[name for name,p in model.named_parameters() if p.requires_grad]
        assert event["model_state_dict"][next(iter(event["model_state_dict"]))].data_ptr()!=next(model.parameters()).data_ptr()
        assert all(type(flag) is bool for flag in event["module_modes"].values())
        assert event["rng_state"]["torch"].dtype==torch.uint8
        assert event["rng_state"]["decoder_generator"].dtype==torch.uint8
        assert event["losses"]["objective"]==pytest.approx(event["losses"]["weighted_token_ce"]
            +.1*event["losses"]["mse"]+.25*event["losses"]["count_ce"],abs=5e-7)
        assert all(group["postclip_l2_norm"]>=0 for group in event["postclip_module_summaries"].values())
        assert event["qualified"] is False and event["proof_authority"] is False
    assert core.tensor_digest(model)==before and (train,tune,options)==inputs
    assert all(p.grad is None for p in model.parameters())
    assert not any("model_state_dict" in row for row in result["report"]["gradient_trace"]["captured_event_summaries"])


def test_snapshot_mutation_is_detected_and_cannot_change_other_states():
    model,_,train,tune,options=setup()
    result=subject.train(model,train,tune,cardinality_weight=.25,gradient_trace=trace_config(),**options)
    events=result["gradient_events"]
    before_other=replay.event_digest(events[1])
    selected_hash=replay.state_digest(result["state_dict"])
    caller_hash=core.tensor_digest(model)
    tensor=next(value for value in events[0]["model_state_dict"].values() if value.is_floating_point())
    tensor.reshape(-1)[0]+=1.
    with pytest.raises(ValueError,match="digest"):
        replay.validate_gradient_event(events[0])
    assert replay.event_digest(events[1])==before_other
    assert replay.state_digest(result["state_dict"])==selected_hash
    assert core.tensor_digest(model)==caller_hash


def test_trace_cost_deadline_keeps_uncommitted_snapshot_separate(monkeypatch):
    model,_,train,tune,options=setup()
    clock=[0.]
    monkeypatch.setattr(subject.time,"monotonic",lambda:clock[0])
    original=subject.GradientTraceObserver.before_step
    def expensive_capture(observer,*args,**kwargs):
        ticket=original(observer,*args,**kwargs)
        clock[0]=21.
        return ticket
    monkeypatch.setattr(subject.GradientTraceObserver,"before_step",expensive_capture)
    result=subject.train(model,train,tune,cardinality_weight=.25,gradient_trace=trace_config(),**options)
    report=result["report"]
    assert report["optimizer_steps"]==0 and report["selected_epoch"]==0 and report["stopped_reason"]=="deadline"
    assert report["selected_weights_sha256"]==core.tensor_digest(model)
    assert result["gradient_events"]==[] and len(result["uncommitted_gradient_events"])==1
    event=result["uncommitted_gradient_events"][0]
    assert not event["complete"] and not event["committed"]
    assert event["poststep_tensor_sha256"] is event["poststep_optimizer_sha256"] is None
    assert event["uncommitted_reason"]=="deadline_before_optimizer_step"
    with pytest.raises(ValueError,match="committed"):
        replay.validate_gradient_event(event)
    assert report["count_training_row_presentations"]==0
    assert report["gradient_trace"]["steps"][0]["committed"] is False


def test_strict_threshold_excludes_equal_norm_and_preserves_earliest_ties(monkeypatch):
    # Controlled norm-return values exercise observer retention only; actual
    # clip arithmetic remains unchanged and these packets are not replay claims.
    model,_,train,tune,options=setup()
    options["curriculum"]=[dict(name="retention",training_ids=[row["id"] for row in train],epochs=5)]
    options["config"].update(epochs=5,max_optimizer_steps=5,validation_interval=5)
    values=iter([1.,3.,3.,2.,5.])
    original=torch.nn.utils.clip_grad_norm_
    def controlled_norm(*args,**kwargs):
        original(*args,**kwargs)
        return torch.tensor(next(values))
    monkeypatch.setattr(torch.nn.utils,"clip_grad_norm_",controlled_norm)
    result=subject.train(model,train,tune,cardinality_weight=.25,
        gradient_trace=trace_config(threshold=1.,top_k=2),**options)
    events=result["gradient_events"]
    assert [(event["preclip_norm"],event["optimizer_step_before"]) for event in events]==[(5.,4),(3.,1)]
    observer=result["report"]["gradient_trace"]
    assert observer["qualifying_captures_created"]==3 and observer["displaced_captures"]==1
    assert "captured_event_sha256" not in observer["steps"][0]
    assert len(events)==2 and not result["uncommitted_gradient_events"]
    assert observer["retained_tensor_bytes"]==sum(event["captured_tensor_bytes"] for event in events)
    assert observer["peak_snapshot_tensor_bytes"]>=observer["retained_tensor_bytes"]


def test_disabled_trace_performs_no_capture_hashes_or_extra_backwards(monkeypatch):
    model,_,train,tune,options=setup()
    def forbidden(*args,**kwargs):
        raise AssertionError("disabled observer performed capture work")
    monkeypatch.setattr(replay,"gradient_digest",forbidden)
    monkeypatch.setattr(replay,"event_digest",forbidden)
    monkeypatch.setattr(subject.GradientTraceObserver,"before_step",forbidden)
    result=subject.train(model,train,tune,cardinality_weight=.25,**options)
    assert result["report"]["optimizer_steps"]==2 and result["gradient_events"]==[]


def test_no_extra_live_backward_or_clip_calls_and_rng_states_unchanged(monkeypatch):
    model,_,train,tune,options=setup()
    counts={"backward":0,"clip":0}
    backward,clip=torch.Tensor.backward,torch.nn.utils.clip_grad_norm_
    def counted_backward(self,*args,**kwargs):
        counts["backward"]+=1
        return backward(self,*args,**kwargs)
    def counted_clip(*args,**kwargs):
        counts["clip"]+=1
        return clip(*args,**kwargs)
    monkeypatch.setattr(torch.Tensor,"backward",counted_backward)
    monkeypatch.setattr(torch.nn.utils,"clip_grad_norm_",counted_clip)
    rng,python=torch.get_rng_state().clone(),random.getstate()
    result=subject.train(model,train,tune,cardinality_weight=.25,gradient_trace=trace_config(),**options)
    assert counts==dict(backward=2,clip=2)
    assert torch.equal(rng,torch.get_rng_state()) and python==random.getstate()
    assert not result["report"]["gradient_trace"]["additional_backwards_in_live_path"]


@pytest.mark.parametrize("change",[
    lambda value:value.update(extra=True),lambda value:value.pop("threshold"),
    lambda value:value.update(enabled=1),lambda value:value.update(module_summaries=0),
    lambda value:value.update(threshold=True),lambda value:value.update(threshold=float("nan")),
    lambda value:value.update(threshold=float("inf")),lambda value:value.update(threshold=-1.),
    lambda value:value.update(top_k=0),lambda value:value.update(top_k=5),lambda value:value.update(top_k=True),
])
def test_closed_bounded_trace_configuration(change):
    model,_,train,tune,options=setup()
    config=trace_config();change(config)
    with pytest.raises(ValueError,match="gradient trace"):
        subject.train(model,train,tune,gradient_trace=config,**options)


def test_trace_memory_preflight_precedes_model_and_snapshot_copy(monkeypatch):
    model,_,train,tune,options=setup()
    options["config"].update(max_memory_bytes=1048576,max_optimizer_steps=100000)
    original=subject.deepcopy
    def checked(value):
        assert not isinstance(value,torch.nn.Module),"model cloned before trace memory refusal"
        return original(value)
    monkeypatch.setattr(subject,"deepcopy",checked)
    with pytest.raises(ValueError,match="tensor and trace work exceeds budget"):
        subject.train(model,train,tune,gradient_trace=trace_config(top_k=4),**options)
