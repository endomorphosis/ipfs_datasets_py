"""Opt-in strict causal retries; baseline math, vocabulary and guards stay fixed."""
from copy import deepcopy
import time
import weakref

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import contextual_generated_boundary_training as subject
from .test_contextual_generated_boundary_training import scripted, collect, loss, resign, transform, contexts_owner


@pytest.fixture(autouse=True)
def one_cpu():
    previous = torch.get_num_threads(); torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def stripped(value):
    if isinstance(value, dict):
        return {k:stripped(v) for k,v in value.items() if k != "elapsed_seconds"}
    if isinstance(value, list):
        return [stripped(v) for v in value]
    return value


def force_bulk_mismatch(monkeypatch):
    original = subject._retry_bulk_replay
    monkeypatch.setattr(subject, "_retry_bulk_replay", lambda *a, **k: original(*a, **k)+.1)


@pytest.mark.parametrize("policy", ["first_last", "first_wrong"])
def test_default_and_explicit_false_preserve_report_loss_and_gradients(policy, monkeypatch):
    model, codec, rows, contexts = scripted()
    collection = collect(model, codec, rows, contexts)
    monkeypatch.setattr(subject, "_generated_boundary_loss_with_retry", lambda *a, **k: pytest.fail("default dispatched retry"))
    first = loss(model, codec, collection, {"train":1}, contexts, site_policy=policy)
    first["loss"].backward(); gradients = {n:p.grad.clone() if p.grad is not None else None for n,p in model.named_parameters()}
    model.zero_grad(set_to_none=True)
    second = loss(model, codec, collection, {"train":1}, contexts, site_policy=policy, retry_on_replay_mismatch=False)
    second["loss"].backward()
    assert torch.equal(first["loss"], second["loss"])
    assert stripped(first["receipt"]) == stripped(second["receipt"])
    assert second["receipt"]["schema"] == subject.LOSS_SCHEMA
    assert "retry_enabled" not in second["receipt"]
    assert all(p.grad is None if gradients[n] is None else torch.equal(p.grad, gradients[n]) for n,p in model.named_parameters())


@pytest.mark.parametrize("policy", ["first_last", "first_wrong"])
def test_successful_bulk_preserves_old_advanced_indexing_math_and_gradients(policy, monkeypatch):
    model, codec, rows, contexts = scripted()
    collection = collect(model, codec, rows, contexts)
    original = loss(model, codec, collection, {"train":1}, contexts, site_policy=policy)
    original["loss"].backward(); gradients = {n:p.grad.clone() if p.grad is not None else None for n,p in model.named_parameters()}
    model.zero_grad(set_to_none=True)
    monkeypatch.setattr(subject, "_retry_incremental_replay", lambda *a, **k: pytest.fail("successful bulk retried"))
    actual = loss(model, codec, collection, {"train":1}, contexts, site_policy=policy, retry_on_replay_mismatch=True)
    actual["loss"].backward(); receipt = actual["receipt"]
    assert torch.equal(actual["loss"], original["loss"])
    assert receipt["events"] == original["receipt"]["events"]
    assert all(p.grad is None if gradients[n] is None else torch.equal(p.grad, gradients[n]) for n,p in model.named_parameters())
    assert receipt["bulk_replay_batch_count"] == receipt["physical_replay_forward_calls"] == 1
    assert receipt["incremental_retry_batch_count"] == receipt["discarded_bulk_batch_count"] == 0
    assert receipt["replay_attempts"][0]["used_for_loss"] is True
    assert receipt["rows_replayed_once"] and receipt["one_gradient_replay_per_active_row"]


@pytest.mark.parametrize(("kind", "dimension"), [("shared",8)]+
    [(kind,dimension) for kind in ("clause","action","recurrent") for dimension in (8,384,768)])
