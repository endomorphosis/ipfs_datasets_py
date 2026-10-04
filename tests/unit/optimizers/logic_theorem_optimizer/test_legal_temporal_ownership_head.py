"""Numerical isolation, occurrence binding and checkpoint invariants."""
from copy import deepcopy
import hashlib
import os
os.environ['CUDA_VISIBLE_DEVICES']='-1'
import pytest
import torch
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_temporal_ownership_head as own


def query(text, needle='within 10 days', *, last=False, identity=None):
    start=text.rindex(needle) if last else text.index(needle)
    return {'id':identity or hashlib.sha256((text+str(start)).encode()).hexdigest(), 'source_text':text,
            'source_sha256':hashlib.sha256(text.encode()).hexdigest(),
            'proposed_time_span':{'char_start':start,'char_end':start+len(needle)}}


def rows(prefix, count):
    result=[]
    for group in range(count):
        for label in own.CLASSES:
            result.append({**query(f'The {prefix}{group} {label} Registry shall file notice within 10 days.'),
                           'label':label,'group_id':f'{prefix}-{group}'})
    return result


@pytest.fixture
def setup(monkeypatch):
    # The fixture isolates this new runtime; production integration validates
    # the complete independently frozen temporal400 parent separately.
    monkeypatch.setattr(own.parent_runtime,'validate_checkpoint',lambda _:None)
    config={'seed':1730,'hidden_size':32,'embedding_dim':16,'latent_dimension':0,'trigger_enabled':True}
    model=own.mixed._model(torch,config)
    parent={'model_config':config,'model_state':{k:v.detach().tolist() for k,v in model.state_dict().items()}}
    return parent,rows('train',4),rows('tune',2)


def checkpoint(setup, arm='frozen_occurrence', seed=1730):
    parent,train,tune=setup
    return own.build_checkpoint(parent,train,tune,arm=arm,seed=seed,parent_file_sha256='1'*64)


@pytest.mark.parametrize('arm,expected',[('source_only',8356),('frozen_occurrence',8356),('finetune_occurrence',21028)])
def test_trainable_inventory_and_exact_source_copy(setup,arm,expected):
    cp=checkpoint(setup,arm);_,model,_=own._restore(cp)
    assert sum(p.numel() for p in model.parameters() if p.requires_grad)==expected
    assert {k.removeprefix('source.'):v for k,v in cp['model_state'].items() if k.startswith('source.')}==setup[0]['model_state']
    assert all(not p.requires_grad for n,p in model.source.named_parameters() if not (arm=='finetune_occurrence' and n.startswith('encoder.')))


def test_initial_head_tensors_identical_across_matched_arms(setup):
    values=[checkpoint(setup,arm)['model_state'] for arm in own.ARMS]
    assert values[0]==values[1]==values[2]
    query_rows=own.source_queries(setup[1][:4])
    x=own.TemporalOwnershipHead(checkpoint(setup,'frozen_occurrence')).predict_many(query_rows)
    y=own.TemporalOwnershipHead(checkpoint(setup,'finetune_occurrence')).predict_many(query_rows)
    assert x==y


def test_source_only_baseline_invariant_to_distinct_same_text_occurrences(setup):
    text='within 10 days, Registry shall file; Board may archive within 10 days.'
    queries=[query(text),query(text,last=True)]
    baseline=own.TemporalOwnershipHead(checkpoint(setup,'source_only')).predict_many(queries)
    assert baseline[0]['logits']==baseline[1]['logits']
    assert baseline[0]['time_token_span']!=baseline[1]['time_token_span']
    occurrence=own.TemporalOwnershipHead(checkpoint(setup)).predict_many(queries)
    assert occurrence[0]['logits']!=occurrence[1]['logits']


