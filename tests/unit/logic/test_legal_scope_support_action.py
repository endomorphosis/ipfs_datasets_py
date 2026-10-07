"""Bounded CPU fixtures for residual training, frozen class and exact resume."""
from copy import deepcopy
from hashlib import sha256
import json

import pytest
import torch

from ipfs_datasets_py.logic.formalization.autoencoder import legal_scope_span_decoder as span
from ipfs_datasets_py.logic.formalization.autoencoder import legal_scope_trigger_readout as trigger
from ipfs_datasets_py.logic.formalization.autoencoder import legal_scope_support_action as head

SOURCE = "cedar must move brick when chalk fades."


def digest(source): return sha256(source.encode()).hexdigest()


@pytest.fixture(scope="module")
def parent_bytes():
    donor = span.ScopeSpanDecoder(span.ScopeSpanDecoderConfig(seed=11, byte_dim=4, byte_hidden=4,
        token_dim=8, token_hidden=32, head_hidden=8))
    with torch.no_grad(): donor.support_head.bias.fill_(-5.)
    optimizer = span.make_scope_span_optimizer(donor)
    span.train_scope_span_step(donor, optimizer, [span.ScopeSpanExample(SOURCE, False)])
    donor.eval()
    raw = json.dumps(span.save_scope_span_checkpoint(donor, optimizer, steps=1), sort_keys=True).encode()
    parent = trigger.FrozenTriggerReadout(raw, expected_donor_sha256=sha256(raw).hexdigest(),
        config=trigger.TriggerReadoutConfig(seed=21, mode="predicted_trigger", hidden=64))
    adapter_optimizer = trigger.make_trigger_readout_optimizer(parent)
    trigger.train_trigger_readout_step(parent, adapter_optimizer, [trigger.TriggerReadoutExample(SOURCE, True, "O")])
    parent.eval()
    return json.dumps(trigger.save_trigger_readout_checkpoint(parent, adapter_optimizer, steps=1),
                      ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def model_from(raw, kind="linear"):
    return head.FrozenSupportAction(raw, expected_parent_sha256=sha256(raw).hexdigest(),
                                   config=head.SupportActionConfig(seed=31, head_kind=kind, hidden=32))


def positives():
    return [head.SupportActionExample(SOURCE, True, [11, 15]),
            head.SupportActionExample("acorn may cross gate.", True, [10, 15])]


def mixed(): return positives() + [head.SupportActionExample("map and ink", False)]


def equal_outputs(left, right, include_trainable=True):
    for key in ("support", "modality", "presence"):
        if include_trainable or key != "support": assert torch.equal(left[key], right[key]), key
    for key in ("start", "end"):
        for facet in span.FACETS:
            if include_trainable or facet != "action": assert torch.equal(left[key][facet], right[key][facet]), (key, facet)


def reseal(checkpoint):
    checkpoint["checkpoint_sha256"] = sha256(span._canonical({k:v for k,v in checkpoint.items()
                                                            if k != "checkpoint_sha256"})).hexdigest()
    return checkpoint


@pytest.mark.parametrize("kind,parameters", [("linear",195), ("mlp",6339)])
def test_zero_residual_parent_parity_fresh_Adam_rng_and_parameter_counts(parent_bytes, kind, parameters):
    rng = torch.random.get_rng_state().clone()
    parent, old_optimizer, steps = trigger.restore_trigger_readout_checkpoint(json.loads(parent_bytes))
    model = model_from(parent_bytes, kind)
    assert torch.equal(rng, torch.random.get_rng_state())
    assert steps == model.parent_steps == 1 and model.feature_width == 64
    assert sum(p.numel() for p in model.heads.parameters()) == parameters
    assert sum(p.numel() for p in model.parameters() if p.requires_grad) == parameters
    assert all(not p.requires_grad and p.grad is None for p in model._parent.parameters())
    optimizer = head.make_support_action_optimizer(model)
    assert not optimizer.state and old_optimizer.state
    assert [id(p) for p in optimizer.param_groups[0]["params"]] == [id(p) for p in model.heads.parameters()]
    batch, _ = span._encoded_sources([SOURCE, "é may go."])
    with torch.no_grad(): equal_outputs(parent(*batch), model(*batch))
    original = trigger.predict_trigger_readout(parent, SOURCE, "rule", expected_source_sha256=digest(SOURCE))
    result = head.predict_support_action(model, SOURCE, "rule", expected_source_sha256=digest(SOURCE))
    for key in ("status","prediction","proposal","blockers","raw_prediction","modality_logits","support_probability","support_threshold"):
        assert result.get(key) == original.get(key), key
    assert torch.equal(rng, torch.random.get_rng_state())
    assert head.save_support_action_checkpoint(model, optimizer, steps=0, action_steps=0)["optimizer"]["state"] == {}


@pytest.mark.parametrize("kind", ["linear", "mlp"])
def test_new_forward_never_calls_old_frozen_parent_contract(parent_bytes, kind):
    model = model_from(parent_bytes, kind)
    def denied(*_args, **_kwargs): pytest.fail("old frozen parent forward/assert/save contract invoked")
    model._parent.forward = denied
    model._parent._assert_frozen = denied
    batch, _ = span._encoded_sources([SOURCE])
    output = model(*batch)
    assert set(output) == {"support","modality","presence","start","end"}
    head.train_support_action_step(model, head.make_support_action_optimizer(model), mixed())


@pytest.mark.parametrize("kind", ["linear", "mlp"])
def test_support_action_updates_leave_parent_class_and_other_facets_exact(parent_bytes, kind):
    model = model_from(parent_bytes, kind)
    optimizer = head.make_support_action_optimizer(model)
    batch, _ = span._encoded_sources([SOURCE, "oak may move."])
    before = model(*batch); parent_state = deepcopy(model._parent.state_dict())
    result = head.train_support_action_step(model, optimizer, mixed())
    assert result["optimizer_step_executed"] and result["action_optimizer_step_executed"]
    assert (result["supported_examples"], result["unsupported_examples"], result["encoded_examples"]) == (2,1,3)
    after = model(*batch); equal_outputs(before, after, include_trainable=False)
    assert not torch.equal(before["support"], after["support"])
    assert not torch.equal(before["start"]["action"], after["start"]["action"])
    assert not torch.equal(before["end"]["action"], after["end"]["action"])
    assert all(torch.equal(v, parent_state[n]) for n,v in model._parent.state_dict().items())
    assert all(p.grad is None for p in model._parent.parameters())
    assert all(float(state["step"]) == 1 for state in optimizer.state.values())
    assert set(optimizer.state) == set(model.heads.parameters())


@pytest.mark.parametrize("kind", ["linear", "mlp"])
def test_negative_batch_updates_support_with_action_grads_moments_weights_idle(parent_bytes, kind):
    model = model_from(parent_bytes, kind)
    optimizer = head.make_support_action_optimizer(model, weight_decay=.5)
    negative = [head.SupportActionExample("map and ink", False)]
    first = head.train_support_action_step(model, optimizer, negative)
    assert first["optimizer_step_executed"] and not first["action_optimizer_step_executed"] and first["action_loss"] == 0.
    assert set(optimizer.state) == set(model.heads["support"].parameters())
    head.save_support_action_checkpoint(model, optimizer, steps=1, action_steps=0)
    head.train_support_action_step(model, optimizer, mixed())
    prior = head.save_support_action_checkpoint(model, optimizer, steps=2, action_steps=1)
    support_before = deepcopy(model.heads["support"].state_dict())
    inactive = {p:deepcopy(optimizer.state[p]) for name in ("action_start","action_end") for p in model.heads[name].parameters()}
    action_weights = {name:deepcopy(model.heads[name].state_dict()) for name in ("action_start","action_end")}
    result = head.train_support_action_step(model, optimizer, negative)
    assert result["supported_examples"] == 0 and result["unsupported_examples"] == result["encoded_examples"] == 1
    assert not result["action_optimizer_step_executed"]
    assert any(not torch.equal(v,support_before[n]) for n,v in model.heads["support"].state_dict().items())
    for name in action_weights:
        assert all(torch.equal(v,action_weights[name][n]) for n,v in model.heads[name].state_dict().items())
    for parameter,state in inactive.items():
        assert parameter.grad is None
        assert all(torch.equal(v,optimizer.state[parameter][k]) for k,v in state.items())
    current = head.save_support_action_checkpoint(model, optimizer, steps=3, action_steps=1)
    assert current["parent"] == prior["parent"]


@pytest.mark.parametrize("kind", ["linear", "mlp"])
def test_exact_checkpoint_next_step_resume_preserves_parent_mode_and_rng(parent_bytes, kind):
    model = model_from(parent_bytes, kind); optimizer = head.make_support_action_optimizer(model)
    head.train_support_action_step(model, optimizer, mixed())
    head.train_support_action_step(model, optimizer, [head.SupportActionExample("ink and map", False)])
    model.eval(); rng = torch.random.get_rng_state().clone()
    checkpoint = head.save_support_action_checkpoint(model, optimizer, steps=2, action_steps=1)
    checkpoint = json.loads(json.dumps(checkpoint, allow_nan=False))
    assert checkpoint["parent"]["json_utf8"].encode() == parent_bytes
    resumed, fresh_optimizer, steps, action_steps = head.restore_support_action_checkpoint(checkpoint)
    assert (steps,action_steps) == (2,1) and not resumed.training
    assert torch.equal(rng, torch.random.get_rng_state())
    assert head.save_support_action_checkpoint(resumed,fresh_optimizer,steps=steps,action_steps=action_steps) == checkpoint
    batch,_=span._encoded_sources([SOURCE])
    equal_outputs(model(*batch),resumed(*batch))
    assert head.train_support_action_step(model,optimizer,mixed()) == head.train_support_action_step(resumed,fresh_optimizer,mixed())
    assert head.save_support_action_checkpoint(model,optimizer,steps=3,action_steps=2) == head.save_support_action_checkpoint(resumed,fresh_optimizer,steps=3,action_steps=2)


@pytest.mark.parametrize("kind", ["linear", "mlp"])
def test_padding_invariance_and_fixed_class_after_training(parent_bytes, kind):
    model=model_from(parent_bytes,kind);head.train_support_action_step(model,head.make_support_action_optimizer(model),mixed())
    (values,mask),_=span._encoded_sources([SOURCE]);padded=torch.zeros(1,values.shape[1]+2,values.shape[2]+3,dtype=torch.long)
    padded[:,:values.shape[1],:values.shape[2]]=values;pmask=torch.zeros(1,mask.shape[1]+2,dtype=torch.bool);pmask[:,:mask.shape[1]]=mask
    a,b=model(values,mask),model(padded,pmask)
    for key in ("support","modality","presence"):assert torch.allclose(a[key],b[key],atol=1e-7,rtol=0),key
    for key in ("start","end"):
        for facet in span.FACETS:
            assert torch.allclose(a[key][facet],b[key][facet][:,:mask.shape[1]],atol=1e-7,rtol=0)
            assert bool((b[key][facet][:,mask.shape[1]:] == -10000.).all())


def test_explicit_action_targets_only_and_parser_guards(parent_bytes,monkeypatch):
    with pytest.raises(ValueError):head.SupportActionExample(SOURCE,True)
    with pytest.raises(ValueError):head.SupportActionExample(SOURCE,False,[11,15])
    with pytest.raises(ValueError):head.SupportActionExample(SOURCE,True,[12,15])
    with pytest.raises(ValueError):head.SupportActionExample(SOURCE,True,[11,True])
    with pytest.raises(TypeError):head.SupportActionExample(SOURCE,True,[11,15],modality="O")
    model=model_from(parent_bytes)
    monkeypatch.setattr(span,"_labels",lambda *_:pytest.fail("old structural TRAIN targets accessed"))
    monkeypatch.setattr(span.proposal,"propose_scope_from_spans",lambda *_args,**_kwargs:pytest.fail("TRAIN used parser/proposal"))
    head.train_support_action_step(model,head.make_support_action_optimizer(model),mixed())
    monkeypatch.setattr(head,"_action_labels",lambda *_:pytest.fail("action targets reached inference"))
    result=head.predict_support_action(model,SOURCE,"rule",expected_source_sha256=digest(SOURCE))
    assert result["status"]=="abstained" and result["modality_logits"] is not None
    assert not result["target_access"]


def test_ordered_donor_features_can_distinguish_same_byte_anagrams(parent_bytes):
    model=model_from(parent_bytes)
    sources=["cedar must move", "cedar muts move"]
    batch,_=span._encoded_sources(sources)
    with torch.no_grad():
        _,encoded,pooled=trigger._donor_tensor_path(model._parent.donor,*batch)
    assert sorted("must".encode())==sorted("muts".encode())
    assert not torch.equal(encoded[0,1],encoded[1,1])
    assert not torch.equal(pooled[0],pooled[1])


def test_support_only_sparse_Adam_restores_without_fabricating_action_state(parent_bytes):
    model=model_from(parent_bytes,"mlp");optimizer=head.make_support_action_optimizer(model)
    head.train_support_action_step(model,optimizer,[head.SupportActionExample("map and ink",False)])
    checkpoint=head.save_support_action_checkpoint(model,optimizer,steps=1,action_steps=0)
    resumed,new_optimizer,steps,action_steps=head.restore_support_action_checkpoint(checkpoint)
    assert (steps,action_steps)==(1,0)
    assert set(new_optimizer.state)==set(resumed.heads["support"].parameters())
    assert head.train_support_action_step(model,optimizer,mixed())==head.train_support_action_step(resumed,new_optimizer,mixed())
    assert head.save_support_action_checkpoint(model,optimizer,steps=2,action_steps=1)==head.save_support_action_checkpoint(resumed,new_optimizer,steps=2,action_steps=1)


def test_wrong_source_digest_and_missing_caller_precede_model(parent_bytes):
    model=model_from(parent_bytes);model.forward=lambda *_:pytest.fail("model invoked before external-source check")
    with pytest.raises(ValueError,match="source digest mismatch"):
        head.predict_support_action(model,SOURCE,"rule",expected_source_sha256="0"*64)
    result=head.predict_support_action(model,SOURCE,None,expected_source_sha256=digest(SOURCE))
    assert not result["model_executed"] and result["blockers"]==["explicit_caller_condition_attachment_required"]


def source_output():
    return {"support":torch.tensor([8.]),"modality":torch.tensor([[.1,.2,.3]]),"presence":torch.tensor([[[1.,0.],[1.,0.]]]),
        **{key:{facet:torch.tensor([[5. if i==position else -5. for i in range(3)]])
            for facet,position in {"modality":1,"actor":0,"action":2,"object":0,"condition":0}.items()} for key in ("start","end")}}


def test_prediction_keeps_owner_and_nullable_caller_zero_authority(parent_bytes):
    model=model_from(parent_bytes);model.forward=lambda *_:source_output();source="cedar must move"
    result=head.predict_support_action(model,source,"statement",expected_source_sha256=digest(source))
    assert result["status"]=="predicted" and result["prediction"]["condition_attachment"] is None
    assert result["prediction"]["spans"]["condition"] is None and result["formal_output"] is None
    assert not any(result["masks"].values()) and result["modality_logits"]==source_output()["modality"][0].tolist()


@pytest.mark.parametrize("fault",["reversed","shape","nonfinite","coverage"])
def test_invalid_predictions_block_without_repair_and_restore_mode(parent_bytes,fault):
    model=model_from(parent_bytes);output=source_output()
    if fault=="reversed":output["end"]["action"]=torch.tensor([[5.,-5.,-5.]])
    elif fault=="shape":output["support"]=torch.zeros(1,2)
    elif fault=="nonfinite":output["support"][0]=float("nan")
    if fault=="coverage":
        def invalid(*_):raise trigger._InvalidTriggerFeature("positive finite coverage required")
        model.forward=invalid
    else:model.forward=lambda *_:output
    source="cedar must move";result=head.predict_support_action(model,source,"rule",expected_source_sha256=digest(source))
    assert result["status"]=="blocked" and result["prediction"] is None
    assert model.training and not model._parent.training
    if fault=="reversed":assert result["modality_logits"] is not None


@pytest.mark.parametrize("fault",["extra","seal","parent_sha","parent_bytes","head_shape","support_step","action_step","missing_state","variance","steps_bool","action_exceeds_support","recipe"])
def test_checkpoint_rejects_tampering_and_per_head_progress(parent_bytes,fault):
    model=model_from(parent_bytes);optimizer=head.make_support_action_optimizer(model)
    head.train_support_action_step(model,optimizer,mixed())
    head.train_support_action_step(model,optimizer,[head.SupportActionExample("ink and map",False)])
    cp=head.save_support_action_checkpoint(model,optimizer,steps=2,action_steps=1)
    if fault=="extra":cp["extra"]=None
    elif fault=="seal":cp["checkpoint_sha256"]="0"*64
    elif fault=="parent_sha":cp["parent"]["sha256"]="0"*64
    elif fault=="parent_bytes":cp["parent"]["bytes"]+=1
    elif fault=="head_shape":cp["head_state"]["support.weight"]["shape"][1]+=1
    elif fault=="support_step":cp["optimizer"]["state"]["0"]["step"]["values"][0]=1.
    elif fault=="action_step":cp["optimizer"]["state"]["2"]["step"]["values"][0]=2.
    elif fault=="missing_state":del cp["optimizer"]["state"]["2"]
    elif fault=="variance":cp["optimizer"]["state"]["0"]["exp_avg_sq"]["values"][0]=-1.
    elif fault=="steps_bool":cp["steps"]=True
    elif fault=="action_exceeds_support":cp["action_steps"]=3
    else:cp["profile"]["class_parameters_updated"]=True
    if fault!="seal":reseal(cp)
    with pytest.raises(ValueError):head.restore_support_action_checkpoint(cp)


@pytest.mark.parametrize("fault",["weight","gradflag","mode","rawprovenance"])
def test_parent_snapshot_rejects_changes(parent_bytes,fault):
    model=model_from(parent_bytes)
    if fault=="weight":
        with torch.no_grad():model._parent.adapter[2].bias.add_(1.)
    elif fault=="gradflag":next(model._parent.adapter.parameters()).requires_grad_(True)
    elif fault=="mode":model._parent.adapter.train()
    else:model._parent_json_utf8+=" "
    with pytest.raises(ValueError):model(*span._encoded_sources([SOURCE])[0])


def test_wrong_parent_digest_typed_owner_and_source_bounds(parent_bytes):
    with pytest.raises(ValueError,match="digest mismatch"):
        head.FrozenSupportAction(parent_bytes,expected_parent_sha256="0"*64)
    model=model_from(parent_bytes)
    parsed=model.parent_checkpoint;parsed["steps"]=99
    assert model.parent_checkpoint["steps"]==1
    with pytest.raises(ValueError,match="typed trigger"):
        trigger.predict_trigger_readout(model,SOURCE,"rule",expected_source_sha256=digest(SOURCE))
    (values,mask),_=span._encoded_sources([SOURCE])
    with pytest.raises(ValueError,match="CPU typed"):model(values.float(),mask)
    values[0,0,0]=257
    with pytest.raises(ValueError,match="alphabet"):model(values,mask)
    with pytest.raises(ValueError):head.SupportActionExample("x"*65,False)
