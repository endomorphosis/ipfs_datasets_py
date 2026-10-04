"""Source-only extraction and negative-control identity guards."""
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import random

import pytest

ROOT=Path(__file__).resolve().parents[5]
SPEC=importlib.util.spec_from_file_location('slot_benchmark_test',ROOT/'scripts/ops/autoencoder/benchmark_decoder_source_slot_probe.py')
driver=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(driver)


@pytest.mark.parametrize('key,value',[('ridge_lambda',.01),('validation_tuning',True),('max_rule_slots',16),
    ('fixed_encoder_context_tokens',1024),('decoder_training_executed',True),('optimizer_steps',False),
    ('feature_order',driver.FEATURES[:-1]),('count_classes',[1,2,4,8])])
def test_predeclared_probe_recipe_is_fixed(key,value):
    plan=deepcopy(driver.FIXED);driver.validate_plan(plan);plan[key]=value
    with pytest.raises(ValueError,match='fixed probe recipe'):
        driver.validate_plan(plan)


def balanced():
    rows=[];refs=[]
    for count in (1,2,4,8):
        for i in range(12):
            name=f'{count}:{i:02}'
            rows.append(dict(id=name,source_sha256=hashlib.sha256(name.encode()).hexdigest(),features=[float(count),float(i)]))
            refs.append(dict(id=name,clause_count=count))
    return rows,refs


@pytest.mark.parametrize('kind',driver.CONTROLS)
def test_controls_are_bijections_and_preserve_identity(kind):
    rows,refs=balanced();before=deepcopy(rows)
    actual,control=driver.control_features(rows,refs,kind)
    assignment=control['source_assignment'];by_id={r['id']:r for r in rows};counts={r['id']:r['clause_count'] for r in refs}
    assert set(assignment)==set(assignment.values())==set(by_id)
    for a,b in zip(actual,rows):
        assert a['id']==b['id'] and a['source_sha256']==b['source_sha256']
        assert a['features']==by_id[assignment[b['id']]]['features']
        if kind=='source_shuffle':assert assignment[b['id']]!=b['id'] and counts[b['id']]==counts[assignment[b['id']]]
        if kind=='cross_length_shuffle':assert counts[b['id']]!=counts[assignment[b['id']]]
    assert rows==before


def test_cross_length_control_refuses_unbalanced_or_missing_references():
    rows,refs=balanced()
    with pytest.raises(ValueError,match='balanced48'):
        driver.control_features(rows[:-1],refs[:-1],'cross_length_shuffle')
    with pytest.raises(ValueError,match='identity'):
        driver.control_features(rows,refs[:-1],'source_shuffle')


def fixture_model():
    torch=pytest.importorskip('torch')
    from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core
    from ipfs_datasets_py.logic.formalization.autoencoder.decoder_gradient_replay import gradient_digest
    class Body(torch.nn.Module):
        def __init__(self):
            super().__init__();self.condition=torch.nn.Linear(384,32);self.source_to_embedding=torch.nn.Linear(384,16,bias=False)
        def start(self,x):return (torch.tanh(self.condition(x)).unsqueeze(0),x,torch.zeros(len(x),dtype=torch.long))
        def next_logits(self,*args):raise AssertionError('prefix decoding must never execute')
    class Model(torch.nn.Module):
        dimension=384
        def __init__(self):super().__init__();self.body=Body()
        def project(self,x):return x+.125
        def describe(self):return {'schema':'source-cardinality-decoder-development/v1'}
        def next_logits(self,*args):raise AssertionError('prefix decoding must never execute')
    with torch.random.fork_rng(devices=[]):model=Model()
    rows=[dict(id=str(i),source_sha256=hashlib.sha256(str(i).encode()).hexdigest(),input=[float(i+1)]*384) for i in range(2)]
    transform=dict(mode='center_rms',mean=[.5]*384,scale=2.,origin='training_only')
    return torch,core,gradient_digest,model,rows,transform


def test_extraction_matches_actual_conditioning_without_target_access_or_mutation():
    torch,core,gradient,model,rows,transform=fixture_model()
    old=torch.get_num_threads();torch.set_num_threads(1)
    try:
        for p in model.parameters():p.grad=torch.ones_like(p)
        model.body.eval();modes={n:m.training for n,m in model.named_modules()}
        before=core.tensor_digest(model);grads=gradient(model);rng=torch.get_rng_state().clone();py=random.getstate()
        result=driver.extract_features(model,rows,transform=transform,core=core,gradient_digest=gradient)
        expected=torch.tensor([[.375]*384,[.875]*384],dtype=torch.float32)
        features=result['rows']
        assert [r['features'] for r in features['projected_source']]==expected.tolist()
        with torch.inference_mode():combined=torch.cat((model.body.start(expected)[0].squeeze(0),model.body.source_to_embedding(expected)),1)
        assert [r['features'] for r in features['conditioning']]==combined.tolist()
        assert not result['report']['prefix_access'] and not result['report']['count_label_access']
        assert core.tensor_digest(model)==before and gradient(model)==grads
        assert modes=={n:m.training for n,m in model.named_modules()}
        assert torch.equal(rng,torch.get_rng_state()) and py==random.getstate()
    finally:torch.set_num_threads(old)


def test_extraction_rejects_targets_and_restores_rng_on_fault():
    torch,core,gradient,model,rows,transform=fixture_model()
    old=torch.get_num_threads();torch.set_num_threads(1)
    try:
        with pytest.raises(ValueError,match='source-only'):
            driver.extract_features(model,[{**rows[0],'target_ids':[1,2]}],transform=transform,core=core,gradient_digest=gradient)
        original=model.body.start
        def stochastic(x):torch.rand(1);return original(x)
        model.body.start=stochastic
        rng=torch.get_rng_state().clone()
        with pytest.raises(ValueError,match='consumed RNG'):
            driver.extract_features(model,rows,transform=transform,core=core,gradient_digest=gradient)
        assert torch.equal(rng,torch.get_rng_state())
    finally:torch.set_num_threads(old)


def test_extraction_deadline_never_returns_partial(monkeypatch):
    torch,core,gradient,model,rows,transform=fixture_model()
    old=torch.get_num_threads();torch.set_num_threads(1)
    try:
        ticks=iter([0.,2.]);monkeypatch.setattr(driver.time,'monotonic',lambda:next(ticks))
        with pytest.raises(TimeoutError):driver.extract_features(model,rows,transform=transform,core=core,gradient_digest=gradient,max_seconds=1.)
    finally:torch.set_num_threads(old)
