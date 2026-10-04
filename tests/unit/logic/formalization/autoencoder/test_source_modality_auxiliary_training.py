"""Authored-bank isolation and raw full-vocabulary modality supervision."""
from collections import Counter
from copy import deepcopy
import math
import random
import time

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import source_modality_auxiliary_training as subject
from ipfs_datasets_py.logic.formalization.autoencoder import authored_scalar_holdout as authored
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core
from . import test_ordered_clause_recurrent_decoder_experiment as recurrent_fixture


@pytest.fixture(autouse=True)
def one_cpu():
    old = torch.get_num_threads(); torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


def deadline():
    return time.monotonic()+30


def corpus(dimension=8):
    codec = dict(schema="typed-json-lexical/v1",target_vocabulary=list(authored.VOCABULARY))
    rows,refs = [],[]
    phrases = ({"O":"must","P":"may","F":"must not"},
               {"O":"is required to","P":"is allowed to","F":"is forbidden to"})
    for actor_index,actor in enumerate(authored.ACTORS):
        for action in [authored.ACTIONS[(actor_index+j)%5] for j in range(3)]:
            for object_ in authored.OBJECTS:
                for modality in ("O","P","F"):
                    for style in (0,1):
                        index=len(rows);angle=(index+1)/200
                        vector=[math.cos(angle),math.sin(angle)]+[0.]*(dimension-2)
                        text=f"The {actor} {phrases[style][modality]} {action} the {object_}."
                        identity=f"training:{index}"
                        rows.append(dict(id=identity,source_text=text,input=vector,wording_style=style))
                        refs.append(dict(id=identity,target={"rules":[dict(actor=actor,action=action,object=object_,
                            modality=modality,conditions=[],exceptions=[],temporal=[])]}))
    used=[]
    counts={('O',0):19,('O',1):16,('P',0):21,('P',1):16,('F',0):21,('F',1):20}
    for key,count in counts.items():
        used.extend(r for r,v in zip(rows,refs) if (v['target']['rules'][0]['modality'],r['wording_style'])==key)
        used[-30:]=used[-30:][:count]
    assert len(used)==113
    occurrences=used+used[:67];paragraphs=[];offset=0
    for length in (1,2,4,8):
        for _ in range(12):
            paragraphs.append(dict(id=f"paragraph:{len(paragraphs)}",
                source_text="\n\n".join(r['source_text'] for r in occurrences[offset:offset+length])))
            offset+=length
    forbidden={split:[dict(id='forbidden:'+split,source_text='Reserved '+split+' source.',
        input=[0.,0.,1.]+[0.]*(dimension-3))] for split in subject.FORBIDDEN_SPLITS}
    return dict(source_rows=rows,references=refs,paragraph_training_rows=paragraphs,
                forbidden_rows_by_split=forbidden,codec=codec)


def hashes(data):
    return {key:subject.digest(value) for key,value in data.items()}


def validator(value):
    return dict(valid=True,canonical_ir=value)


def bank(kind='used113',dimension=8):
    data=corpus(dimension)
    return subject.prepare_bank(**data,bank_kind=kind,input_sha256=hashes(data),
                                validate_rule=validator,deadline=deadline()),data


def model_for(monkeypatch,dimension=8,fitted=False,kind='recurrent'):
    codec=dict(schema='typed-json-lexical/v1',target_vocabulary=list(authored.VOCABULARY))
    monkeypatch.setattr(recurrent_fixture,'setup',lambda _dimension:(None,codec))
    recurrent,factorized,_,_=recurrent_fixture.fixture(dimension,fitted=fitted)
    return (recurrent if kind=='recurrent' else factorized),codec


def transform(dimension):
    return dict(mode='center_rms',mean=[.02]*dimension,scale=1.3,origin='training_only')


def cache_for(monkeypatch,kind='used113',dimension=8,fitted=False,model_kind='recurrent'):
    prepared,data=bank(kind,dimension);model,codec=model_for(monkeypatch,dimension,fitted,model_kind)
    cache=subject.prepare_tensor_cache(torch,model,prepared,codec=codec,input_transform=transform(dimension),
        seed=1729,deadline=deadline())
    return model,cache,prepared,data


