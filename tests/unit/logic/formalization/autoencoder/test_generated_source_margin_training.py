"""Source-only generated margins, strict replay and detached training targets."""
from copy import deepcopy
import json
import math
import random
import time

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import generated_source_margin_training as subject
from ipfs_datasets_py.logic.formalization.autoencoder import generated_field_training as fields
from ipfs_datasets_py.logic.formalization.autoencoder import clause_source_context as contexts_owner
from .test_contextual_generated_boundary_training import scripted
from .test_generated_field_training import labelled
from .test_clause_source_context import transform
from .test_projected_source_decoder_experiment import encode, rule
from .test_long_span_cardinality_training import validate_rule
from .test_ordered_clause_recurrent_decoder_experiment import fixture as real_fixture


@pytest.fixture(autouse=True)
def one_cpu():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def prepared(dimension=8, count=2, eroded=True, invalid=False):
    model, codec, rows, contexts = scripted("recurrent", count=count, dimension=dimension, invalid=invalid)
    vocabulary = codec["target_vocabulary"]
    size = len(vocabulary)
    source_targets = {field: vocabulary.index(json.dumps(rule()[field])) for field in subject.FIELDS}
    with torch.no_grad():
        model.non_action_head.field_readout.weight.zero_()
        model.non_action_head.field_readout.bias.zero_()
        for index, field in enumerate(("actor", "modality", "object")):
            model.non_action_head.field_readout.bias[index*size+source_targets[field]] = 8.
        model.action_head.field_readout.weight.zero_()
        model.action_head.field_readout.bias.zero_()
        model.action_head.field_readout.bias[source_targets["action"]] = 8.
        if eroded and not invalid:
            sequence = encode(codec, {"rules": [rule()]*count})[1:]
            competitor = vocabulary.index('"a"')
            for position, token in enumerate(sequence):
                if position >= 2 and vocabulary[sequence[position-2]] in [json.dumps(f) for f in subject.FIELDS]:
                    model.body.body.body.output.weight[:, position].zero_()
                    model.body.body.body.output.weight[competitor, position] = 3.
    train, references = labelled(rows, contexts, codec, wrong=False)
    inventory = subject.prepare_training_inventory(train, references, contexts=contexts, codec=codec, validate_rule=validate_rule)
    return model, codec, rows, contexts, inventory


def collect(model, codec, rows, contexts, **options):
    return subject.collect_source_margin_sites(model, rows, codec=codec, input_transform=transform(model.dimension),
        source_contexts=contexts, max_target_tokens=options.pop("max_target_tokens", 512),
        batch_size=options.pop("batch_size", 8), deadline=options.pop("deadline", time.monotonic()+30), **options)


def losses(model, codec, collection, inventory, contexts, **options):
    return subject.generated_margin_losses(torch, model, collection, inventory, codec=codec,
        input_transform=transform(model.dimension), source_contexts=contexts,
        deadline=options.pop("deadline", time.monotonic()+30), **options)


def resign(value, key="collection_sha256"):
    value[key] = subject.core.digest({k: v for k, v in value.items() if k != key})
    return value


@pytest.mark.parametrize("dimension", [8,384,768])
def test_positive_margin_collection_and_shared_loss_at_all_native_widths(dimension):
    model, codec, rows, contexts, inventory = prepared(dimension)
    old = fields.collect_source_generated_sites(model, rows, codec=codec, input_transform=transform(dimension),
        source_contexts=contexts, deadline=time.monotonic()+30)
    col = collect(model, codec, rows, contexts)
    assert col["predictions"] == old["predictions"]
    assert col["rows"][0]["available_sites"] == old["rows"][0]["available_sites"]
    assert col["source_head_extra_evaluations"] == col["extra_model_passes"] == 0
    assert col["reference_count_access"] is col["reference_prefix_access"] is col["inventory_access"] is False
    assert col["available_field_sites"] == 8
    result = losses(model, codec, col, inventory, contexts)
    receipt = result["receipt"]
    assert receipt["margin"]["selected_sites"] == 4
    assert receipt["margin"]["eligible_sites"] == receipt["margin"]["eroded_sites"] == 8
    assert receipt["margin"]["unvisited_reference_sites"]==0
    assert all(c==dict(scored=2,eligible=2,eroded=2,source_wrong_combined_correct=0)
        for c in receipt["margin"]["eligibility_by_field"].values())
    assert receipt["boundary"]["selected_sites"] == 2
    assert float(result["margin_loss"].detach()) == 3.
    assert receipt["maximum_replay_logit_absolute_difference"] == receipt["maximum_source_replay_logit_absolute_difference"] == 0.
    assert receipt["generation"]["rollout_count"] == receipt["replay_batch_count"] == 1
    assert all(e["slot"] == 0 and e["source_margin"] == 8. and e["replayed_combined_margin"] == 5.
        for e in receipt["margin"]["events"])
    assert result["margin_loss"].requires_grad
    assert all(p.grad is None for p in model.parameters())


