"""Behavioral checks for source-bound heading supervision and frozen scope."""
from copy import deepcopy
import json
import re

import pytest
import torch

from ipfs_datasets_py.logic.autoformal import legal_clause_boundary_decoder as base
from ipfs_datasets_py.logic.autoformal import legal_clause_heading_boundary as subject


def authored(text, identity, supported=True):
    return {'candidate_id':identity,'source_text':text,'source_sha256':base.text_sha(text),
        'supported':supported,'clauses':[{'char_start':0,'char_end':len(text)}] if supported else []}


def source(row):
    return {key:row[key] for key in ('candidate_id','source_text','source_sha256')}


def annotation(row, spans=()):
    tokens = base.tokenize(row['source_text'])
    ends = {clause['char_end'] for clause in row['clauses']}
    positive = [i for i,t in enumerate(tokens) if t['char_end'] in ends]
    negative = [i for i,t in enumerate(tokens) if i not in positive and re.fullmatch(r'[^\w\s]',t['text'])
        and any(s['char_start'] <= t['char_start'] < t['char_end'] <= s['char_end'] for s in spans)]
    return {'candidate_id':row['candidate_id'],'source_sha256':row['source_sha256'],
        'true_end_token_indices':positive,'editorial_hard_negative_token_indices':negative,
        'editorial_heading_spans':list(spans),'provenance':subject.ROLE_PROVENANCE}


@pytest.fixture(scope='module')
def parent():
    torch.set_num_threads(1)
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(401)
        network = base.model(torch)
    return base.checkpoint(network,steps=800,training_manifest_sha256='a'*64,tuning_manifest_sha256='b'*64)


@pytest.fixture(scope='module')
def initial(parent):
    return {arm:subject.build_checkpoint(parent,arm=arm,training_manifest_sha256='c'*64,
        tuning_manifest_sha256='d'*64,parent_file_sha256='e'*64) for arm in subject.ARMS}


@pytest.fixture
def rows():
    return [authored('(a) Records.—Board must retain reports.','opaque-a'),
        authored('Council may file a dated notice.','opaque-b'),
        authored('Unless the Panel may disclose files, the Agency must archive all published reports.','opaque-c',False)]


@pytest.fixture
def roles(rows):
    return [annotation(rows[0],[{'char_start':0,'char_end':len('(a) Records.—')}]),annotation(rows[1])]


def inputs(rows, roles):
    ids,features,lengths,labels,scopes,valid = base.tensor_batch(torch,rows,labels=True)
    positive,negative = subject.token_role_masks(torch,rows,roles)
    return (ids,features,lengths),(labels,valid,scopes,positive,negative)


@pytest.mark.parametrize('arm',subject.ARMS)
def test_initial_complete_logits_and_source_rows_exact_parent(parent,initial,rows,arm):
    _,old = base.restore(parent);_,network = subject.restore(initial[arm])
    args = base.tensor_batch(torch,rows)[:3]
    with torch.inference_mode(): before=old(*args);after=network(*args)
    assert all(torch.equal(a,b) for a,b in zip(before,after))
    sources = [source(row) for row in rows]
    assert subject.decoder(initial[arm]).decode(sources)['rows'] == subject.decoder(parent).decode(sources)['rows']
    assert initial['control']['model_state'] == initial['rehearsal']['model_state']
    assert initial[arm]['optimizer_steps'] == 800 and initial[arm]['additional_optimizer_steps'] == 0


@pytest.mark.parametrize('arm',subject.ARMS)
def test_only_residual_trainable_and_scope_has_no_gradient(initial,rows,roles,arm):
    _,network = subject.restore(initial[arm]);params = subject.configure_trainable(network,arm)
    assert sum(p.numel() for p in params) == 1057
    assert {n for n,p in network.named_parameters() if p.requires_grad} == subject.ADAPTER_PARAMETERS
    network.train()
    assert not any(module.training for module in (network.embedding,network.encoder,network.boundary,network.scope))
    args,loss_args = inputs(rows,roles)
    token,scope = network(*args)
    assert token.requires_grad and not scope.requires_grad
    loss,_ = subject.objective_loss(torch,token,*loss_args,arm=arm);loss.backward()
    assert all(p.grad is None for n,p in network.named_parameters() if n not in subject.ADAPTER_PARAMETERS)
    assert torch.count_nonzero(network.boundary_residual.weight.grad) > 0
    assert torch.count_nonzero(network.boundary_hidden.weight.grad) == 0