@pytest.mark.parametrize('kind,count',[('used113',113),('full180',180)])
@pytest.mark.parametrize('dimension',[8,384,768])
def test_banks_are_closed_complete_training_only_and_do_not_mutate_inputs(kind,count,dimension):
    data=corpus(dimension);before=deepcopy(data)
    actual=subject.prepare_bank(**data,bank_kind=kind,input_sha256=hashes(data),validate_rule=validator,deadline=deadline())
    assert data==before and len(actual['rows'])==count and actual['dimension']==dimension
    assert actual['bank_sha256']==subject.digest({k:v for k,v in actual.items() if k!='bank_sha256'})
    assert all(actual[k] is False for k in subject.FALSE)
    assert sum(item['count'] for item in actual['strata'])==count
    assert actual['source_inventory']==[{k:row[k] for k in ('id','source_sha256','input_sha256','target_sha256','modality','wording_style')} for row in actual['rows']]


def test_original_adapter_authenticates_full_ids_vectors_targets_and_declared_style():
    data=corpus();raw=[];cache=[]
    for source,ref in zip(data['source_rows'],data['references']):
        raw.append(dict(source,embedding=source['input'],target=ref['target'],split='train'))
        cache.append(dict(id=source['id'],source_text=source['source_text'],input=source['input'],
                          target_ids=authored._encode(ref['target'],data['codec'])))
    before=deepcopy((raw,cache))
    actual=subject.adapt_original_training_bank(raw,cache,codec=data['codec'],deadline=deadline())
    assert actual['source_rows']==data['source_rows'] and actual['references']==data['references']
    assert (raw,cache)==before
    for kind in ('split','style','target','vector','cache_target','duplicate'):
        original,cached=deepcopy(before)
        if kind=='split':original[0]['split']='validation'
        elif kind=='style':original[0]['wording_style']=1
        elif kind=='target':original[0]['target']['rules'][0]['modality']='P'
        elif kind=='vector':cached[0]['input']=cached[1]['input']
        elif kind=='cache_target':cached[0]['target_ids'][-2]=3
        else:cached[1]=deepcopy(cached[0])
        with pytest.raises(ValueError):subject.adapt_original_training_bank(original,cached,codec=data['codec'],deadline=deadline())


@pytest.mark.parametrize('kind',['id','text','normalized_text','vector','paragraph_clause'])
def test_all_forbidden_identity_text_and_vector_routes_rejected(kind):
    data=corpus();row=data['source_rows'][0];blocked=data['forbidden_rows_by_split']['exposed_holdout'][0]
    if kind=='id':blocked['id']=row['id']
    elif kind=='text':blocked['source_text']=row['source_text']
    elif kind=='normalized_text':blocked['source_text']='  '+row['source_text'].upper()+'  '
    elif kind=='vector':blocked['input']=deepcopy(row['input'])
    else:blocked['source_text']='Different first clause.\n\n'+row['source_text']
    with pytest.raises(ValueError,match='forbidden'):
        subject.prepare_bank(**data,bank_kind='full180',input_sha256=hashes(data),validate_rule=validator,deadline=deadline())


@pytest.mark.parametrize('kind',['bad_hash','label','style_bool','style','vector_bool','nan','width','missing_ref','unseen_paragraph','extra_label','missing_forbidden'])
def test_bad_or_unbound_bank_inputs_fail_closed(kind):
    data=corpus();old_hashes=hashes(data)
    if kind=='bad_hash':data['source_rows'][0]['id']='rebound'
    elif kind=='label':data['references'][0]['target']['rules'][0]['modality']='P'
    elif kind=='style_bool':data['source_rows'][0]['wording_style']=True
    elif kind=='style':data['source_rows'][0]['wording_style']=1
    elif kind=='vector_bool':data['source_rows'][0]['input'][0]=True
    elif kind=='nan':data['source_rows'][0]['input'][0]=float('nan')
    elif kind=='width':data['source_rows'][0]['input'].append(0.)
    elif kind=='missing_ref':data['references'].pop()
    elif kind=='unseen_paragraph':data['paragraph_training_rows'][0]['source_text']='Not an original clause.'
    elif kind=='extra_label':data['forbidden_rows_by_split']['validation'][0]['target']='hidden label'
    else:data['forbidden_rows_by_split'].pop('test')
    with pytest.raises((ValueError,KeyError)):
        subject.prepare_bank(**data,bank_kind='used113',input_sha256=old_hashes,validate_rule=validator,deadline=deadline())