def test_collection_caches_without_an_extra_head_call_or_greedy_pass(monkeypatch):
    model, codec, rows, contexts, inventory = prepared()
    calls = {"greedy": 0, "action": 0, "non_action": 0, "bulk": 0}
    original = subject.core._greedy
    def greedy(*a, **kw):
        calls["greedy"] += 1
        return original(*a, **kw)
    monkeypatch.setattr(subject.core, "_greedy", greedy)
    handles=[]
    for name in ("action", "non_action"):
        handles.append(getattr(model,name+"_head").field_readout.register_forward_hook(
            lambda _m,_i,_o,n=name:calls.__setitem__(n,calls[n]+1)))
    bulk=fields._bulk_replay
    def replay(*a,**kw):
        calls["bulk"]+=1
        return bulk(*a,**kw)
    monkeypatch.setattr(fields,"_bulk_replay",replay)
    try:
        col=collect(model,codec,rows,contexts)
        assert calls == dict(greedy=1,action=1,non_action=1,bulk=0)
        losses(model,codec,col,inventory,contexts)
        assert calls == dict(greedy=1,action=2,non_action=2,bulk=1)
    finally:
        for handle in handles:handle.remove()


@pytest.mark.parametrize("key", ["target_ids","target","reference_count","prefix"])
def test_reference_fields_are_refused_before_collection(key):
    model,codec,rows,contexts,_=prepared()
    rows[0][key]=[]
    with pytest.raises(ValueError,match="closed source-only"):
        collect(model,codec,rows,contexts)


def test_training_inventory_requires_unambiguous_literal_alignment():
    model,codec,rows,contexts,_=prepared()
    segment=contexts["train"]["segments"][0]
    rows[0]["source_text"]=segment["source_text"]+"\n\n"+segment["source_text"]
    contexts["train"]=contexts_owner._descriptor(rows[0]["source_text"],[segment["vector"],segment["vector"]])
    train,refs=labelled(rows,contexts,codec,targets={"train":[rule(),dict(rule(),action="a")]})
    with pytest.raises(ValueError,match="ambiguous.*conflicting"):
        subject.prepare_training_inventory(train,refs,contexts=contexts,codec=codec,validate_rule=validate_rule)


def test_zero_signal_preserves_legacy_boundary_loss_and_gradients():
    model,codec,rows,contexts,inventory=prepared(eroded=False)
    col=collect(model,codec,rows,contexts)
    actual=losses(model,codec,col,inventory,contexts)
    oldcol=fields.collect_source_generated_sites(model,rows,codec=codec,input_transform=transform(8),
        source_contexts=contexts,deadline=time.monotonic()+30)
    old=fields.generated_site_losses(torch,model,oldcol,inventory,codec=codec,input_transform=transform(8),
        source_contexts=contexts,deadline=time.monotonic()+30)
    assert actual["margin_loss"] is None and old["field_loss"] is None
    assert torch.equal(actual["boundary_loss"],old["boundary_loss"])
    parameters=[p for p in model.parameters() if p.requires_grad]
    a=torch.autograd.grad(actual["boundary_loss"],parameters,allow_unused=True)
    b=torch.autograd.grad(old["boundary_loss"],parameters,allow_unused=True)
    assert all(x is None and y is None or x is not None and y is not None and torch.equal(x,y) for x,y in zip(a,b))