@pytest.mark.parametrize('arm',subject.ARMS)
def test_training_changes_boundaries_preserves_scope_and_all_parent_state(initial,parent,rows,roles,arm):
    _,network = subject.restore(initial[arm]);params = subject.configure_trainable(network,arm)
    optimizer = torch.optim.Adam(params,lr=.004);assert not optimizer.state
    args,loss_args = inputs(rows,roles);valid = loss_args[1]
    _,old = base.restore(parent)
    with torch.inference_mode(): prior = old(*args)
    for _ in range(3):
        network.train();optimizer.zero_grad(set_to_none=True)
        token,scope = network(*args)
        assert torch.equal(scope,prior[1])
        loss,_ = subject.objective_loss(torch,token,*loss_args,arm=arm);loss.backward()
        torch.nn.utils.clip_grad_norm_(params,5.);optimizer.step()
    assert torch.count_nonzero(network.boundary_hidden.weight.grad) > 0
    assert {int(optimizer.state[p]['step']) for p in params} == {3}
    cp = subject.checkpoint(network,initial_checkpoint=initial[arm],additional_steps=3)
    assert cp['optimizer_steps'] == 803 and cp['optimizer_resumption_supported'] is False
    assert subject.assert_frozen_state(parent['model_state'],cp['model_state']) == cp['frozen_parent_state_sha256']
    _,restored = subject.restore(json.loads(json.dumps(cp)))
    with torch.inference_mode(): actual=network(*args);replayed=restored(*args)
    assert all(torch.equal(a,b) for a,b in zip(actual,replayed))
    assert torch.equal(actual[1],prior[1]) and not torch.equal(actual[0][valid],prior[0][valid])
    assert torch.equal(actual[0][~valid],prior[0][~valid])


def test_control_gradient_is_exact_original_supported_token_BCE(rows,roles):
    _,args = inputs(rows,roles);labels,valid,supported,positive,negative = args
    logits = torch.linspace(-3,4,labels.numel(),dtype=torch.float64).reshape_as(labels).requires_grad_()
    loss,parts = subject.objective_loss(torch,logits,*args,arm='control')
    eligible = valid & supported.bool()[:,None]
    expected = torch.nn.functional.binary_cross_entropy_with_logits(logits[eligible],labels[eligible].double(),pos_weight=torch.tensor(12.))
    assert loss == expected and parts['auxiliary_weight'] == 0.
    a = torch.autograd.grad(loss,logits,retain_graph=True)[0]
    b = torch.autograd.grad(expected,logits)[0]
    assert torch.equal(a,b)


@pytest.mark.parametrize('arm',subject.ARMS)
@pytest.mark.parametrize('scale',[.1,1.,100.])
def test_objective_value_gradients_and_class_balancing_match_scalar_oracle(rows,roles,arm,scale):
    _,args = inputs(rows,roles);labels,valid,supported,positive,negative = args
    labels = labels.double();args=(labels,valid,supported,positive,negative)
    logits = (torch.linspace(-2,3,labels.numel(),dtype=torch.float64)*scale).reshape_as(labels).requires_grad_()
    eligible = valid & supported.bool()[:,None]
    loss,parts = subject.objective_loss(torch,logits,*args,arm=arm)
    scalar = []
    for value,label in zip(logits[eligible],labels[eligible]):
        scalar.append(12*torch.logaddexp(torch.zeros_like(value),-value) if label else torch.logaddexp(torch.zeros_like(value),value))
    common = torch.stack(scalar).mean()
    pos = torch.stack([torch.logaddexp(torch.zeros_like(v),-v) for v in logits[positive]]).mean()
    neg = torch.stack([torch.logaddexp(torch.zeros_like(v),v) for v in logits[negative]]).mean()
    oracle = common+subject.AUXILIARY_WEIGHTS[arm]*(pos+neg)/2
    torch.testing.assert_close(loss,oracle,rtol=1e-12,atol=1e-12)
    a=torch.autograd.grad(loss,logits,retain_graph=True)[0];b=torch.autograd.grad(oracle,logits)[0]
    torch.testing.assert_close(a,b,rtol=1e-12,atol=1e-12)
    assert torch.count_nonzero(a[~eligible]) == 0
    assert parts['auxiliary_positive_count'] == int(positive.sum())
    assert parts['auxiliary_negative_count'] == int(negative.sum())
    assert parts['eligible_token_count'] == int(eligible.sum())
    assert abs(parts['base_bce']-(12*parts['base_positive_bce_sum']+parts['base_negative_bce_sum'])/int(eligible.sum())) < 1e-10