@pytest.mark.parametrize('kind',['used113','full180'])
def test_sampler_has_exact_balanced_exposure_is_pure_and_preserves_rng(monkeypatch,kind):
    model,cache,_,_=cache_for(monkeypatch,kind)
    rng=torch.get_rng_state().clone();python_rng=random.getstate();seen=Counter();strata=Counter()
    for step in range(340):
        chosen=subject.select_indices(cache,step)
        assert chosen==subject.select_indices(cache,step) and len(set(chosen))==6
        for i in chosen:seen[i]+=1;strata[cache._rows[i][2:]]+=1
    assert len(seen)==(113 if kind=='used113' else 180) and sum(seen.values())==2040
    assert strata==Counter({key:340 for key in subject.STRATA})
    assert torch.equal(rng,torch.get_rng_state()) and random.getstate()==python_rng
    with pytest.raises(AttributeError):cache._max_steps=900
    report=cache.receipt;report['bank_kind']='mutated';assert cache.receipt['bank_kind']==kind
    for step in (True,-1,340,1.5):
        with pytest.raises(ValueError):subject.select_indices(cache,step)


@pytest.mark.parametrize('dimension',[8,384,768])
@pytest.mark.parametrize('model_kind',['factorized','recurrent'])
def test_cache_uses_exact_frozen_transform_without_head_or_recurrent_pass(monkeypatch,dimension,model_kind):
    prepared,data=bank(dimension=dimension);model,codec=model_for(monkeypatch,dimension,kind=model_kind)
    for name in ('project','start','next_logits','count_logits','source_value_logits'):
        monkeypatch.setattr(model,name,lambda *a,**k:pytest.fail('model executed during preparation'))
    before=core.tensor_digest(model);rng=torch.get_rng_state().clone()
    cache=subject.prepare_tensor_cache(torch,model,prepared,codec=codec,input_transform=transform(dimension),seed=1729,deadline=deadline())
    expected=(torch.tensor([r['input'] for r in prepared['rows']],dtype=torch.float32)-.02)/1.3
    assert torch.equal(cache._data,expected) and torch.equal(cache._vectors[:,0],expected)
    assert cache._mask[:,0].all() and not cache._mask[:,1:].any() and not cache._vectors[:,1:].any()
    assert cache.receipt['estimated_training_work_bytes']>=cache.receipt['cached_tensor_bytes']
    assert core.tensor_digest(model)==before and torch.equal(rng,torch.get_rng_state())


def test_loss_full32v_ce_exact_source_only_one_pass_no_rehash_and_no_mutation(monkeypatch):
    model,cache,prepared,data=cache_for(monkeypatch,fitted=True)
    before=core.tensor_digest(model);rng=torch.get_rng_state().clone();modes={n:m.training for n,m in model.named_modules()}
    for parameter in model.parameters():
        if parameter.requires_grad:parameter.grad=torch.ones_like(parameter)
    gradients={n:None if p.grad is None else p.grad.clone() for n,p in model.named_parameters()}
    calls=[];original=model.source_value_logits
    def source(*a,**kw):
        assert set(kw)=={'source_context'} and set(kw['source_context'])=={'vectors','mask'}
        calls.append(True);return original(*a,**kw)
    monkeypatch.setattr(model,'source_value_logits',source)
    for name in ('start','next_logits','count_logits'):
        monkeypatch.setattr(model,name,lambda *a,**kw:pytest.fail('non-source model path executed'))
    monkeypatch.setattr(subject,'digest',lambda *a:pytest.fail('step rehashed bank'))
    actual=subject.modality_loss(torch,model,cache,committed_step=0,deadline=deadline())
    receipt=actual['receipt'];expected=torch.nn.functional.cross_entropy(torch.tensor(receipt['full_vocabulary_logits']),torch.tensor(receipt['target_token_ids']))
    assert actual['loss'].item()==pytest.approx(expected.item()) and len(calls)==1
    only_modal=torch.tensor(receipt['full_vocabulary_logits'])[:,[4,5,3]]
    assert not torch.isclose(expected,torch.nn.functional.cross_entropy(only_modal,torch.tensor([0,0,1,1,2,2])))
    assert receipt['row_ids']==[cache._rows[i][0] for i in subject.select_indices(cache,0)]
    assert core.tensor_digest(model)==before and torch.equal(rng,torch.get_rng_state()) and modes=={n:m.training for n,m in model.named_modules()}
    assert all(torch.equal(p.grad,gradients[n]) if gradients[n] is not None else p.grad is None for n,p in model.named_parameters())