@pytest.mark.parametrize("invalid",[False,True])
def test_no_selected_margin_or_boundary_returns_no_graph(invalid,monkeypatch):
    model,codec,rows,contexts,inventory=prepared(eroded=False,invalid=invalid)
    col=collect(model,codec,rows,contexts)
    monkeypatch.setattr(fields,"_bulk_replay",lambda *a,**kw:pytest.fail("unselected sites must not replay"))
    result=losses(model,codec,col,inventory,contexts,boundary_site_policy="first_wrong")
    assert result["margin_loss"] is result["boundary_loss"] is None
    assert result["receipt"]["union_active_rows"]==0
    if invalid:assert result["receipt"]["margin"]["unvisited_reference_sites"]==8


def artificial_site(field="action",slot=0,source=None,combined=None,position=1):
    source=source or [8.,0.,-1.,-2.]
    combined=combined or [5.,0.,-1.,-2.]
    return dict(field=field,slot=slot,position=position,source_slot_available=True,
        source_logits=source,collection_logits=combined,
        actual_next_token_id=max(range(len(combined)),key=combined.__getitem__))


def clauses(count=2):
    return [dict(target_token_ids={f:0 for f in subject.FIELDS},source_sha256="a"*64,reference_rule_index=i) for i in range(count)]


@pytest.mark.parametrize("field",subject.FIELDS)
def test_first_eroded_per_field_and_positive_source_correct_eligibility(field):
    sites=[artificial_site(field,0,combined=[9.,0.,-1.,-2.],position=1),
           artificial_site(field,1,position=8),artificial_site(field,1,position=20)]
    selected,scored,unscored=subject._select_margin_sites(sites,clauses())
    assert len(selected)==1 and selected[0]["position"]==8
    assert len(scored)==3 and unscored==[]


@pytest.mark.parametrize("source,combined,eligible,selected",[
    ([8.,0.,-1.,-2.],[5.,0.,-1.,-2.],True,True),
    ([8.,0.,-1.,-2.],[8.,0.,-1.,-2.],True,False),
    ([8.,0.,-1.,-2.],[9.,0.,-1.,-2.],True,False),
    ([1.,2.,-1.,-2.],[5.,0.,-1.,-2.],False,False),
    ([1.,1.,-1.,-2.],[.5,1.,-1.,-2.],False,False),
])
def test_selective_loss_excludes_wrong_source_and_zero_margin_ties(source,combined,eligible,selected):
    result,scored,_=subject._select_margin_sites([artificial_site(source=source,combined=combined)],clauses())
    assert scored[0]["source_positive_margin_eligible"] is eligible
    assert bool(result) is selected


def test_full_vocabulary_punctuation_competitor_and_first_tie_gradient():
    logits=torch.tensor([5.,1.,3.,3.],requires_grad=True)
    loss,margin,competitor=subject._margin_tensor(torch,logits,0,4.)
    assert competitor==2 and float(margin)==2. and float(loss)==2.
    loss.backward()
    assert logits.grad.tolist()==[-1.,0.,1.,0.]


@pytest.mark.parametrize("margin",[4.,5.])
def test_relu_has_no_gradient_at_equal_or_better_margin(margin):
    logits=torch.tensor([margin,0.,-1.,-2.],requires_grad=True)
    loss,_,_=subject._margin_tensor(torch,logits,0,4.)
    loss.backward()
    assert float(loss)==0. and torch.count_nonzero(logits.grad)==0


def test_margin_target_is_detached_even_if_caller_supplies_tensor():
    logits=torch.tensor([3.,0.,-1.,-2.],requires_grad=True)
    teacher=torch.tensor(4.,requires_grad=True)
    with pytest.warns(UserWarning):
        loss,_,_=subject._margin_tensor(torch,logits,0,teacher)
    loss.backward()
    assert teacher.grad is None and logits.grad.tolist()==[-1.,1.,0.,0.]


def test_extra_source_slots_are_unscored_and_never_clamped():
    model,codec,rows,contexts,inventory=prepared(count=9)
    col=collect(model,codec,rows,contexts)
    # Greedy follows supplied source only where available. Do not invent later
    # reference labels if it stops or loses grammar at an unavailable slot.
    for site in col["rows"][0]["available_field_sites"]:
        if site["slot"]>=2:
            assert site["source_slot_available"] is False
            assert site["source_clause_sha256"] is None
            assert all(value==0. for value in site["source_logits"])
    result=losses(model,codec,col,inventory,contexts)
    assert all(e["slot"]<2 for e in result["receipt"]["margin"]["events"])