def test_ID_and_labels_do_not_enter_source_only_prediction(setup):
    model=own.TemporalOwnershipHead(checkpoint(setup));q=query('Registry shall file within 10 days.')
    a=model.predict_many([q])[0];b=model.predict_many([{**q,'id':'condition-gold-label'}])[0]
    assert a['logits']==b['logits'] and a['probabilities']==b['probabilities']
    with pytest.raises(ValueError,match='four-field'):model.predict_many([{**q,'label':'condition'}])
    with pytest.raises(ValueError,match='four-field'):model.predict_many([{**q,'owner_span':[0,8]}])


@pytest.mark.parametrize('mutation',['sha','unaligned','reversed','bool','outside','extra'])
def test_proposed_span_and_source_are_exactly_bound(mutation):
    q=query('Registry shall file within 10 days.')
    if mutation=='sha':q['source_sha256']='0'*64
    if mutation=='unaligned':q['proposed_time_span']['char_start']+=1
    if mutation=='reversed':q['proposed_time_span']['char_end']=0
    if mutation=='bool':q['proposed_time_span']['char_start']=True
    if mutation=='outside':q['proposed_time_span']['char_end']=1000
    if mutation=='extra':q['proposed_time_span']['owner']='norm'
    with pytest.raises(ValueError):own._query(q)


def test_same_source_different_intervals_allowed_but_same_query_rejected():
    q=query('Within 10 days, Registry shall file within 10 days.')
    own._query(q);own._query(query(q['source_text'],last=True))
    r=rows('train',4);r[1]={**r[0],'label':'condition','id':'different'}
    with pytest.raises(ValueError,match='duplicate'):own._split(r)


def test_sampler_four_complete_quartets_and_resume_order(setup):
    records,_,groups=own._splits(setup[1],setup[2])
    for step in (0,1,49,99,199):
        indices,names=own.batch_indices(groups,1730,step)
        assert len(indices)==16 and len(names)==4
        assert [sum(records[i]['label']==c for i in indices) for c in range(4)]==[4]*4
        assert (indices,names)==own.batch_indices(groups,1730,step)


@pytest.mark.parametrize('arm',own.ARMS)
def test_exact_two_step_resume_and_frozen_gradient_isolation(setup,arm):
    initial=checkpoint(setup,arm);train,tune=setup[1:]
    both,report=own.train(initial,train,tune,additional_steps=2)
    first,_=own.train(initial,train,tune,additional_steps=1)
    resumed,tail=own.train(first,train,tune,additional_steps=1)
    assert both['model_state']==resumed['model_state'] and both['optimizer_state']==resumed['optimizer_state']
    assert report['trace'][1]==tail['trace'][0]
    assert report['encoder_source_evaluations']==32 and report['encoder_batch_forwards']==2
    assert set(both['optimizer_state']['parameters'])==set(report['trainable_parameters'])
    for name in initial['model_state']:
        if name.startswith('source.') and not (arm=='finetune_occurrence' and name.startswith('source.encoder.')):
            assert both['model_state'][name]==initial['model_state'][name]
    if arm=='finetune_occurrence':
        assert any(both['model_state'][k]!=initial['model_state'][k] for k in initial['model_state'] if k.startswith('source.encoder.'))


def test_source_features_are_from_actual_parent_encoder(setup):
    _,model,_=own._restore(checkpoint(setup));records=[own._query(q) for q in own.source_queries(setup[1][:2])]
    captured=[];hook=model.source.encoder.register_forward_hook(lambda _m,_a,out:captured.append(out[0]))
    with torch.no_grad():features=model.features(records)
    hook.remove();encoded,lengths=torch.nn.utils.rnn.pad_packed_sequence(captured[0],batch_first=True)
    for i,r in enumerate(records):
        a,b=r['time_tokens'];assert torch.equal(features[i,:64],encoded[i,:lengths[i]].mean(0))
        assert torch.equal(features[i,64:128],encoded[i,a]);assert torch.equal(features[i,128:192],encoded[i,b])
        assert torch.equal(features[i,192:],encoded[i,a:b+1].mean(0))