def test_strict_retry_full_vocabulary_values_and_gradient_preservation(kind, dimension, monkeypatch):
    model, codec, rows, contexts = scripted(kind, dimension=dimension)
    collection = collect(model, codec, rows, contexts)
    force_bulk_mismatch(monkeypatch); before = subject._snapshot(model, torch)
    actual = loss(model, codec, collection, {row["id"]:1 for row in rows}, contexts, retry_on_replay_mismatch=True)
    subject._preserved(model, torch, before)
    receipt = actual["receipt"]; bulk, retry = receipt["replay_attempts"]
    assert receipt["schema"] == "contextual-generated-source-boundary-loss/v2"
    assert not bulk["parity_passed"] and not bulk["used_for_loss"] and bulk["mismatches"]
    assert retry["parity_passed"] and retry["used_for_loss"] and not retry["mismatches"]
    assert retry["maximum_absolute_difference"] == receipt["maximum_replay_logit_absolute_difference"] == 0.
    assert retry["original_batch_membership_preserved"] and retry["collected_prefix_checked"]
    assert not receipt["rows_replayed_once"] and receipt["one_gradient_replay_per_active_row"]
    assert receipt["bulk_replay_batch_count"] == receipt["discarded_bulk_batch_count"] == receipt["incremental_retry_batch_count"] == 1
    assert receipt["physical_replay_forward_calls"] == 1+retry["prefix_steps"]
    assert receipt["physical_replay_row_tokens"] == receipt["bulk_attempted_row_tokens"]+receipt["retry_attempted_row_tokens"]
    by_site = {(row["id"],site["position"]):site["collection_logits"] for row in collection["rows"] for site in row["available_sites"]}
    for event in receipt["events"]:
        assert event["replay_logits"] == by_site[event["id"],event["position"]]
        assert len(event["replay_logits"]) == len(codec["target_vocabulary"])
        expected = torch.nn.functional.cross_entropy(torch.tensor([event["replay_logits"]]),torch.tensor([event["target_token_id"]]))
        assert event["cross_entropy"] == float(expected)
    actual["loss"].backward()
    assert model.body.body.body.output.weight.grad is not None
    assert receipt["additional_optimizer_steps"] == 0


def test_rejected_bulk_graph_is_dropped_before_any_ce(monkeypatch):
    model, codec, rows, contexts = scripted(); collection = collect(model,codec,rows,contexts)
    original_bulk, original_retry = subject._retry_bulk_replay, subject._retry_incremental_replay
    references, phases = [], []
    def bulk(*a, **k):
        value = original_bulk(*a, **k)+.1; references.append(weakref.ref(value))
        value.register_hook(lambda gradient: pytest.fail("discarded bulk graph received gradient"))
        return value
    def retry(*a, **k):
        assert references[0]() is None and not phases
        value = original_retry(*a, **k); phases.append("retried"); return value
    original_ce = torch.nn.functional.cross_entropy
    def ce(*a, **k):
        assert phases == ["retried"]; return original_ce(*a, **k)
    monkeypatch.setattr(subject,"_retry_bulk_replay",bulk); monkeypatch.setattr(subject,"_retry_incremental_replay",retry)
    monkeypatch.setattr(torch.nn.functional,"cross_entropy",ce)
    loss(model,codec,collection,{"train":1},contexts,retry_on_replay_mismatch=True)["loss"].backward()


def several(count=6):
    model,codec,rows,contexts = scripted(count=2); template=deepcopy(rows[0])
    vectors=[s["vector"] for s in contexts["train"]["segments"]]; rows=[];contexts={}
    for i in range(count):
        identity="row"+str(i);text=f"Agency source {i}.\n\nOfficer source {i}."
        rows.append(dict(id=identity,source_text=text,input=template["input"][:]))
        contexts[identity]=contexts_owner._descriptor(text,vectors)
    return model,codec,rows,contexts