@pytest.mark.parametrize("key,value",[("source_slot_available",False),("source_guidance_active",False),
    ("source_clause_sha256","b"*64),("source_logits",[0.])])
def test_resigned_source_provenance_tampering_is_rejected(key,value):
    model,codec,rows,contexts,inventory=prepared()
    col=collect(model,codec,rows,contexts)
    col["rows"][0]["available_field_sites"][0][key]=value
    resign(col)
    with pytest.raises(ValueError):losses(model,codec,col,inventory,contexts)


def test_resigned_source_logits_cannot_pass_strict_replay():
    model,codec,rows,contexts,inventory=prepared()
    col=collect(model,codec,rows,contexts)
    col["rows"][0]["available_field_sites"][0]["source_logits"][0]+=.125
    resign(col)
    with pytest.raises(ValueError,match="replayed source-margin logits"):
        losses(model,codec,col,inventory,contexts)
    assert all(p.grad is None for p in model.parameters())


def test_bulk_failure_retries_original_batch_before_any_loss(monkeypatch):
    model,codec,rows,contexts,inventory=prepared()
    col=collect(model,codec,rows,contexts)
    bulk=fields._bulk_replay
    def wrong(*a,**kw):return bulk(*a,**kw)+.01
    monkeypatch.setattr(fields,"_bulk_replay",wrong)
    result=losses(model,codec,col,inventory,contexts)
    receipt=result["receipt"]
    assert receipt["discarded_bulk_batch_count"]==receipt["incremental_retry_batch_count"]==1
    bad,good=receipt["replay_attempts"]
    assert not bad["parity_passed"] and not bad["used_for_loss"]
    assert good["parity_passed"] and good["source_parity_passed"] and good["used_for_loss"]
    assert good["original_batch_membership_preserved"]
    assert receipt["physical_replay_forward_calls"]==1+receipt["incremental_retry_forward_steps"]
    assert receipt["replay_logits_atol"]==receipt["replay_logits_rtol"]==2e-5
    assert float(result["margin_loss"].detach())==3.


def test_retry_mismatch_aborts_without_backward(monkeypatch):
    model,codec,rows,contexts,inventory=prepared()
    col=collect(model,codec,rows,contexts)
    bulk,retry=fields._bulk_replay,fields._incremental_replay
    monkeypatch.setattr(fields,"_bulk_replay",lambda *a,**kw:bulk(*a,**kw)+.01)
    def wrong(*a,**kw):
        result=retry(*a,**kw)
        return {rid:{pos:value+.01 for pos,value in values.items()} for rid,values in result.items()}
    monkeypatch.setattr(fields,"_incremental_replay",wrong)
    with pytest.raises(ValueError,match="replayed source-margin logits"):
        losses(model,codec,col,inventory,contexts)
    assert all(p.grad is None for p in model.parameters())


@pytest.mark.parametrize("phase",["collection","loss"])
def test_expired_deadline_preserves_model_and_gradients(phase):
    model,codec,rows,contexts,inventory=prepared()
    col=collect(model,codec,rows,contexts)
    before=subject.core.tensor_digest(model)
    with pytest.raises(TimeoutError):
        (collect(model,codec,rows,contexts,deadline=0.) if phase=="collection" else
         losses(model,codec,col,inventory,contexts,deadline=0.))
    assert subject.core.tensor_digest(model)==before
    assert all(p.grad is None for p in model.parameters())


def test_collection_and_replay_preserve_caller_modes_rng_and_weights():
    model,codec,rows,contexts,inventory=prepared()
    model.train();model.action_head.eval()
    modes={k:v.training for k,v in model.named_modules()}
    before=subject.core.tensor_digest(model);rng=torch.get_rng_state().clone();python_rng=random.getstate()
    losses(model,codec,collect(model,codec,rows,contexts),inventory,contexts)
    assert subject.core.tensor_digest(model)==before and modes=={k:v.training for k,v in model.named_modules()}
    assert torch.equal(rng,torch.get_rng_state()) and python_rng==random.getstate()


