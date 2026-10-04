"""Synthetic private-step replay; no corpus, weights download, or proof claim."""
from copy import deepcopy
import json
import random

import pytest

torch=pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_gradient_replay as subject
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core
from ipfs_datasets_py.logic.formalization.autoencoder import long_span_count_exposure_training as previous
from ipfs_datasets_py.logic.formalization.autoencoder import long_span_gradient_trace_training as capture
from .test_long_span_cardinality_training import setup


@pytest.fixture(autouse=True)
def one_cpu():
    before=torch.get_num_threads();torch.set_num_threads(1)
    yield
    torch.set_num_threads(before)


def captured(exposure="current_stage"):
    template,_,rows,_,options=setup()
    config=core._config({**options["config"],"alpha":0.,"max_grad_norm":.1})
    work=deepcopy(template);work.train()
    optimizer=torch.optim.AdamW([p for p in work.parameters() if p.requires_grad],
        lr=config["learning_rate"],weight_decay=config["weight_decay"],foreach=False)
    refs=options["training_references"];codec=options["codec"];transform=options["input_transform"]
    weights=previous.reference_weights(rows,refs,codec,strategy="semantic_fields",validate_rule=options["validate_rule"])
    labels_by_id=previous._count_labels(refs)
    observer=capture.GradientTraceObserver(dict(enabled=True,threshold=0.,top_k=2,module_summaries=True),
        options=config,input_transform=transform,codec=codec,cardinality_weight=.25,
        strategy="semantic_fields",count_exposure=exposure)
    generator=torch.Generator().manual_seed(1729)
    for step in range(2):
        part=rows;count_part=rows if exposure=="current_stage" else list(reversed(rows))
        data,labels=core._batch(torch,part,transform)
        token_weights=torch.tensor([weights[row["id"]]+[0.]*(labels.shape[1]-len(weights[row["id"]]))
            for row in part],dtype=torch.float32)[:,1:]
        optimizer.zero_grad(set_to_none=True)
        projected,logits=core._logits(torch,work,data,labels[:,:-1],len(codec["target_vocabulary"]))
        ce=torch.nn.functional.cross_entropy(logits.flatten(0,1),labels[:,1:].flatten(),
            ignore_index=0,reduction="none").reshape(labels.shape[0],-1)
        plain=ce.sum()/(labels[:,1:]!=0).sum()
        weighted=(ce*token_weights).sum()/token_weights.sum()
        mse=(projected-data).square().mean()*transform["scale"]**2
        count_projected=projected if exposure=="current_stage" else work.project(previous._source_batch(torch,count_part,transform))
        targets=torch.tensor([labels_by_id[row["id"]] for row in count_part],dtype=torch.long)
        count=torch.nn.functional.cross_entropy(previous._count_logits(torch,work,count_projected),targets)
        objective=weighted+config["reconstruction_weight"]*mse
        objective=objective+.25*count
        objective.backward()
        norm=torch.nn.utils.clip_grad_norm_([p for p in work.parameters() if p.requires_grad],.1,error_if_nonfinite=True)
        ticket=observer.before_step(work,optimizer,generator,
            metadata=dict(optimizer_step_before=step,epoch=step+1,stage="synthetic",stage_epoch=step+1),
            decoder_rows=part,count_rows=count_part,weights=weights,count_targets=targets,
            losses=dict(weighted_token_ce=weighted,token_ce=plain,count_ce=count,mse=mse,objective=objective),
            preclip_norm=norm,count_selector=None)
        optimizer.step();observer.after_step(ticket,work,optimizer)
    event=next(event for event in observer.events if event["optimizer_step_before"]==1)
    return template,event,rows,refs,options


def replay(values,**extra):
    model,event,rows,refs,options=values
    return subject.replay_event(model,event,rows,refs,options["codec"],options["input_transform"],
        validate_rule=options["validate_rule"],max_seconds=20.,**extra)


@pytest.mark.parametrize("exposure",["current_stage","balanced_all"])
def test_exact_step_replays_before_separate_branch_attribution(exposure):
    values=captured(exposure);model,event,_,_,_=values
    assert event["optimizer_state_dict"]["state"]  # nontrivial Adam moments
    torch_before=torch.get_rng_state().clone();python_before=random.getstate()
    model_before=core.tensor_digest(model);grad_before=subject.gradient_digest(model)
    result=replay(values)
    assert result["complete"] and result["full_step_exact"]
    assert result["full_loss_exact"] and result["preclip_norm_exact"] and result["clipped_gradient_digest_exact"]
    assert result["poststep_model_digest_exact"] and result["poststep_optimizer_digest_exact"]
    assert result["attribution"]["branches_reconcile"]
    assert result["attribution_valid"] is True
    assert result["frozen_reconstruction_branch"]==dict(requires_grad=False,gradient_norm=0.,cosine=None)
    groups=result["attribution"]["groups"]
    assert groups["decoder"]["weighted_token_ce_norm"]>0
    assert groups["decoder"]["quarter_weight_count_ce_norm"]==0
    assert groups["decoder"]["weighted_branch_cosine"] is None
    assert groups["count_head"]["weighted_token_ce_norm"]==0
    assert groups["count_head"]["quarter_weight_count_ce_norm"]>0
    assert groups["condition"]["quarter_weight_count_ce_norm"]>0
    global_summary=result["attribution"]["global_summary"]
    assert global_summary["combined_norm"]**2==pytest.approx(sum(group["combined_norm"]**2 for group in groups.values()))
    assert global_summary["weighted_branch_dot"]==pytest.approx(sum(group["weighted_branch_dot"] for group in groups.values()))
    assert model_before==core.tensor_digest(model) and grad_before==subject.gradient_digest(model)
    assert torch.equal(torch_before,torch.get_rng_state()) and python_before==random.getstate()
    assert all(result[key] is False for key in subject.FALSE)
    json.dumps(result,allow_nan=False)


