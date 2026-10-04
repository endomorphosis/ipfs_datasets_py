"""Matched placement draws, inherited objective, warm/resume and integrity checks."""
from copy import deepcopy
import hashlib
import os
os.environ['CUDA_VISIBLE_DEVICES']='-1'
import pytest
import torch
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_temporal_stability as own


def query(text,index=0):
    needle='within 10 days';starts=[i for i in range(len(text)) if text.startswith(needle,i)];a=starts[index]
    return {'id':hashlib.sha256((text+':'+str(a)).encode()).hexdigest(),'source_text':text,
            'source_sha256':hashlib.sha256(text.encode()).hexdigest(),'proposed_time_span':{'char_start':a,'char_end':a+len(needle)}}


def singles(prefix,count):
    return [{**query(f'{prefix}{g} {label} Registry shall file within 10 days.'),'label':label,'group_id':f'{prefix}-{g}'}
            for g in range(count) for label in own.CLASSES]


def multiples(prefix,count=2):
    rows=[];units=[]
    patterns=[(0,0),(1,1),(2,2),(3,3,0),(3,1,2)]
    for unit in range(count):
        ids=[]
        for group,labels in enumerate(patterns):
            text='; '.join(f'{prefix}{unit}_{group}_{i} Registry files within 10 days' for i in range(len(labels)))+'.'
            for i,label in enumerate(labels):
                row={**query(text,i),'label':own.CLASSES[label],'group_id':f'{prefix}-{unit}-{group}'}
                ids.append(row['id']);rows.append(row)
        units.append({'unit_id':f'{prefix}-{unit}','query_ids':ids})
    return rows,units


@pytest.fixture
def setup(monkeypatch):
    earlier=own.previous.previous
    monkeypatch.setattr(earlier.parent_runtime,'validate_checkpoint',lambda _:None)
    cfg={'seed':1730,'hidden_size':32,'embedding_dim':16,'latent_dimension':0,'trigger_enabled':True}
    model=earlier.mixed._model(torch,cfg)
    source={'model_config':cfg,'model_state':{k:v.detach().tolist() for k,v in model.state_dict().items()}}
    train=singles('old',8);tune=singles('oldtune',2)
    parent=earlier.build_checkpoint(source,train,tune,arm='finetune_occurrence',seed=1730,parent_file_sha256='1'*64)
    parent,_=earlier.train(parent,train,tune,additional_steps=1)
    parent['optimizer_steps']=200
    for v in parent['optimizer_state']['parameters'].values():v['step']=200
    paired,units=multiples('paired');paired_tune,_=multiples('pairtune',1)
    warm=own.previous.build_checkpoint(parent,train,paired,units,tune,paired_tune,arm='mixed_occurrences',seed=1730,parent_file_sha256='2'*64)
    warm,_=own.previous.train(warm,train,paired,units,tune,paired_tune,additional_steps=1)
    warm['optimizer_steps']=200;warm['cumulative_owner_head_updates']=400
    for v in warm['optimizer_state']['parameters'].values():v['step']=200
    own.previous._restore(warm)
    new,newunits=multiples('placement');newtune,_=multiples('placementtune',1)
    return warm,(train,paired,units,new,newunits,tune,paired_tune,newtune)


@pytest.fixture
def cache(setup):
    return own.build_teacher_cache(setup[0],setup[1][0],setup[1][1],seed=1730,parent_file_sha256='3'*64)


def cp(setup,cache,arm='placement_kl'):
    return own.build_checkpoint(setup[0],*setup[1],arm=arm,seed=1730,parent_file_sha256='3'*64,
        teacher_cache=cache,teacher_cache_ref={'path':'/test/cache.json','sha256':'4'*64,'bytes':1234})


def test_initials_equal_exact_warm_model_and_clear_optimizer(setup,cache):
    models=[cp(setup,cache,arm) for arm in own.ARMS]
    assert all(m['model_state']==setup[0]['model_state'] and m['optimizer_state']['parameters']=={} for m in models)
    assert models[0]['teacher_cache']['payload_sha256']==own.digest(cache)