def test_loss_receipt_matches_independent_logsumexp_oracle(setup):
    _,report=own.train(checkpoint(setup),*setup[1:],additional_steps=1)
    row=report['trace'][0];logits=torch.tensor(row['logits'],dtype=torch.float64);labels=torch.tensor(row['labels'])
    wanted=(torch.logsumexp(logits,dim=1)-logits[torch.arange(16),labels]).mean().item()
    assert abs(wanted-row['loss'])<2e-7


@pytest.mark.parametrize('field',['source.byte_embedding.weight','source.encoder.weight_ih_l0','source.start.weight'])
def test_repaired_hash_cannot_change_frozen_parent_tensor(setup,field):
    cp,_=own.train(checkpoint(setup),*setup[1:],additional_steps=1)
    cp['model_state'][field][0][0]+=.125
    with pytest.raises(ValueError,match='frozen parent'):own._restore(cp)


@pytest.mark.parametrize('mutation',['steps','moment','negative_moment','NaN','predecessor','config','authority','manifest'])
def test_corrupt_checkpoint_or_resume_binding_rejected(setup,mutation):
    cp,_=own.train(checkpoint(setup),*setup[1:],additional_steps=1)
    if mutation=='steps':cp['optimizer_steps']=201
    if mutation=='moment':cp['optimizer_state']['parameters']['head.0.weight']['step']=0
    if mutation=='negative_moment':cp['optimizer_state']['parameters']['head.0.weight']['exp_avg_sq'][0][0]=-1
    if mutation=='NaN':cp['model_state']['head.0.weight'][0][0]=float('nan')
    if mutation=='predecessor':cp['preceding_checkpoint_sha256']=None
    if mutation=='config':cp['config']['threshold']=.5
    if mutation=='authority':cp['statutory_semantics_verified']=True
    if mutation=='manifest':cp['training_manifest_sha256']='0'*64
    with pytest.raises(ValueError):
        if mutation=='manifest':own.train(cp,*setup[1:],additional_steps=1)
        else:own._restore(cp)


def test_tuning_source_group_and_ID_overlap_rejected(setup):
    train,tune=setup[1:]
    with pytest.raises(ValueError,match='overlap'):own._splits(train,deepcopy(train))
    tune=deepcopy(tune);tune[0]['group_id']=train[0]['group_id']
    with pytest.raises(ValueError):own._splits(train,tune)


def test_ambiguity_always_defers_and_fixed_confidence_is_not_a_training_gate(setup):
    cp=checkpoint(setup);_,model,_=own._restore(cp)
    with torch.no_grad():
        model.head[2].weight.zero_();model.head[2].bias.copy_(torch.tensor([0.,0.,0.,10.]))
    decoder=own.TemporalOwnershipHead(cp);decoder.model=model
    row=decoder.predict_many([query('Registry shall file within 10 days.')])[0]
    assert row['confidence']>.99 and row['owner_type'] is None and row['reason']=='predicted_ambiguous'
    assert row['owner_occurrence_resolved'] is False


@pytest.mark.parametrize('field,value',[('max_steps',200.),('batch_size',16.),('parent_optimizer_moments_transferred',0)])
def test_config_numeric_and_boolean_aliases_rejected(setup,field,value):
    cp=checkpoint(setup);cp['config'][field]=value
    with pytest.raises(ValueError,match='training config'):own._restore(cp)


def test_parent_config_integer_float_alias_rejected(setup):
    cp=checkpoint(setup);cp['model_config']['hidden_size']=32.
    with pytest.raises(ValueError,match='parent binding'):own._restore(cp)


def test_zero_update_tensor_numeric_alias_rejected(setup):
    cp=checkpoint(setup);cp['model_state']['source.actor_boundary.bias'][0]=0
    with pytest.raises(ValueError,match='zero-update'):own._restore(cp)