def test_tagged_roundtrip_preserves_integer_optimizer_keys_tuples_and_tensor_bytes():
    values=captured();event=values[1]
    packed=subject.pack_event(event)
    restored=subject.unpack_event(json.loads(json.dumps(packed,allow_nan=False)))
    assert subject.event_digest(restored)==event["event_sha256"]
    assert all(type(key) is int for key in restored["optimizer_state_dict"]["state"])
    assert type(restored["rng_state"]["python"]) is tuple
    assert subject.state_digest(restored)==subject.state_digest(event)
    result=replay((values[0],restored,*values[2:]))
    assert result["full_step_exact"]


def test_digests_preserve_signed_zero_none_and_dictionary_key_types():
    assert subject.state_digest(torch.tensor([0.]))!=subject.state_digest(torch.tensor([-0.]))
    assert subject.state_digest({0:torch.tensor(1.)})!=subject.state_digest({"0":torch.tensor(1.)})
    assert subject.state_digest(None)!=subject.state_digest(torch.zeros(1))


@pytest.mark.parametrize("field,value,reason",[
    ("clipped_gradient_sha256","0"*64,"clipped gradients"),
    ("poststep_tensor_sha256","0"*64,"post-step model"),
    ("poststep_optimizer_sha256","0"*64,"post-step optimizer"),
    ("pre_step_model_sha256","0"*64,"pre-step model"),
    ("pre_step_optimizer_sha256","0"*64,"pre-step optimizer digest"),
    ("preclip_norm",1000.,"preclip norm"),
    ("token_weights_sha256","0"*64,"token weights"),
    ("decoder_batch_sha256","0"*64,"batch bytes"),
    ("count_batch_sha256","0"*64,"batch bytes"),
    ("codec_sha256","0"*64,"codec, transform"),
    ("qualified",True,"qualification authority"),
])
def test_coherently_rehashed_tampering_still_fails_exact_replay(field,value,reason):
    values=list(captured());values[1][field]=value
    values[1]["event_sha256"]=subject.event_digest(values[1])
    before=core.tensor_digest(values[0])
    with pytest.raises(ValueError,match=reason):replay(values)
    assert core.tensor_digest(values[0])==before


def test_plain_digest_tampering_is_rejected_before_step():
    values=list(captured());values[1]["losses"]["objective"]+=1.
    with pytest.raises(ValueError,match="event digest"):replay(values)


def test_rehashed_loss_tampering_fails_before_branch_analysis():
    values=list(captured());values[1]["losses"]["objective"]+=1.
    values[1]["event_sha256"]=subject.event_digest(values[1])
    with pytest.raises(ValueError,match="replay loss"):replay(values)


def test_incomplete_events_remain_archivable_but_never_replayable():
    values=list(captured());event=values[1]
    event.update(complete=False,committed=False,poststep_tensor_sha256=None,
        poststep_optimizer_sha256=None,uncommitted_reason="deadline_before_step")
    event["event_sha256"]=subject.event_digest(event)
    restored=subject.unpack_event(subject.pack_event(event))
    assert restored["complete"] is False and restored["committed"] is False
    with pytest.raises(ValueError,match="complete committed"):subject.validate_gradient_event(restored)
    with pytest.raises(ValueError,match="complete committed"):replay(values)


def test_missing_snapshot_and_nonfinite_values_fail_closed():
    values=list(captured());event=values[1]
    event.pop("optimizer_state_dict")
    with pytest.raises(ValueError,match="closed gradient event"):replay(values)
    with pytest.raises(ValueError,match="finite snapshot"):subject.state_digest(torch.tensor([float("nan")]))


def test_memory_preflight_refuses_before_copying_model(monkeypatch):
    values=captured()
    def forbidden(*args):raise AssertionError("copy occurred before memory preflight")
    monkeypatch.setattr(subject,"deepcopy",forbidden)
    with pytest.raises(ValueError,match="tensor work exceeds"):replay(values,max_memory_bytes=1)


def test_deadline_returns_no_success_and_preserves_caller(monkeypatch):
    values=captured();before=core.tensor_digest(values[0]);times=iter([0.,21.])
    monkeypatch.setattr(subject.time,"monotonic",lambda:next(times))
    with pytest.raises(TimeoutError,match="incomplete analysis"):replay(values)
    assert core.tensor_digest(values[0])==before