def test_auxiliary_gradients_reach_modality_shared_projection_not_recurrent_or_other_readout_rows(monkeypatch):
    model,cache,_,_=cache_for(monkeypatch,fitted=True)
    result=subject.modality_loss(torch,model,cache,committed_step=0,deadline=deadline());result['loss'].backward()
    head=model.non_action_head
    assert head.source_projection.weight.grad.abs().sum()>0
    assert head.field_readout.weight.grad[32:64].abs().sum()>0
    assert not head.field_readout.weight.grad[:32].any() and not head.field_readout.weight.grad[64:].any()
    assert all(p.grad is None or not p.grad.any() for n,p in model.named_parameters() if not n.startswith('non_action_head.'))


def test_zero_initialized_readout_has_zero_first_source_projection_gradient(monkeypatch):
    model,cache,_,_=cache_for(monkeypatch)
    result=subject.modality_loss(torch,model,cache,committed_step=0,deadline=deadline());result['loss'].backward()
    assert model.non_action_head.source_projection.weight.grad is not None
    assert not model.non_action_head.source_projection.weight.grad.any()
    assert model.non_action_head.field_readout.weight.grad.any()


@pytest.mark.parametrize('kind',['cache','normalizer','different_model'])
def test_stale_cache_and_frozen_model_changes_are_rejected(monkeypatch,kind):
    model,cache,_,_=cache_for(monkeypatch)
    if kind=='cache':cache._vectors.add_(1.)
    elif kind=='normalizer':model.clause_source_mean.add_(1.)
    else:model=deepcopy(model)
    with pytest.raises(ValueError):subject.modality_loss(torch,model,cache,committed_step=0,deadline=deadline())


def test_deadlines_before_after_preparation_and_loss_do_not_advance_or_update(monkeypatch):
    data=corpus()
    with pytest.raises(TimeoutError):subject.prepare_bank(**data,bank_kind='used113',input_sha256=hashes(data),validate_rule=validator,deadline=0.)
    model,cache,prepared,_=cache_for(monkeypatch)
    before=core.tensor_digest(model);chosen=subject.select_indices(cache,0)
    with pytest.raises(TimeoutError):subject.modality_loss(torch,model,cache,committed_step=0,deadline=0.)
    original=model.source_value_logits
    def exhausted(*a,**k):
        result=original(*a,**k);monkeypatch.setattr(subject.time,'monotonic',lambda:100.);return result
    monkeypatch.setattr(model,'source_value_logits',exhausted);monkeypatch.setattr(subject.time,'monotonic',lambda:0.)
    with pytest.raises(TimeoutError):subject.modality_loss(torch,model,cache,committed_step=0,deadline=50.)
    assert subject.select_indices(cache,0)==chosen and core.tensor_digest(model)==before
    assert all(p.grad is None for p in model.parameters())


@pytest.mark.parametrize('steps',[True,0,-1,1.5,100001])
def test_memory_estimator_rejects_invalid_step_budget_without_tensor_allocation(steps):
    prepared,_=bank()
    with pytest.raises(ValueError):subject.estimate_training_work_bytes(prepared,max_optimizer_steps=steps)


def bound_fit(data):
    sources=data['source_rows'];cache=[{k:r[k] for k in ('id','source_text','input')} for r in sources]
    lookup={r['source_text']:r['input'] for r in sources}
    train=[dict(r,input=lookup[r['source_text'].split('\n\n')[0]],target=object())
           for r in data['paragraph_training_rows']]
    validation=deepcopy(data['forbidden_rows_by_split']['validation'])
    validation[0]['target']=object()
    source_contexts=dict(train=subject.contexts.build_source_contexts(data['paragraph_training_rows'],cache),
        validation=subject.contexts.build_source_contexts(
            [{k:r[k] for k in ('id','source_text')} for r in validation],
            [{k:r[k] for k in ('id','source_text','input')} for r in validation]))
    return train,validation,source_contexts