def test_initial_predictions_reuse_original_wire(setup,cache):
    rows=own.source_queries(setup[1][3][:4])
    for arm in own.ARMS:
        assert own.TemporalStabilityHead(cp(setup,cache,arm)).predict_many(rows)==own.previous.PairedTemporalOwnershipHead(setup[0]).predict_many(rows)


def test_all_arms_use_exact_frozen_placement_schedule(setup):
    d=own._splits(*setup[1])
    for step in range(200):
        expected=own.baseline.batch_indices(d['single_groups'],d['prior_paired_units'],d['placement_units'],1730,step,'placement')
        for arm in own.ARMS:
            actual=own.batch_indices(d['single_groups'],d['prior_paired_units'],d['placement_units'],1730,step,arm)
            assert actual==expected


@pytest.mark.parametrize('arm',own.ARMS)
def test_split_resume_exact_tensors_moments_and_trace(setup,cache,arm):
    initial=cp(setup,cache,arm)
    one,r1=own.train(initial,*setup[1],teacher_cache=cache,additional_steps=1)
    resumed,r2=own.train(one,*setup[1],teacher_cache=cache,additional_steps=2)
    whole,r=own.train(initial,*setup[1],teacher_cache=cache,additional_steps=3)
    assert resumed['model_state']==whole['model_state'] and resumed['optimizer_state']==whole['optimizer_state']
    assert r1['trace']+r2['trace']==r['trace']
    assert sum(r['trainable_parameters'].values())==(8356 if arm=='placement_head_only' else 21028)
    assert r['teacher_encoder_batch_forwards']==0 and r['teacher_cache_batch_uses']==3
    for name,value in initial['model_state'].items():
        if not name.startswith('head.') and (arm=='placement_head_only' or not name.startswith('source.encoder.')):
            assert whole['model_state'][name]==value


def test_ce_trajectory_identical_to_old_placement_training(setup,cache):
    old=own.baseline.build_checkpoint(setup[0],*setup[1],arm='placement',seed=1730,parent_file_sha256='3'*64)
    old,_=own.baseline.train(old,*setup[1],additional_steps=3)
    new,_=own.train(cp(setup,cache,'placement_ce'),*setup[1],teacher_cache=cache,additional_steps=3)
    assert new['model_state']==old['model_state'] and new['optimizer_state']==old['optimizer_state']


def test_independent_kl_values_gradients_teacher_detachment_and_masks():
    generator=torch.Generator().manual_seed(731)
    for count in (0,1,12,24):
        student=(torch.randn(24,4,generator=generator,dtype=torch.float64)*20).requires_grad_()
        teacher=(torch.randn(24,4,generator=generator,dtype=torch.float64)*20).requires_grad_()
        labels=torch.tensor(list(range(4))*6);mask=torch.arange(24)<count
        logp=teacher.detach()/2-torch.logsumexp(teacher.detach()/2,1,keepdim=True)
        logq=student/2-torch.logsumexp(student/2,1,keepdim=True)
        terms=(logp.exp()*(logp-logq)).sum(1)
        kl=terms[mask].sum()/count if count else student.sum()*0
        ce=torch.nn.functional.cross_entropy(student,labels)
        for arm in own.ARMS:
            loss,parts=own.objective(torch,student,labels,teacher,mask,arm)
            expected=ce+4*kl if arm=='placement_kl' else ce
            assert torch.allclose(loss,expected,atol=1e-12,rtol=1e-12)
            actual_grad=torch.autograd.grad(loss,student,retain_graph=True)[0]
            expected_grad=torch.autograd.grad(expected,student,retain_graph=True)[0]
            assert torch.allclose(actual_grad,expected_grad,atol=1e-12,rtol=1e-12)
            assert torch.autograd.grad(loss,teacher,allow_unused=True,retain_graph=True)[0] is None
            assert parts['teacher_eligible_count']==count
            assert parts['objective']==('standard_ce_plus_teacher_kl' if arm=='placement_kl' else 'standard_ce')
            if arm=='placement_kl':
                inherited_ce=(torch.logsumexp(student,dim=1)-student.gather(1,labels[:,None]).squeeze(1)).mean()
                aux=actual_grad-torch.autograd.grad(inherited_ce,student,retain_graph=True)[0]
                assert torch.equal(aux[~mask],torch.zeros_like(aux[~mask]))


