"""CPU fixtures for matched support pooling, frozen actions and exact Adam resume."""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json

import pytest
import torch

from ipfs_datasets_py.logic.formalization.autoencoder import legal_scope_span_decoder as span
from ipfs_datasets_py.logic.formalization.autoencoder import legal_scope_trigger_readout as trigger
from ipfs_datasets_py.logic.formalization.autoencoder import legal_scope_support_action as action
from ipfs_datasets_py.logic.formalization.autoencoder import legal_scope_support_gate as gate

SOURCE = "cedar must move brick when chalk fades."


def digest(source): return sha256(source.encode()).hexdigest()


@pytest.fixture(scope="module")
def parent_bytes():
    donor = span.ScopeSpanDecoder(span.ScopeSpanDecoderConfig(seed=11, byte_dim=4, byte_hidden=16,
        token_dim=8, token_hidden=32, head_hidden=8))
    with torch.no_grad(): donor.support_head.bias.fill_(-5.)
    optimizer = span.make_scope_span_optimizer(donor)
    span.train_scope_span_step(donor, optimizer, [span.ScopeSpanExample(SOURCE, False)])
    donor.eval()
    raw = json.dumps(span.save_scope_span_checkpoint(donor, optimizer, steps=1), sort_keys=True).encode()
    middle = trigger.FrozenTriggerReadout(raw, expected_donor_sha256=sha256(raw).hexdigest(),
        config=trigger.TriggerReadoutConfig(seed=21, mode="predicted_trigger", hidden=64))
    optimizer = trigger.make_trigger_readout_optimizer(middle)
    trigger.train_trigger_readout_step(middle, optimizer, [trigger.TriggerReadoutExample(SOURCE, True, "O")])
    middle.eval()
    raw = json.dumps(trigger.save_trigger_readout_checkpoint(middle, optimizer, steps=1),
                     ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    parent = action.FrozenSupportAction(raw, expected_parent_sha256=sha256(raw).hexdigest(),
        config=action.SupportActionConfig(seed=22, head_kind="mlp", hidden=32))
    optimizer = action.make_support_action_optimizer(parent)
    action.train_support_action_step(parent, optimizer,
        [action.SupportActionExample(SOURCE, True, [11,15]), action.SupportActionExample("map and ink", False)])
    action.train_support_action_step(parent, optimizer, [action.SupportActionExample("ink and map", False)])
    parent.eval()
    return json.dumps(action.save_support_action_checkpoint(parent, optimizer, steps=2, action_steps=1),
                      ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def model_from(raw, mode="global"):
    return gate.FrozenSupportGate(raw, expected_parent_sha256=sha256(raw).hexdigest(),
                                 config=gate.SupportGateConfig(seed=31, mode=mode))


def mixed():
    return [gate.SupportGateExample(SOURCE, True), gate.SupportGateExample("oak may cross gate.", True),
            gate.SupportGateExample("cedar muts move brick.", False)]


def equal_outputs(left, right, support=True):
    for key in ("support", "modality", "presence"):
        if support or key != "support": assert torch.equal(left[key], right[key]), key
    for key in ("start", "end"):
        for facet in span.FACETS: assert torch.equal(left[key][facet], right[key][facet]), (key, facet)


def reseal(checkpoint):
    checkpoint["checkpoint_sha256"] = sha256(span._canonical({k:v for k,v in checkpoint.items()
                                                            if k != "checkpoint_sha256"})).hexdigest()
    return checkpoint


@pytest.mark.parametrize("mode", ["global", "predicted_trigger"])
def test_zero_gate_matches_whole_parent_function_and_full_output_custody(parent_bytes, mode):
    rng = torch.random.get_rng_state().clone()
    parent, old_optimizer, steps, action_steps = action.restore_support_action_checkpoint(json.loads(parent_bytes))
    model = model_from(parent_bytes, mode)
    assert (steps, action_steps) == (model.parent_steps, model.parent_action_steps) == (2,1)
    assert torch.equal(rng, torch.random.get_rng_state()) and model.feature_width == 97
    assert sum(p.numel() for p in model.gate.parameters()) == 3169
    assert sum(p.numel() for p in model.parameters() if p.requires_grad) == 3169
    assert all(not p.requires_grad and p.grad is None for p in model._parent.parameters())
    optimizer = gate.make_support_gate_optimizer(model)
    assert not optimizer.state and old_optimizer.state
    assert [id(p) for p in optimizer.param_groups[0]["params"]] == [id(p) for p in model.gate.parameters()]
    batch, _ = span._encoded_sources([SOURCE, "é may go.", "cedar muts move brick."])
    with torch.no_grad(): equal_outputs(parent(*batch), model(*batch))
    original = action.predict_support_action(parent, SOURCE, "rule", expected_source_sha256=digest(SOURCE))
    result = gate.predict_support_gate(model, SOURCE, "rule", expected_source_sha256=digest(SOURCE))
    for key in ("status","prediction","proposal","blockers","raw_prediction","modality_logits","support_probability","support_threshold"):
        assert result.get(key) == original.get(key), key
    assert torch.equal(rng, torch.random.get_rng_state())
    cp = gate.save_support_gate_checkpoint(model, optimizer, steps=0)
    assert cp["optimizer"]["state"] == {} and cp["parent"]["json_utf8"].encode() == parent_bytes


def test_matched_arm_initialization_and_only_pooling_differs(parent_bytes):
    global_model, local_model = model_from(parent_bytes), model_from(parent_bytes, "predicted_trigger")
    assert global_model.config.to_dict() | {"mode":"predicted_trigger"} == local_model.config.to_dict()
    assert all(torch.equal(v, local_model.gate.state_dict()[n]) for n,v in global_model.gate.state_dict().items())
    captured = {}
    def record(name):
        def hook(_module, args): captured[name] = args[0].detach().clone()
        return hook
    handles = [global_model.gate.register_forward_pre_hook(record("global")),
               local_model.gate.register_forward_pre_hook(record("local"))]
    batch,_=span._encoded_sources(["cedar must move brick when chalk fades.", "oak may go."])
    try:
        with torch.no_grad(): equal_outputs(global_model(*batch),local_model(*batch))
    finally:
        for handle in handles: handle.remove()
    assert captured["global"].shape == captured["local"].shape == (2,97)
    assert not torch.equal(captured["global"], captured["local"])
    with torch.no_grad():
        output,encoded,_=trigger._donor_tensor_path(local_model._parent._parent.donor,*batch)
        bundle=torch.cat((encoded,gate._ordered_byte_features(local_model._parent._parent.donor,*batch)),-1)
        expected=trigger._predicted_trigger_feature(bundle,batch[1],output["start"]["modality"],output["end"]["modality"])
    assert torch.equal(captured["local"],expected)


def test_orthography_features_match_original_projection_input_and_pad_to_finite_zero(parent_bytes):
    model=model_from(parent_bytes);donor=model._parent._parent.donor;captured=[]
    hook=donor.token_projection.register_forward_pre_hook(lambda _m,args:captured.append(args[0].detach().clone()))
    batch,_=span._encoded_sources([SOURCE,"é may go."])
    try:
        with torch.no_grad(): model(*batch);features=gate._ordered_byte_features(donor,*batch)
    finally: hook.remove()
    assert len(captured)==1 and torch.equal(features,captured[0])
    assert bool(torch.isfinite(features).all()) and bool((features[~batch[1]]==0).all())
    anagrams,_=span._encoded_sources(["cedar must move", "cedar muts move"])
    with torch.no_grad():orthography=gate._ordered_byte_features(donor,*anagrams)
    assert sorted("must".encode()) == sorted("muts".encode())
    assert not torch.equal(orthography[0,1],orthography[1,1])


@pytest.mark.parametrize("mode", ["global", "predicted_trigger"])
def test_does_not_invoke_old_parent_forward_assertion_or_saver(parent_bytes, mode, monkeypatch):
    model=model_from(parent_bytes,mode)
    def denied(*_args,**_kwargs):pytest.fail("old frozen parent typed contract invoked")
    monkeypatch.setattr(model._parent,"forward",denied);monkeypatch.setattr(model._parent,"_assert_parent",denied)
    monkeypatch.setattr(model._parent._parent,"forward",denied);monkeypatch.setattr(model._parent._parent,"_assert_frozen",denied)
    monkeypatch.setattr(action,"save_support_action_checkpoint",denied)
    optimizer=gate.make_support_gate_optimizer(model)
    gate.train_support_gate_step(model,optimizer,mixed())
    gate.save_support_gate_checkpoint(model,optimizer,steps=1)


@pytest.mark.parametrize("mode", ["global", "predicted_trigger"])
def test_support_updates_leave_action_class_all_spans_and_old_moments_frozen(parent_bytes, mode):
    model=model_from(parent_bytes,mode);optimizer=gate.make_support_gate_optimizer(model,weight_decay=.5)
    batch,_=span._encoded_sources([SOURCE,"oak may cross gate."])
    with torch.no_grad():before=model(*batch)
    state=deepcopy(model._parent.state_dict());artifact=model.parent_checkpoint;parent_modes=dict(model._parent_modes)
    result=gate.train_support_gate_step(model,optimizer,mixed())
    assert result["optimizer_step_executed"] and result["support_optimizer_step_executed"]
    assert (result["supported_examples"],result["unsupported_examples"],result["encoded_examples"]) == (2,1,3)
    with torch.no_grad():after=model(*batch)
    equal_outputs(before,after,support=False);assert not torch.equal(before["support"],after["support"])
    assert all(torch.equal(v,state[n]) for n,v in model._parent.state_dict().items())
    assert model.parent_checkpoint == artifact and model._parent_modes == parent_modes
    assert all(p.grad is None and not p.requires_grad for p in model._parent.parameters())
    assert set(optimizer.state)==set(model.gate.parameters()) and all(float(s["step"])==1 for s in optimizer.state.values())
    negative=[gate.SupportGateExample("cedar muts move brick.",False)]
    result=gate.train_support_gate_step(model,optimizer,negative)
    assert (result["supported_examples"],result["unsupported_examples"])==(0,1) and result["optimizer_step_executed"]
    assert model.parent_checkpoint==artifact and all(float(s["step"])==2 for s in optimizer.state.values())
    assert all(p.grad is None for p in model._parent.parameters())
    gate.save_support_gate_checkpoint(model,optimizer,steps=2)


@pytest.mark.parametrize("mode", ["global", "predicted_trigger"])
def test_exact_resume_next_update_full_Adam_parent_bytes_modes_and_rng(parent_bytes, mode):
    model=model_from(parent_bytes,mode);optimizer=gate.make_support_gate_optimizer(model)
    gate.train_support_gate_step(model,optimizer,mixed())
    gate.train_support_gate_step(model,optimizer,[gate.SupportGateExample("map and ink",False)])
    model.eval();rng=torch.random.get_rng_state().clone();cp=gate.save_support_gate_checkpoint(model,optimizer,steps=2)
    cp=json.loads(json.dumps(cp,allow_nan=False));resumed,new_optimizer,steps=gate.restore_support_gate_checkpoint(cp)
    assert steps==2 and not resumed.training and torch.equal(rng,torch.random.get_rng_state())
    assert cp["parent"]["json_utf8"].encode()==parent_bytes
    assert gate.save_support_gate_checkpoint(resumed,new_optimizer,steps=steps)==cp
    batch,_=span._encoded_sources([SOURCE]);equal_outputs(model(*batch),resumed(*batch))
    assert gate.train_support_gate_step(model,optimizer,mixed())==gate.train_support_gate_step(resumed,new_optimizer,mixed())
    assert gate.save_support_gate_checkpoint(model,optimizer,steps=3)==gate.save_support_gate_checkpoint(resumed,new_optimizer,steps=3)


@pytest.mark.parametrize("mode", ["global", "predicted_trigger"])
def test_padding_invariance_after_training(parent_bytes, mode):
    model=model_from(parent_bytes,mode);gate.train_support_gate_step(model,gate.make_support_gate_optimizer(model),mixed())
    (values,mask),_=span._encoded_sources([SOURCE]);padded=torch.zeros(1,values.shape[1]+2,values.shape[2]+3,dtype=torch.long)
    padded[:,:values.shape[1],:values.shape[2]]=values;pmask=torch.zeros(1,mask.shape[1]+2,dtype=torch.bool);pmask[:,:mask.shape[1]]=mask
    a,b=model(values,mask),model(padded,pmask)
    for key in ("support","modality","presence"):assert torch.allclose(a[key],b[key],atol=1e-7,rtol=0),key
    for key in ("start","end"):
        for facet in span.FACETS:
            assert torch.allclose(a[key][facet],b[key][facet][:,:mask.shape[1]],atol=1e-7,rtol=0)
            assert bool((b[key][facet][:,mask.shape[1]:]==-10000.).all())


def test_support_only_labels_no_parser_targets_at_fit_or_inference(parent_bytes,monkeypatch):
    with pytest.raises(ValueError):gate.SupportGateExample(SOURCE,1)
    with pytest.raises(TypeError):gate.SupportGateExample(SOURCE,True,action_span=[11,15])
    with pytest.raises(TypeError):gate.SupportGateExample(SOURCE,True,modality="O")
    model=model_from(parent_bytes)
    def denied(*_args,**_kwargs):pytest.fail("old labels, training constructors or parser invoked")
    monkeypatch.setattr(span,"_labels",denied);monkeypatch.setattr(action,"_action_labels",denied)
    monkeypatch.setattr(action,"SupportActionExample",denied);monkeypatch.setattr(trigger,"TriggerReadoutExample",denied)
    monkeypatch.setattr(span.proposal,"propose_scope_from_spans",denied)
    gate.train_support_gate_step(model,gate.make_support_gate_optimizer(model),mixed())
    monkeypatch.setattr(gate,"SupportGateExample",denied)
    result=gate.predict_support_gate(model,SOURCE,"rule",expected_source_sha256=digest(SOURCE))
    assert result["status"]=="abstained" and result["modality_logits"] is not None and not result["target_access"]


def test_wrong_source_digest_and_missing_caller_precede_model(parent_bytes):
    model=model_from(parent_bytes);model.forward=lambda *_:pytest.fail("model invoked before external source check")
    with pytest.raises(ValueError,match="source digest mismatch"):
        gate.predict_support_gate(model,SOURCE,"rule",expected_source_sha256="0"*64)
    result=gate.predict_support_gate(model,SOURCE,None,expected_source_sha256=digest(SOURCE))
    assert not result["model_executed"] and result["blockers"]==["explicit_caller_condition_attachment_required"]


def source_output():
    return {"support":torch.tensor([8.]),"modality":torch.tensor([[.1,.2,.3]]),"presence":torch.tensor([[[1.,0.],[1.,0.]]]),
        **{key:{facet:torch.tensor([[5. if i==position else -5. for i in range(3)]])
            for facet,position in {"modality":1,"actor":0,"action":2,"object":0,"condition":0}.items()} for key in ("start","end")}}


def test_prediction_transport_nullable_caller_and_zero_authority(parent_bytes):
    model=model_from(parent_bytes);model.forward=lambda *_:source_output();source="cedar must move"
    result=gate.predict_support_gate(model,source,"statement",expected_source_sha256=digest(source))
    assert result["status"]=="predicted" and result["prediction"]["condition_attachment"] is None
    assert result["prediction"]["spans"]["condition"] is None and result["formal_output"] is None
    assert not any(result["masks"].values()) and result["modality_logits"]==source_output()["modality"][0].tolist()
    assert not any(result[k] for k in ("accepted","qualified","proof_ready","formalized","source_semantics_verified"))


@pytest.mark.parametrize("fault", ["reversed","shape","nonfinite","coverage"])
def test_invalid_predictions_block_without_repair_and_restore_mode(parent_bytes,fault):
    model=model_from(parent_bytes);output=source_output()
    if fault=="reversed":output["end"]["action"]=torch.tensor([[5.,-5.,-5.]])
    elif fault=="shape":output["support"]=torch.zeros(1,2)
    elif fault=="nonfinite":output["support"][0]=float("nan")
    if fault=="coverage":
        def invalid(*_):raise trigger._InvalidTriggerFeature("positive finite coverage required")
        model.forward=invalid
    else:model.forward=lambda *_:output
    source="cedar must move";result=gate.predict_support_gate(model,source,"rule",expected_source_sha256=digest(source))
    assert result["status"]=="blocked" and result["prediction"] is None and model.training
    assert not model._parent.training
    if fault=="reversed":assert result["modality_logits"] is not None


@pytest.mark.parametrize("fault", ["extra","seal","parent_sha","parent_bytes","gate_shape","adam_step","missing_state","variance","steps_bool","recipe","nonfinite"])
def test_strict_checkpoint_rejects_tampering_full_Adam_and_progress(parent_bytes,fault):
    model=model_from(parent_bytes);optimizer=gate.make_support_gate_optimizer(model)
    gate.train_support_gate_step(model,optimizer,mixed());cp=gate.save_support_gate_checkpoint(model,optimizer,steps=1)
    if fault=="extra":cp["extra"]=None
    elif fault=="seal":cp["checkpoint_sha256"]="0"*64
    elif fault=="parent_sha":cp["parent"]["sha256"]="0"*64
    elif fault=="parent_bytes":cp["parent"]["bytes"]+=1
    elif fault=="gate_shape":cp["gate_state"]["0.weight"]["shape"][1]+=1
    elif fault=="adam_step":cp["optimizer"]["state"]["0"]["step"]["values"][0]=0.
    elif fault=="missing_state":del cp["optimizer"]["state"]["2"]
    elif fault=="variance":cp["optimizer"]["state"]["0"]["exp_avg_sq"]["values"][0]=-1.
    elif fault=="steps_bool":cp["steps"]=True
    elif fault=="recipe":cp["profile"]["structural_parameters_updated"]=True
    else:cp["gate_state"]["0.weight"]["values"][0]=float("nan")
    if fault=="nonfinite":
        with pytest.raises(ValueError):gate.restore_support_gate_checkpoint(cp)
        return
    if fault!="seal":reseal(cp)
    with pytest.raises(ValueError):gate.restore_support_gate_checkpoint(cp)


@pytest.mark.parametrize("fault", ["action_weight","class_weight","gradflag","mode","config","nestedartifact","rawprovenance"])
def test_whole_parent_snapshot_rejects_mutation(parent_bytes,fault):
    model=model_from(parent_bytes)
    if fault=="action_weight":
        with torch.no_grad():model._parent.heads["action_start"][2].bias.add_(1.)
    elif fault=="class_weight":
        with torch.no_grad():model._parent._parent.adapter[2].bias.add_(1.)
    elif fault=="gradflag":next(model._parent.heads["support"].parameters()).requires_grad_(True)
    elif fault=="mode":model._parent.heads.train()
    elif fault=="config":model._parent.config=replace(model._parent.config,seed=99)
    elif fault=="nestedartifact":model._parent._parent._donor_json_utf8+=" "
    else:model._parent_json_utf8+=" "
    with pytest.raises(ValueError):model(*span._encoded_sources([SOURCE])[0])


def test_wrong_parent_digest_typed_owner_and_source_bounds(parent_bytes):
    with pytest.raises(ValueError,match="digest mismatch"):
        gate.FrozenSupportGate(parent_bytes,expected_parent_sha256="0"*64)
    model=model_from(parent_bytes);parsed=model.parent_checkpoint;parsed["steps"]=99
    assert model.parent_checkpoint["steps"]==2
    with pytest.raises(ValueError,match="typed support/action"):
        action.predict_support_action(model,SOURCE,"rule",expected_source_sha256=digest(SOURCE))
    batch,_=span._encoded_sources([SOURCE]);values,mask=batch
    with pytest.raises(ValueError,match="CPU typed"):model(values.float(),mask)
    values[0,0,0]=257
    with pytest.raises(ValueError,match="alphabet"):model(values,mask)
    with pytest.raises(ValueError):gate.SupportGateExample("x"*65,False)
    with pytest.raises(ValueError):gate.SupportGateConfig(mode="oracle")
    with pytest.raises(ValueError):gate.SupportGateConfig(hidden=64)


def test_zero_progress_cannot_relabel_trained_or_tampered_gate_as_cold(parent_bytes):
    model=model_from(parent_bytes);optimizer=gate.make_support_gate_optimizer(model)
    cold=gate.save_support_gate_checkpoint(model,optimizer,steps=0)
    tampered=deepcopy(cold);tampered["gate_state"]["0.bias"]["values"][0]+=1.;reseal(tampered)
    with pytest.raises(ValueError,match="exact seeded cold gate"):
        gate.restore_support_gate_checkpoint(tampered)
    gate.train_support_gate_step(model,optimizer,mixed())
    with pytest.raises(ValueError,match="exact seeded cold gate"):
        gate.save_support_gate_checkpoint(model,gate.make_support_gate_optimizer(model),steps=0)
    with pytest.raises(ValueError,match="inventory"):
        gate.save_support_gate_checkpoint(model,optimizer,steps=0)