@pytest.mark.parametrize("dimension",[8,384,768])
def test_exact_recurrent_whitelist_on_real_geometry(monkeypatch,dimension):
    from . import test_ordered_clause_recurrent_decoder_experiment as fixture_owner
    original=fixture_owner.numerical._model
    def geometry(seed,codec,options):return original(seed,codec,dict(options,hidden_size=32))
    monkeypatch.setattr(fixture_owner.numerical,"_model",geometry)
    model,_,codec,_=real_fixture(dimension)
    pairs=subject.recurrent_auxiliary_parameters(model)
    assert tuple(name for name,_ in pairs)==subject.RECURRENT_PARAMETER_NAMES
    assert len(pairs)==11 and len({id(p) for _,p in pairs})==11
    assert all(not any(part in name for part in ('action_head','count_head','projection_')) for name,_ in pairs)
    size=len(codec["target_vocabulary"])
    expected=32*(dimension+1)+4800+size*33+size*16+16*dimension+2048
    assert sum(p.numel() for _,p in pairs)==expected
    first=pairs[0][1];first.requires_grad_(False)
    with pytest.raises(ValueError,match="auxiliary recurrent parameter"):
        subject.recurrent_auxiliary_parameters(model)


def test_whitelist_rejects_scripted_or_undeclared_recurrent_geometry():
    model,_,_,_,_=prepared()
    with pytest.raises(ValueError,match="recurrent geometry"):
        subject.recurrent_auxiliary_parameters(model)


def test_row_balanced_reduction_does_not_weight_rows_by_number_of_fields():
    model,codec,rows,contexts,_=prepared()
    other=dict(id="other",source_text="Another agency clause.\n\nAnother officer clause.",input=list(rows[0]["input"]))
    rows.append(other)
    contexts["other"]=contexts_owner._descriptor(other["source_text"],
        [segment["vector"] for segment in contexts["train"]["segments"]])
    targets={"train":[rule(),rule()],"other":[dict(rule(),actor="a",modality="F",object="a")]*2}
    train,refs=labelled(rows,contexts,codec,targets=targets)
    inventory=subject.prepare_training_inventory(train,refs,contexts=contexts,codec=codec,validate_rule=validate_rule)
    result=losses(model,codec,collect(model,codec,rows,contexts),inventory,contexts)
    component=result["receipt"]["margin"]
    assert component["active_rows"]==2 and component["selected_sites"]==5
    assert all(e["mean_loss_coefficient"]==(.125 if e["id"]=="train" else .5) for e in component["events"])
    assert float(result["margin_loss"].detach())==3.
    assert sum(e["mean_loss_coefficient"] for e in component["events"])==1.


def test_only_margin_graph_when_all_boundaries_correct_and_first_wrong_policy():
    model,codec,rows,contexts,inventory=prepared()
    result=losses(model,codec,collect(model,codec,rows,contexts),inventory,contexts,boundary_site_policy="first_wrong")
    assert result["boundary_loss"] is None
    assert result["margin_loss"].requires_grad
    assert result["receipt"]["boundary"]["active_rows"]==0


def test_selected_source_cache_mismatch_alone_triggers_retry(monkeypatch):
    model,codec,rows,contexts,inventory=prepared()
    col=collect(model,codec,rows,contexts)
    original=fields._bulk_replay
    def wrong_cache(torch_,proxy,*a,**kw):
        logits=original(torch_,proxy,*a,**kw)
        proxy.source=proxy.source+.01
        return logits
    monkeypatch.setattr(fields,"_bulk_replay",wrong_cache)
    receipt=losses(model,codec,col,inventory,contexts)["receipt"]
    bad,good=receipt["replay_attempts"]
    assert bad["combined_parity_passed"] and not bad["source_parity_passed"] and not bad["used_for_loss"]
    assert bad["source_mismatches"] and not bad["mismatches"]
    assert good["source_parity_passed"] and good["used_for_loss"]