@pytest.mark.parametrize('kind',['used113','full180'])
def test_bank_binding_uses_actual_training_vectors_excludes_actual_validation_without_labels(kind):
    prepared,data=bank(kind);train,validation,source_contexts=bound_fit(data)
    actual=subject.validate_training_binding(prepared,train,validation,source_contexts=source_contexts,
        codec=data['codec'],deadline=deadline())
    assert actual['actual_training_unique_clauses']==113
    assert actual['externally_declared_extra_training_sources']==(67 if kind=='full180' else 0)
    assert actual['training_paragraph_sources_sha256']==prepared['input_sha256']['paragraph_training_rows']
    assert actual['validation_labels_accessed'] is False and actual['training_reference_labels_accessed'] is False


@pytest.mark.parametrize('kind',['other_paragraphs','missing_used_source','vector_mismatch','validation_text','validation_vector','validation_id','codec','dimension'])
def test_actual_fit_binding_rejects_stale_bank_missing_sources_and_validation_leaks(kind):
    prepared,data=bank('full180');train,validation,source_contexts=bound_fit(data)
    used={s['source_sha256'] for c in source_contexts['train'].values() for s in c['segments']}
    unused=next(row for row in prepared['rows'] if row['source_sha256'] not in used)
    if kind=='other_paragraphs':prepared['input_sha256']['paragraph_training_rows']='0'*64
    elif kind=='missing_used_source':
        prepared['rows']=prepared['rows'][::-1]
        index=next(i for i,r in enumerate(prepared['rows']) if r['source_sha256'] in used)
        prepared['rows'][index]=deepcopy(unused)
    elif kind=='vector_mismatch':
        first=source_contexts['train'][train[0]['id']]['segments'][0]
        replacement=[0.,0.,0.,1.,0.,0.,0.,0.]
        for row in train:
            descriptor=source_contexts['train'][row['id']]
            vectors=[replacement if s['source_sha256']==first['source_sha256'] else s['vector'] for s in descriptor['segments']]
            source_contexts['train'][row['id']]=subject.contexts._descriptor(row['source_text'],vectors)
    elif kind.startswith('validation_'):
        if kind=='validation_text':validation[0]['source_text']=unused['source_text']
        elif kind=='validation_vector':validation[0]['input']=unused['input']
        else:validation[0]['id']=unused['id']
        source_contexts['validation']=subject.contexts.build_source_contexts(
            [{k:r[k] for k in ('id','source_text')} for r in validation],
            [{k:r[k] for k in ('id','source_text','input')} for r in validation])
    elif kind=='codec':prepared['codec_sha256']='0'*64
    else:train[0]['input']=train[0]['input']+[0.]*376
    prepared['bank_sha256']=subject.digest({k:v for k,v in prepared.items() if k!='bank_sha256'})
    with pytest.raises(ValueError):subject.validate_training_binding(prepared,train,validation,
        source_contexts=source_contexts,codec=data['codec'],deadline=deadline())


def test_real_auxiliary_update_changes_head_without_invalidating_frozen_cache(monkeypatch):
    model,cache,_,_=cache_for(monkeypatch,fitted=True)
    before={n:p.detach().clone() for n,p in model.named_parameters()}
    optimizer=torch.optim.AdamW([p for p in model.parameters() if p.requires_grad],lr=.001,foreach=False)
    result=subject.modality_loss(torch,model,cache,committed_step=0,deadline=deadline())
    (.05*result['loss']).backward();optimizer.step();optimizer.zero_grad(set_to_none=True)
    assert not torch.equal(before['non_action_head.field_readout.weight'],model.non_action_head.field_readout.weight)
    recurrent=[n for n in before if n.endswith('.decoder.weight_ih_l0')]
    assert recurrent and all(torch.equal(before[n],dict(model.named_parameters())[n]) for n in recurrent)
    next_result=subject.modality_loss(torch,model,cache,committed_step=1,deadline=deadline())
    assert next_result['receipt']['committed_step']==1 and next_result['loss'].requires_grad