def test_cache_frozen_teacher_exact_order_and_no_new_data(setup,cache):
    rows=setup[1][0]+setup[1][1]
    assert [r['id'] for r in cache['rows']]==[r['id'] for r in rows]
    assert not {r['id'] for r in cache['rows']}&{r['id'] for r in setup[1][3]}
    assert cache['teacher_state_before_sha256']==cache['teacher_state_after_sha256']==own.digest(setup[0]['model_state'])
    assert cache['teacher_gradients_absent'] is True and cache['teacher_requires_grad'] is False
    assert cache['encoder_batch_forwards']==2 and cache['encoder_source_evaluations']==56


def test_new_rows_are_explicitly_zero_teacher_and_never_eligible(setup,cache):
    _,report=own.train(cp(setup,cache),*setup[1],teacher_cache=cache,additional_steps=2)
    row=report['trace'][1]
    assert row['teacher_cached_mask']==[True]*12+[False]*12
    assert row['teacher_eligible_mask'][12:]==[False]*12
    assert row['teacher_logits'][12:]==[[0.0]*4]*12
    assert row['objective_components']['teacher_eligible_count']==sum(row['teacher_eligible_mask'])


@pytest.mark.parametrize('mutation',['order','wrong_label','correctness','parent','float_alias','new_row','mask_authority'])
def test_cache_mutations_rejected(setup,cache,mutation):
    x=deepcopy(cache)
    if mutation=='order':x['rows'][0],x['rows'][1]=x['rows'][1],x['rows'][0]
    if mutation=='wrong_label':x['rows'][0]['label']='unknown'
    if mutation=='correctness':x['rows'][0]['correct']=not x['rows'][0]['correct']
    if mutation=='parent':x['parent_file_sha256']='0'*64
    if mutation=='float_alias':x['rows'][0]['logits'][0]+=1e-15
    if mutation=='new_row':x['rows'][0]['id']=setup[1][3][0]['id']
    if mutation=='mask_authority':x['new_placement_rows_included']=True
    with pytest.raises(ValueError):own.validate_teacher_cache(x,setup[0],setup[1][0],setup[1][1],seed=1730,parent_file_sha256='3'*64)


@pytest.mark.parametrize('mutation',['parent','producer','numeric_alias','bool_alias','frozen_tensor','nonfinite','initial','count','cumulative','authority','predecessor'])
def test_repaired_checkpoint_mutations_fail(setup,cache,mutation):
    x=cp(setup,cache)
    if mutation=='parent':x['parent_payload_sha256']='0'*64
    if mutation=='producer':x['implementation']={}
    if mutation=='numeric_alias':x['config']['max_steps']=200.0
    if mutation=='bool_alias':x['config']['head_learning_rate']=True
    if mutation=='frozen_tensor':x['model_state']['source.byte_embedding.weight'][1][0]+=1
    if mutation=='nonfinite':x['model_state']['head.0.weight'][0][0]=float('nan')
    if mutation=='initial':x['initial_state_sha256']='0'*64
    if mutation=='count':x['manifests']['sampling_units']['count']+=1
    if mutation=='cumulative':x['cumulative_owner_head_updates']=401
    if mutation=='authority':x['owner_occurrence_resolved']=True
    if mutation=='predecessor':x['preceding_checkpoint_sha256']='0'*64
    with pytest.raises(ValueError):own._restore(x)


def test_changed_training_rows_cannot_resume(setup,cache):
    args=list(deepcopy(setup[1]));args[3][0]['label']='ambiguous'
    with pytest.raises(ValueError):own.train(cp(setup,cache),*args,teacher_cache=cache,additional_steps=1)


@pytest.mark.parametrize('step',[-1,200,True,1.0])
def test_sampler_rejects_invalid_step(setup,step):
    d=own._splits(*setup[1])
    with pytest.raises(ValueError):own.batch_indices(d['single_groups'],d['prior_paired_units'],d['placement_units'],1730,step,'placement_ce')


def test_split_source_overlap_is_rejected(setup):
    args=list(deepcopy(setup[1]));args[-1]=args[3]
    with pytest.raises(ValueError):own._splits(*args)
