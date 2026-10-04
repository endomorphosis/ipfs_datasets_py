"""Matched placement draws, inherited objective, warm/resume and integrity checks."""
from copy import deepcopy
import hashlib
import os
os.environ['CUDA_VISIBLE_DEVICES']='-1'
import pytest
import torch
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_temporal_placement as own


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


def cp(setup,arm='placement'):
    return own.build_checkpoint(setup[0],*setup[1],arm=arm,seed=1730,parent_file_sha256='3'*64)


def test_initials_equal_exact_warm_model_and_clear_optimizer(setup):
    a,b=cp(setup,'continuation'),cp(setup)
    assert a['model_state']==b['model_state']==setup[0]['model_state']
    assert a['optimizer_state']['parameters']==b['optimizer_state']['parameters']=={}
    assert a['parent_owner_head_updates']==400 and a['cumulative_owner_head_updates']==400
    assert setup[0]['optimizer_state']['parameters']


def test_initial_predictions_reuse_original_wire(setup):
    rows=own.source_queries(setup[1][3][:4])
    actual=own.TemporalPlacementHead(cp(setup)).predict_many(rows)
    assert actual==own.previous.PairedTemporalOwnershipHead(setup[0]).predict_many(rows)


def test_balanced_schedule_exact_common_even_steps_and_single_prefix(setup):
    d=own._splits(*setup[1]);counts={'old':0,'new':0}
    for step in range(200):
        a=own.batch_indices(d['single_groups'],d['prior_paired_units'],d['placement_units'],1730,step,'continuation')
        b=own.batch_indices(d['single_groups'],d['prior_paired_units'],d['placement_units'],1730,step,'placement')
        assert a['single_indices']==b['single_indices'] and len(a['single_indices'])==12
        assert len(a['prior_paired_indices'])==12 and not a['placement_indices']
        if step%2==0:assert a==b;counts['old']+=1
        else:assert len(b['placement_indices'])==12 and not b['prior_paired_indices'];counts['new']+=1
        batch=[d['single_training'][i] for i in b['single_indices']]+[d['prior_paired_training'][i] for i in b['prior_paired_indices']]+[d['placement_training'][i] for i in b['placement_indices']]
        assert [sum(r['label']==c for r in batch) for c in range(4)]==[6]*4
    assert counts=={'old':100,'new':100}


def test_natural_single_draws_exhaust_each_epoch_without_skipped_prefix(setup):
    d=own._splits(*setup[1]);names=[]
    for step in range(3):names.extend(own.batch_indices(d['single_groups'],d['prior_paired_units'],d['placement_units'],1730,step,'placement')['single_group_ids'])
    assert len(set(names[:8]))==8


def test_objective_value_and_gradients_equal_unweighted_ce_for_both_arms():
    torch.manual_seed(7)
    for arm in own.ARMS:
        logits=(torch.randn(24,4,dtype=torch.float64)*30).requires_grad_();labels=torch.tensor(list(range(4))*6)
        actual,parts=own.objective(torch,logits,labels,arm)
        expected=torch.nn.functional.cross_entropy(logits,labels)
        assert torch.allclose(actual,expected,atol=1e-12,rtol=1e-12)
        assert torch.allclose(torch.autograd.grad(actual,logits,retain_graph=True)[0],torch.autograd.grad(expected,logits)[0],atol=1e-12,rtol=1e-12)
        assert parts['applied_class_weights']==[1.]*4 and parts['class_counts']==[6]*4


def test_split_resume_exact_tensors_moments_and_trace(setup):
    initial=cp(setup)
    one,r1=own.train(initial,*setup[1],additional_steps=1)
    resumed,r2=own.train(one,*setup[1],additional_steps=2)
    whole,r=own.train(initial,*setup[1],additional_steps=3)
    assert resumed['model_state']==whole['model_state'] and resumed['optimizer_state']==whole['optimizer_state']
    assert r1['trace']+r2['trace']==r['trace']
    assert whole['cumulative_owner_head_updates']==403
    assert sum(r['trainable_parameters'].values())==21028
    for name,value in initial['model_state'].items():
        if not name.startswith(('head.','source.encoder.')):assert whole['model_state'][name]==value


def test_same_first_update_has_identical_state_across_arms(setup):
    left,_=own.train(cp(setup,'continuation'),*setup[1],additional_steps=1)
    right,_=own.train(cp(setup),*setup[1],additional_steps=1)
    assert left['model_state']==right['model_state'] and left['optimizer_state']==right['optimizer_state']


@pytest.mark.parametrize('mutation',['parent','producer','numeric_alias','bool_alias','frozen_tensor','nonfinite','initial','count','cumulative','authority','predecessor'])
def test_repaired_checkpoint_mutations_fail(setup,mutation):
    x=cp(setup)
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


def test_changed_training_rows_cannot_resume(setup):
    args=list(deepcopy(setup[1]));args[3][0]['label']='ambiguous'
    with pytest.raises(ValueError):own.train(cp(setup),*args,additional_steps=1)


@pytest.mark.parametrize('step',[-1,200,True,1.0])
def test_sampler_rejects_invalid_step(setup,step):
    d=own._splits(*setup[1])
    with pytest.raises(ValueError):own.batch_indices(d['single_groups'],d['prior_paired_units'],d['placement_units'],1730,step,'placement')


def test_split_source_overlap_is_rejected(setup):
    args=list(deepcopy(setup[1]));args[-1]=args[3]
    with pytest.raises(ValueError):own._splits(*args)