def test_auxiliary_gradient_is_zero_outside_authored_token_roles(rows,roles):
    _,args=inputs(rows,roles);labels,valid,supported,positive,negative=args
    logits=torch.zeros_like(labels,requires_grad=True)
    control,_=subject.objective_loss(torch,logits,*args,arm='control')
    target,_=subject.objective_loss(torch,logits,*args,arm='rehearsal')
    gradient=torch.autograd.grad(target-control,logits)[0]
    assert torch.count_nonzero(gradient[~(positive|negative)]) == 0
    assert bool((gradient[positive] < 0).all()) and bool((gradient[negative] > 0).all())
    assert abs(float(gradient[positive].sum())+.125) < 1e-7
    assert abs(float(gradient[negative].sum())-.125) < 1e-7


@pytest.mark.parametrize('bad',['empty_positive','empty_negative','unsupported_negative','padding_negative','positive_as_negative','omitted_positive','float_mask','nonbinary_labels'])
def test_invalid_or_unbalanced_loss_masks_are_rejected(rows,roles,bad):
    _,args=inputs(rows,roles);labels,valid,supported,positive,negative=[x.clone() for x in args]
    if bad=='empty_positive': labels.zero_();positive.zero_()
    if bad=='empty_negative': negative.zero_()
    if bad=='unsupported_negative': negative[2,0]=True
    if bad=='padding_negative': negative[0,-1]=True
    if bad=='positive_as_negative': negative |= positive
    if bad=='omitted_positive': positive[1].zero_()
    if bad=='float_mask': valid=valid.float()
    if bad=='nonbinary_labels': labels[0,0]=.5
    with pytest.raises(ValueError): subject.objective_loss(torch,torch.zeros_like(labels),labels,valid,supported,positive,negative,arm='control')


def test_roles_cover_all_editorial_punctuation_and_exclude_scope_negatives(rows,roles):
    positive,negative=subject.token_role_masks(torch,rows,roles)
    tokens=base.tokenize(rows[0]['source_text'])
    assert [t['text'] for i,t in enumerate(tokens) if negative[0,i]] == ['(',')','.','—']
    assert [int(row.sum()) for row in positive] == [1,1,0]
    assert int(negative[1:].sum()) == 0
    lookup={r['candidate_id']:r for r in roles}
    other=subject.token_role_masks(torch,rows,lookup)
    assert all(torch.equal(a,b) for a,b in zip((positive,negative),other))


@pytest.mark.parametrize('change',['source_hash','identity','extra_key','provenance','omitted_punctuation','nonpunctuation','gold_end_negative','bool_index','span_outside','overlap_spans','missing_true_end'])
def test_mutated_role_records_reject_even_with_other_fields_preserved(rows,roles,change):
    record=deepcopy(roles[0])
    if change=='source_hash':record['source_sha256']='f'*64
    if change=='identity':record['candidate_id']='other'
    if change=='extra_key':record['rule']={}
    if change=='provenance':record['provenance']='inferred'
    if change=='omitted_punctuation':record['editorial_hard_negative_token_indices'].pop()
    if change=='nonpunctuation':record['editorial_hard_negative_token_indices']=[1]
    if change=='gold_end_negative':record['editorial_hard_negative_token_indices']+=record['true_end_token_indices']
    if change=='bool_index':record['editorial_hard_negative_token_indices'][0]=False
    if change=='span_outside':record['editorial_heading_spans'][0]['char_end']=len(rows[0]['source_text'])+1
    if change=='overlap_spans':record['editorial_heading_spans']*=2
    if change=='missing_true_end':record['true_end_token_indices']=[]
    with pytest.raises(ValueError):subject.validate_token_roles(rows[0],record)