def test_retry_preserves_original_batch_groups_and_unselected_rows(monkeypatch):
    model,codec,rows,contexts=several();collection=collect(model,codec,rows,contexts)
    force_bulk_mismatch(monkeypatch)
    counts={row["id"]:1 if i%2 else 2 for i,row in enumerate(rows)}
    receipt=loss(model,codec,collection,counts,contexts,site_policy="first_wrong",retry_on_replay_mismatch=True)["receipt"]
    assert receipt["active_rows"] == receipt["replay_batch_count"] == receipt["incremental_retry_batch_count"] == 3
    for offset in (0,2,4):
        bulk,retry=[a for a in receipt["replay_attempts"] if a["original_batch_offset"]==offset]
        assert bulk["row_ids"] == retry["active_row_ids"] == ["row"+str(offset+1)]
        assert retry["row_ids"] == ["row"+str(offset),"row"+str(offset+1)]
        assert retry["physical_row_tokens"] == 2*bulk["physical_row_tokens"]


@pytest.mark.parametrize("failure",["mismatch","timeout","prefix"])
def test_retry_failure_never_returns_loss_or_mutates_caller(failure,monkeypatch):
    model,codec,rows,contexts=scripted();collection=collect(model,codec,rows,contexts)
    force_bulk_mismatch(monkeypatch); original=subject._retry_incremental_replay
    snapshot=subject._snapshot(model,torch)
    def failed(*a,**k):
        if failure=="timeout": raise TimeoutError("retry deadline")
        if failure=="prefix":
            real=model.next_logits
            def changed(tokens,state):
                logits,updated=real(tokens,state);value=logits.clone();value[:,:,0]=1000.;return value,updated
            with monkeypatch.context() as patch:
                patch.setattr(model,"next_logits",changed);return original(*a,**k)
        return {identity:{position:value+.1 for position,value in sites.items()} for identity,sites in original(*a,**k).items()}
    monkeypatch.setattr(subject,"_retry_incremental_replay",failed)
    monkeypatch.setattr(torch.nn.functional,"cross_entropy",lambda *a,**k:pytest.fail("failed retry created CE"))
    with pytest.raises(TimeoutError if failure=="timeout" else ValueError) as caught:
        loss(model,codec,collection,{"train":1},contexts,retry_on_replay_mismatch=True)
    subject._preserved(model,torch,snapshot)
    if failure=="mismatch":
        attempts=caught.value.replay_receipt["replay_attempts"]
        assert len(attempts)==2 and all(not a["used_for_loss"] and not a["parity_passed"] for a in attempts)
    assert subject.REPLAY_ATOL == subject.REPLAY_RTOL == 2e-5


@pytest.mark.parametrize("offset",[1,-1,True,0.,"0"])
def test_enabled_retry_rejects_rehashed_batch_offset_before_forward(offset,monkeypatch):
    model,codec,rows,contexts=scripted();collection=collect(model,codec,rows,contexts)
    collection["rows"][0]["batch_offset"]=offset;resign(collection)
    monkeypatch.setattr(subject,"_retry_bulk_replay",lambda *a,**k:pytest.fail("forged grouping forwarded"))
    with pytest.raises(ValueError,match="batch offset"):
        loss(model,codec,collection,{"train":1},contexts,retry_on_replay_mismatch=True)


@pytest.mark.parametrize("value",[None,0,1,"true",[]])
def test_retry_option_rejects_nonbool(value):
    model,codec,rows,contexts=scripted();collection=collect(model,codec,rows,contexts)
    with pytest.raises(ValueError,match="boolean"):
        loss(model,codec,collection,{"train":1},contexts,retry_on_replay_mismatch=value)


@pytest.mark.parametrize("invalid",[False,True])
def test_no_selected_sites_create_no_replay_or_graph(invalid,monkeypatch):
    model,codec,rows,contexts=scripted(invalid=invalid);collection=collect(model,codec,rows,contexts)
    monkeypatch.setattr(subject,"_retry_bulk_replay",lambda *a,**k:pytest.fail("empty selection replayed"))
    result=loss(model,codec,collection,{"train":2},contexts,site_policy="first_wrong",retry_on_replay_mismatch=True)
    assert result["loss"] is None and result["receipt"]["replay_attempts"]==[]