@pytest.mark.parametrize("phase",["bulk","retry"])
def test_deadline_during_replay_leaves_no_grads_and_restores_modes(monkeypatch,phase):
    model,codec,rows,contexts,inventory=prepared()
    col=collect(model,codec,rows,contexts)
    model.train();model.non_action_head.eval()
    modes={name:module.training for name,module in model.named_modules()}
    before=subject.core.tensor_digest(model)
    def expired(*a,**kw):raise TimeoutError("test replay deadline")
    if phase=="bulk":monkeypatch.setattr(fields,"_bulk_replay",expired)
    else:
        original=fields._bulk_replay
        monkeypatch.setattr(fields,"_bulk_replay",lambda *a,**kw:original(*a,**kw)+.01)
        monkeypatch.setattr(fields,"_incremental_replay",expired)
    with pytest.raises(TimeoutError,match="test replay deadline"):
        losses(model,codec,col,inventory,contexts)
    assert subject.core.tensor_digest(model)==before
    assert all(p.grad is None for p in model.parameters())
    assert modes=={name:module.training for name,module in model.named_modules()}


@pytest.mark.parametrize("change",["weights","source_input","context","inventory","codec"])
def test_stale_producer_and_reference_bindings_fail_closed(change):
    model,codec,rows,contexts,inventory=prepared()
    col=collect(model,codec,rows,contexts)
    if change=="weights":
        with torch.no_grad():model.action_head.field_readout.bias[0]+=.1
    elif change=="source_input":col["source_rows"][0]["input"][0]+=.1;resign(col)
    elif change=="context":contexts["train"]["segments"][0]["source_sha256"]="a"*64
    elif change=="inventory":inventory["rows"]["train"]["clauses"][0]["source_sha256"]="a"*64;resign(inventory,"inventory_sha256")
    else:codec["target_vocabulary"][-1]='"new"'
    with pytest.raises(ValueError):losses(model,codec,col,inventory,contexts)


def test_near_output_limit_receipt_and_collection_retention_is_bounded(monkeypatch):
    model,codec,rows,contexts,inventory=prepared(count=16,eroded=False)
    vocabulary=codec["target_vocabulary"]
    sequence=encode(codec,{"rules":[rule()]*16})[1:]
    with torch.no_grad():
        for position in range(min(66,len(sequence))):
            if position>=2 and vocabulary[sequence[position-2]] in [json.dumps(f) for f in subject.FIELDS]:
                model.body.body.body.output.weight[:,position].zero_()
                model.body.body.body.output.weight[vocabulary.index('"a"'),position]=3.
    col=collect(model,codec,rows,contexts)
    assert col["predictions"][0]["generation_status"]=="output_limit"
    assert len(col["rows"][0]["consumed_prefix"])==511
    original=fields._bulk_replay
    monkeypatch.setattr(fields,"_bulk_replay",lambda *a,**kw:original(*a,**kw)+.01)
    receipt=losses(model,codec,col,inventory,contexts)["receipt"]
    assert receipt["margin"]["selected_sites"]==4
    assert receipt["incremental_retry_batch_count"]==1
    size=len(vocabulary)
    def count_vectors(value):
        if isinstance(value,list):
            if len(value)==size and all(type(v) is float for v in value):return 1
            return sum(count_vectors(v) for v in value)
        if isinstance(value,dict):return sum(count_vectors(v) for v in value.values())
        return 0
    assert count_vectors(col)<=144
    assert count_vectors(receipt)<=188
    assert count_vectors(col)+count_vectors(receipt)<=332
    assert "selected_field_sites" not in receipt["generation"]["rows"][0]
    assert all("source_logits" not in s and "collection_logits" not in s
        for s in receipt["generation"]["rows"][0]["scored_margin_sites"])


def test_existing_gradients_are_not_changed_by_collection_or_loss():
    model,codec,rows,contexts,inventory=prepared()
    for p in model.parameters():
        if p.requires_grad:p.grad=torch.full_like(p,.125)
    before={name:None if p.grad is None else p.grad.clone() for name,p in model.named_parameters()}
    losses(model,codec,collect(model,codec,rows,contexts),inventory,contexts)
    assert all(before[name] is None and p.grad is None or before[name] is not None
        and torch.equal(before[name],p.grad) for name,p in model.named_parameters())