def test_deadline_inside_private_forward_restores_rng_and_template(monkeypatch):
    values=captured();before=core.tensor_digest(values[0]);clock=[0.]
    rng=torch.get_rng_state().clone();python_rng=random.getstate()
    original=core._logits
    def expire(*args):
        result=original(*args);clock[0]=21.;return result
    monkeypatch.setattr(core,"_logits",expire)
    monkeypatch.setattr(subject.time,"monotonic",lambda:clock[0])
    with pytest.raises(TimeoutError):replay(values)
    assert core.tensor_digest(values[0])==before
    assert torch.equal(torch.get_rng_state(),rng) and random.getstate()==python_rng


def test_deadline_in_final_integrity_verification_cannot_return_success(monkeypatch):
    values=captured();model=values[0];before=core.tensor_digest(model);clock=[0.];caller_checks=[]
    torch_rng=torch.get_rng_state().clone();python_rng=random.getstate()
    original=subject.gradient_digest
    def digest(value):
        result=original(value)
        if value is model:
            caller_checks.append(1)
            if len(caller_checks)==2:clock[0]=21.
        return result
    monkeypatch.setattr(subject,"gradient_digest",digest)
    monkeypatch.setattr(subject.time,"monotonic",lambda:clock[0])
    with pytest.raises(TimeoutError,match="after final integrity verification"):replay(values)
    assert len(caller_checks)==2 and core.tensor_digest(model)==before
    assert torch.equal(torch.get_rng_state(),torch_rng) and random.getstate()==python_rng


def test_elapsed_time_includes_final_integrity_verification(monkeypatch):
    values=captured();model=values[0];clock=[0.];caller_checks=[]
    original=subject.gradient_digest
    def digest(value):
        result=original(value)
        if value is model:
            caller_checks.append(1)
            if len(caller_checks)==2:clock[0]=7.
        return result
    monkeypatch.setattr(subject,"gradient_digest",digest)
    monkeypatch.setattr(subject.time,"monotonic",lambda:clock[0])
    result=replay(values)
    assert result["elapsed_seconds"]==7. and result["complete"]


def test_cleanup_deadline_does_not_replace_original_replay_failure(monkeypatch):
    values=list(captured());model=values[0];clock=[0.];caller_checks=[]
    values[1]["losses"]["objective"]+=1.
    values[1]["event_sha256"]=subject.event_digest(values[1])
    original=subject.gradient_digest
    def digest(value):
        result=original(value)
        if value is model:
            caller_checks.append(1)
            if len(caller_checks)==2:clock[0]=21.
        return result
    monkeypatch.setattr(subject,"gradient_digest",digest)
    monkeypatch.setattr(subject.time,"monotonic",lambda:clock[0])
    with pytest.raises(ValueError,match="full replay loss differs"):replay(values)
    assert len(caller_checks)==2


def test_nonreconciling_gradients_remain_an_explicit_invalid_attribution():
    report=subject._attribution(torch,{"condition.weight":torch.tensor([1.])},
        {"condition.weight":torch.tensor([1.])},{"condition.weight":torch.tensor([1.])},atol=1e-4,rtol=1e-4)
    assert report["branches_reconcile"] is False
    assert report["status"]=="unreconciled_do_not_claim_additive_attribution"
    assert report["max_absolute_reconciliation_error"]==1.


def test_tampered_tagged_shapes_and_wire_budget_reject():
    values=captured();wire=subject.pack_event(values[1])
    with pytest.raises(ValueError,match="byte limit"):subject.unpack_event(wire,max_bytes=1)
    broken=deepcopy(wire)
    pairs=broken["event"]["pairs"]
    target=next(item for key,item in pairs if key=="model_state_dict")["pairs"][0][1]
    target["shape"]=[1000001]
    with pytest.raises(ValueError,match="geometry exceeds"):subject.unpack_event(broken)


@pytest.mark.parametrize("exposure",["current_stage","balanced_all"])
def test_full_trace_trainer_capture_pack_reload_replay_interoperate(exposure):
    model,_,rows,tune,options=setup()
    result=capture.train(model,rows,tune,cardinality_weight=.25,count_exposure=exposure,
        strategy="semantic_fields",gradient_trace=dict(enabled=True,threshold=0.,top_k=2,module_summaries=True),**options)
    assert result["gradient_events"]
    for captured_event in result["gradient_events"]:
        event=subject.unpack_event(json.loads(json.dumps(subject.pack_event(captured_event))))
        replayed=subject.replay_event(model,event,rows,options["training_references"],options["codec"],
            options["input_transform"],validate_rule=options["validate_rule"],max_seconds=20.)
        assert replayed["full_step_exact"] and replayed["poststep_optimizer_digest_exact"]
        assert replayed["attribution_valid"]


@pytest.mark.parametrize("value",[True,-1.,float("nan"),1.])
def test_attribution_tolerance_cannot_silently_disable_reconciliation(value):
    values=captured()
    with pytest.raises(ValueError,match="attribution tolerances"):replay(values,reconciliation_atol=value)