def test_retry_continues_stopped_original_rows_with_real_argmax(monkeypatch):
    model,codec,rows,contexts=several(2);rows[0]["input"][0]+=1.
    real=model.next_logits;trace=[]
    with torch.no_grad():
        projected=model.project(subject.legacy._data(torch,rows,transform(model.dimension)))
        marker=float(projected[0,0]);assert marker!=float(projected[1,0])
    def stopped(tokens,state):
        logits,updated=real(tokens,state);changed=logits.clone()
        for index in range(len(tokens)):
            if float(state[1][index,0])==marker:
                for offset in range(tokens.shape[1]):
                    position=int(state[2][index])+offset;changed[index,offset].fill_(-100.)
                    changed[index,offset,2 if position==0 else 3+position%5]=100.
        if tokens.shape[1]==1 and len(tokens)==2:trace.append(tokens[:,0].tolist())
        return changed,updated
    monkeypatch.setattr(model,"next_logits",stopped)
    collection=collect(model,codec,rows,contexts);collected=deepcopy(trace);trace.clear()
    assert collection["rows"][0]["consumed_prefix"]==[1]
    force_bulk_mismatch(monkeypatch)
    receipt=loss(model,codec,collection,{row["id"]:1 for row in rows},contexts,retry_on_replay_mismatch=True)["receipt"]
    retry=receipt["replay_attempts"][-1]
    assert retry["row_ids"]==["row0","row1"] and retry["active_row_ids"]==["row1"]
    assert trace==collected[:retry["prefix_steps"]] and trace[1][0]==2
    assert all(pair[0]!=0 for pair in trace) and retry["parity_passed"]


def test_actual_retry_deadline_preserves_existing_gradients_modes_and_rng(monkeypatch):
    model,codec,rows,contexts=scripted();collection=collect(model,codec,rows,contexts)
    model.train();model.non_action_head.eval()
    for parameter in model.parameters():
        if parameter.requires_grad:parameter.grad=torch.ones_like(parameter)
    snapshot=subject._snapshot(model,torch);force_bulk_mismatch(monkeypatch)
    original=subject._retry_incremental_replay;real=model.next_logits
    def expire_on_first_incremental_step(*a,**k):
        def expired(tokens,state):
            result=real(tokens,state);monkeypatch.setattr(subject.time,"monotonic",lambda:100.);return result
        monkeypatch.setattr(model,"next_logits",expired)
        return original(*a,**k)
    monkeypatch.setattr(subject.time,"monotonic",lambda:0.)
    monkeypatch.setattr(subject,"_retry_incremental_replay",expire_on_first_incremental_step)
    monkeypatch.setattr(torch.nn.functional,"cross_entropy",lambda *a,**k:pytest.fail("timed-out retry created CE"))
    with pytest.raises(TimeoutError):
        loss(model,codec,collection,{"train":1},contexts,retry_on_replay_mismatch=True,deadline=50.)
    subject._preserved(model,torch,snapshot)


def test_parity_uses_exact_allclose_predicate_and_lossless_compact_coordinates():
    original=torch.linspace(-100.,100.,32);original[0]=0.
    tolerance=subject.REPLAY_ATOL+subject.REPLAY_RTOL*original.abs()
    thresholds=original+tolerance
    variants=[original,thresholds,torch.nextafter(thresholds,torch.full_like(thresholds,float('inf'))),
              torch.nextafter(thresholds,torch.full_like(thresholds,-float('inf')))]
    row=dict(id='r',batch_offset=0,replay_prefix_tokens=1,
             selected_sites=[dict(position=0,collection_logits=original.tolist())])
    for observed in variants:
        record=subject._retry_parity(torch,observed.reshape(1,1,32),[row],original_rows=[row],kind='bulk',elapsed_seconds=0.)
        expected=bool(torch.allclose(observed,original,atol=2e-5,rtol=2e-5))
        assert record['parity_passed'] is expected
        indices=(~torch.isclose(observed,original,atol=2e-5,rtol=2e-5)).nonzero().flatten().tolist()
        assert record['mismatches']==([] if expected else [dict(id='r',position=0,vocabulary_indices=indices)])
        assert record['selected_logits']==[dict(id='r',position=0,logits=observed.tolist())]