def test_gold_end_inside_an_editorial_span_is_not_negative(rows):
    row=rows[0]
    record=annotation(row,[{'char_start':0,'char_end':len(row['source_text'])}])
    verified=subject.validate_token_roles(row,record)
    assert not set(verified['true_end_token_indices']) & set(verified['editorial_hard_negative_token_indices'])


def test_missing_duplicate_or_unsupported_annotation_is_rejected(rows,roles):
    for wrong in (roles[:1],roles+[deepcopy(roles[0])],roles+[annotation(rows[2])]):
        with pytest.raises(ValueError):subject.token_role_masks(torch,rows,wrong)


@pytest.mark.parametrize('name',['embedding.weight','encoder.weight_ih_l0','boundary.weight','scope.weight'])
def test_repaired_hash_cannot_mutate_frozen_parent_tensors(initial,name):
    cp=deepcopy(initial['rehearsal']);cp['additional_optimizer_steps']=1;cp['optimizer_steps']+=1
    cp['model_state'][name][0][0]+=.1
    cp['frozen_parent_state_sha256']=subject.digest(subject.frozen_state(cp['model_state']))
    with pytest.raises(ValueError,match='frozen'):subject.restore(cp)


@pytest.mark.parametrize('mutate',[
    lambda c:c.update(extra=True),lambda c:c.update(implementation_sha256='0'*64),
    lambda c:c.update(parent_checkpoint_sha256='0'*64),lambda c:c.update(initial_model_state_sha256='0'*64),
    lambda c:c.update(additional_optimizer_steps=-1),lambda c:c.update(additional_optimizer_steps=401),
    lambda c:c.update(optimizer_steps=801),lambda c:c.update(optimizer_resumption_supported=True),
    lambda c:c['model_state']['boundary_residual.bias'].append(0),
    lambda c:c['model_state']['boundary_residual.bias'].__setitem__(0,float('nan')),
    lambda c:c['model_state']['boundary_residual.bias'].__setitem__(0,1.),
    lambda c:c['training_config'].__setitem__('auxiliary_weight',999),
])
def test_checkpoint_contract_shape_finiteness_and_zero_initial_state(initial,mutate):
    cp=deepcopy(initial['rehearsal']);mutate(cp)
    with pytest.raises(ValueError):subject.restore(cp)


def test_identifiers_do_not_enter_numeric_input_and_label_payloads_rejected(initial,rows):
    sources=[source(r) for r in rows]
    decoder=subject.decoder(initial['rehearsal'])
    original=decoder.decode(sources)
    changed=decoder.decode([{**r,'candidate_id':str(i)} for i,r in enumerate(sources)])
    assert all(a['boundary_logits']==b['boundary_logits'] and a['scope_logits']==b['scope_logits'] for a,b in zip(original['rows'],changed['rows']))
    with pytest.raises(ValueError,match='source-only'):decoder.decode([{**sources[0],'editorial_heading_spans':[]}])
    with pytest.raises(ValueError,match='profile'):decoder.decode(sources,source_profile='unrestricted_nested_scope')


def test_initialization_and_restore_preserve_rng(parent,initial):
    torch.manual_seed(573);state=torch.random.get_rng_state().clone()
    subject.build_checkpoint(parent,arm='control',training_manifest_sha256='c'*64,tuning_manifest_sha256='d'*64,parent_file_sha256='e'*64)
    assert torch.equal(state,torch.random.get_rng_state())
    subject.restore(initial['rehearsal'])
    assert torch.equal(state,torch.random.get_rng_state())
