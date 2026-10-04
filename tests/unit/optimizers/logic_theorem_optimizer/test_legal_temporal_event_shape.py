"""Fictional-only shape supervision tests; no experiment corpus is read.

Toy carrier tests explicitly patch both authentication constants and the
delegated carrier restore. The final smoke separately authenticates real source
weights and uses only fictional source/target fixtures.
"""
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_temporal_event_shape as m


def query(text, phrase, identity='q'):
    start=text.index(phrase)
    return {'id':identity,'source_text':text,'source_sha256':hashlib.sha256(text.encode()).hexdigest(),
            'proposed_time_span':{'char_start':start,'char_end':start+len(phrase)}}


def rows(prefix, count=16, mixed=False, masked=False):
    result=[]
    for i in range(count):
        text=f'{prefix}{i} shall file after issuance; Office{i} shall wait until notice; Clerk{i} shall act after the beacon rings.'
        phrases=('after issuance','until notice','after the beacon rings') if mixed else ('after issuance',)
        for j,phrase in enumerate(phrases):
            result.append({**query(text,phrase,f'{prefix}-{i}-{j}'),'label':m.CLASSES[j%2 if mixed else i%2],
                           'shape_label':None if masked else m.SHAPE_CLASSES[(i+j)%4], 'group_id':f'{prefix}-siblings-{i//2}'})
    return result


@pytest.fixture
def toy(monkeypatch):
    torch=m._torch()
    config={'embedding_dim':16,'hidden_size':32,'latent_dimension':0,'projection_width':16,
            'residual_scale':.1,'seed':914,'latent_enabled':False}
    parent={'schema':m.carrier.SCHEMA,'config':{'arm':'relative_position','seed':1730},'optimizer_steps':200,
            'model_config':config,'fictional_test_carrier':True}
    calls=[]
    def restore(value):
        assert value==parent;calls.append(value)
        return torch,SimpleNamespace(source=m.span._model(torch,config)),None
    monkeypatch.setattr(m.carrier,'_restore',restore)
    monkeypatch.setattr(m,'PARENT_FILE_SHA256','a'*64)
    monkeypatch.setattr(m,'PARENT_PAYLOAD_SHA256',m.digest(parent))
    return parent,calls


def checkpoint(toy,arm='auxiliary_shape',seed=1730,masked=False):
    return m.build_checkpoint(toy[0],rows('Train',masked=masked),rows('Tune',4,masked=masked),
                              arm=arm,seed=seed,parent_file_sha256='a'*64)


def test_shape_source_class_weighting_has_independent_numerical_gradient_oracle():
    torch=m._torch();ps=[.8,.4,.2,.9,.7,.3]
    labels=[0,0,0,0,2,None];sources=['A','A','A','B','C','D']
    values=[]
    for p,label in zip(ps,labels):
        vector=[math.log((1-p)/3)]*4;vector[label if label is not None else 1]=math.log(p);values.append(vector)
    logits=torch.tensor(values,dtype=torch.float64,requires_grad=True)
    records=[{'shape_label':label,'query':{'source_sha256':source}} for label,source in zip(labels,sources)]
    loss,parts=m.shape_objective(torch,logits,records)
    expected=.5*((sum(-math.log(p) for p in ps[:3])/3-math.log(.9))/2-math.log(.7))
    assert float(loss.detach())==pytest.approx(expected,abs=1e-12)
    assert parts['present_classes']==[0,2] and parts['class_source_counts']==[2,0,1,0]
    assert parts['class_candidate_counts']==[4,0,1,0] and parts['masked_candidate_count']==1
    assert parts['class_mean_source_nll'][1] is None
    loss.backward();assert logits.grad[:-1].abs().sum()>0
    assert bool((logits.grad[-1]==0).all())


def test_repeated_candidate_does_not_reweight_source_or_shape_class():
    torch=m._torch();logits=torch.tensor([[2.,0.,0.,0.],[0.,1.,0.,0.]])
    records=[{'shape_label':0,'query':{'source_sha256':'A'}},{'shape_label':1,'query':{'source_sha256':'B'}}]
    first,_=m.shape_objective(torch,logits,records)
    repeated,_=m.shape_objective(torch,torch.cat([logits[:1].repeat(3,1),logits[1:]]),[records[0]]*3+[records[1]])
    assert float(first.detach())==float(repeated.detach())


def test_all_masked_shape_loss_is_connected_exact_zero():
    torch=m._torch();logits=torch.randn(2,4,requires_grad=True)
    loss,parts=m.shape_objective(torch,logits,[{'shape_label':None,'query':{'source_sha256':str(i)}} for i in range(2)])
    assert float(loss.detach())==0 and parts['present_classes']==[] and parts['candidate_count']==0
    loss.backward();assert logits.grad is not None and bool((logits.grad==0).all())


@pytest.mark.parametrize('arm',m.ARMS)
def test_combined_loss_and_gradient_respect_arm(arm):
    torch=m._torch()
    binary=torch.tensor([[1.,0.],[0.,1.]],requires_grad=True)
    shape=torch.tensor([[2.,0.,0.,0.],[0.,2.,0.,0.]],requires_grad=True)
    records=[{'label':i,'shape_label':i,'query':{'source_sha256':str(i)}} for i in range(2)]
    total,parts=m.objective(torch,binary,shape,records,arm=arm)
    expected=math.log1p(math.exp(-1))+(0.5 if arm=='auxiliary_shape' else 0)*math.log1p(3*math.exp(-2))
    assert float(total.detach())==pytest.approx(expected,abs=1e-7)
    assert parts['shape_weight']==(.5 if arm=='auxiliary_shape' else 0.)
    total.backward();assert binary.grad.abs().sum()>0
    if arm=='auxiliary_shape':assert shape.grad.abs().sum()>0
    else:assert shape.grad is None


@pytest.mark.parametrize('seed',[1730,1731])
def test_same_initial_tensors_and_original_binary_initialization_across_arms(toy,seed):
    a=checkpoint(toy,'binary_control',seed);b=checkpoint(toy,'auxiliary_shape',seed)
    assert a['model_state']==b['model_state'] and a['initial_state_sha256']==b['initial_state_sha256']
    original=m.base._model(m._torch(),toy[0],m.base._config('finetuned_gru_eligibility',seed))
    assert {k:v for k,v in a['model_state'].items() if not k.startswith('shape_head.')}=={k:v.tolist() for k,v in original.state_dict().items()}
    assert a['optimizer_state']['parameters']==b['optimizer_state']['parameters']=={}


@pytest.mark.parametrize('mixed',[False,True])
def test_sampler_matches_original_and_extends_to_step399(mixed):
    records=m._records(rows('Sample',20,mixed=mixed));groups=m._source_groups(records)
    for seed in (1730,1731):
        for step in (0,50,199):assert m.batch_indices(records,seed,step)==m.base.batch_indices(records,seed,step)
        indices,sources=m.batch_indices(records,seed,399)
        assert len(sources)==len(set(sources))==16 and len(indices)==(48 if mixed else 16)
        assert all(set(groups[source])<=set(indices) for source in sources)
        assert {records[i]['label'] for i in indices}=={0,1}
        assert (indices,sources)==m.batch_indices(records,seed,399)
    with pytest.raises(ValueError):m.batch_indices(records,1730,400)


@pytest.mark.parametrize('arm',m.ARMS)
def test_real_gradients_update_only_declared_tensors_and_report_logits(toy,arm):
    cp=checkpoint(toy,arm);trained,report=m.train(cp,rows('Train'),rows('Tune',4),additional_steps=1)
    changed={k for k in cp['model_state'] if cp['model_state'][k]!=trained['model_state'][k]}
    assert any(k.startswith('head.') for k in changed) and any(k.startswith('source.encoder.') for k in changed)
    assert all(k.startswith(('head.','source.encoder.','shape_head.')) for k in changed)
    assert any(k.startswith('shape_head.') for k in changed)==(arm=='auxiliary_shape')
    step=report['trace'][0]
    assert len(step['logits'])==len(step['shape_logits'])==len(step['shape_mask'])==16
    assert len(step['complete_source_order'])==16 and step['shape_mask']==[True]*16
    assert step['shape_loss']>0 and step['binary_loss']>0 and step['preclip_gradient_norm']>0
    assert step['loss']==pytest.approx(step['binary_loss']+step['shape_weight']*step['shape_loss'],abs=1e-6)
    assert report['encoder_batch_forwards']==1 and report['encoder_source_evaluations']==16
    assert all(moment['step']==1 for moment in trained['optimizer_state']['parameters'].values())
    assert all((not k.startswith('shape_head.') or arm=='auxiliary_shape') for k in report['trainable_parameters'])


@pytest.mark.parametrize('arm',m.ARMS)
def test_chunked_resume_matches_uninterrupted_tensors_moments_and_trace(toy,arm):
    cp=checkpoint(toy,arm)
    whole,full=m.train(cp,rows('Train'),rows('Tune',4),additional_steps=4)
    first,a=m.train(cp,rows('Train'),rows('Tune',4),additional_steps=2)
    resumed,b=m.train(first,rows('Train'),rows('Tune',4),additional_steps=2)
    assert whole['model_state']==resumed['model_state'] and whole['optimizer_state']==resumed['optimizer_state']
    assert full['trace']==a['trace']+b['trace']
    assert resumed['preceding_checkpoint_sha256']==m.digest(first)


def test_binary_control_ignores_shape_targets_for_training(toy):
    training=rows('Train');tuning=rows('Tune',4)
    changed=deepcopy(training)
    for i,row in enumerate(changed):row['shape_label']=None if i%2 else m.SHAPE_CLASSES[(i+1)%4]
    a=m.build_checkpoint(toy[0],training,tuning,arm='binary_control',seed=1730,parent_file_sha256='a'*64)
    b=m.build_checkpoint(toy[0],changed,tuning,arm='binary_control',seed=1730,parent_file_sha256='a'*64)
    a,ar=m.train(a,training,tuning,additional_steps=2);b,br=m.train(b,changed,tuning,additional_steps=2)
    assert a['model_state']==b['model_state'] and a['optimizer_state']==b['optimizer_state']
    assert [r['loss'] for r in ar['trace']]==[r['loss'] for r in br['trace']]


def test_binary_control_reproduces_original_finetuned_binary_updates(toy):
    training=rows('Train');tuning=rows('Tune',4)
    original_training=[{k:v for k,v in row.items() if k!='shape_label'} for row in training]
    original_tuning=[{k:v for k,v in row.items() if k!='shape_label'} for row in tuning]
    old=m.base.build_checkpoint(toy[0],original_training,original_tuning,
                                arm='finetuned_gru_eligibility',seed=1730,parent_file_sha256='a'*64)
    new=checkpoint(toy,'binary_control')
    old,old_report=m.base.train(old,original_training,original_tuning,additional_steps=2)
    new,new_report=m.train(new,training,tuning,additional_steps=2)
    assert old['model_state']=={k:v for k,v in new['model_state'].items() if not k.startswith('shape_head.')}
    assert old['optimizer_state']==new['optimizer_state']
    assert [r['loss'] for r in old_report['trace']]==[r['loss'] for r in new_report['trace']]


def test_masked_auxiliary_head_retains_values_and_zero_moments(toy):
    cp=checkpoint(toy,masked=True)
    trained,report=m.train(cp,rows('Train',masked=True),rows('Tune',4,masked=True),additional_steps=2)
    assert all(r['shape_loss']==0 and not any(r['shape_mask']) for r in report['trace'])
    for key in ('shape_head.weight','shape_head.bias'):
        assert trained['model_state'][key]==cp['model_state'][key]
        state=trained['optimizer_state']['parameters'][key]
        assert state['step']==2
        assert not m._torch().tensor(state['exp_avg']).count_nonzero()
        assert not m._torch().tensor(state['exp_avg_sq']).count_nonzero()


def test_auxiliary_shape_targets_change_shared_gradient_updates(toy):
    a=checkpoint(toy);training=rows('Train');other=deepcopy(training)
    for row in other:row['shape_label']=m.SHAPE_CLASSES[(m.SHAPE_CLASSES.index(row['shape_label'])+1)%4]
    b=m.build_checkpoint(toy[0],other,rows('Tune',4),arm='auxiliary_shape',seed=1730,parent_file_sha256='a'*64)
    a,_=m.train(a,training,rows('Tune',4),additional_steps=1);b,_=m.train(b,other,rows('Tune',4),additional_steps=1)
    assert a['model_state']['head.0.weight']!=b['model_state']['head.0.weight']
    assert a['model_state']['source.encoder.weight_ih_l0']!=b['model_state']['source.encoder.weight_ih_l0']


def test_joint_prediction_shares_forward_preserves_binary_wire_and_has_no_id_features(toy):
    cp=checkpoint(toy);model=m.TemporalEventShapeEligibility(cp)
    q=query('Élan shall file after receipt.','after receipt','one')
    joint=model.predict_joint([q]);assert model.encoder_batch_forwards==1 and model.encoder_source_evaluations==1
    assert joint['binary']==model.predict_many([q])
    shape=joint['shapes'][0];assert shape==model.predict_shapes([q])[0]
    assert shape['schema']==m.SHAPE_PREDICTION_SCHEMA and shape['class_order']==list(m.SHAPE_CLASSES)
    assert shape['diagnostic_only'] is True and shape['acceptance_input_allowed'] is False
    assert all(v is False for v in shape['authority'].values()) and shape['formula_admission'] is False
    assert shape['confidence']==max(shape['probabilities']) and sum(shape['probabilities'])==pytest.approx(1.,abs=1e-7)
    assert joint['binary'][0]['schema']==m.base.PREDICTION_SCHEMA
    renamed={**q,'id':'changed'};other=model.predict_joint([renamed])
    for key in ('binary','shapes'):assert joint[key][0]['logits']==other[key][0]['logits']


@pytest.mark.parametrize('feature',[{'label':'eligible_surface'},{'shape_label':'finite_clause'},
                                  {'reason_codes':['unsupported_event_shape']},{'latent':[0.]*8}])
def test_inference_rejects_targets_reasons_and_latents(toy,feature):
    model=m.TemporalEventShapeEligibility(checkpoint(toy))
    q={**query('Guild shall act after notice.','after notice'),**feature}
    with pytest.raises(ValueError):model.predict_joint([q])
    assert model.encoder_batch_forwards==0


@pytest.mark.parametrize('mutation',['missing_shape','invalid_shape','bool_shape','source_overlap','group_overlap','duplicate','extra','four_candidates'])
def test_closed_targets_and_split_controls(mutation):
    training=rows('Train',mixed=True);tuning=rows('Tune',4)
    if mutation=='missing_shape':training[0].pop('shape_label')
    elif mutation=='invalid_shape':training[0]['shape_label']='event'
    elif mutation=='bool_shape':training[0]['shape_label']=True
    elif mutation=='source_overlap':tuning[0]={**training[0],'id':'new','group_id':'new'}
    elif mutation=='group_overlap':tuning[0]['group_id']=training[0]['group_id']
    elif mutation=='duplicate':training.append(deepcopy(training[0]))
    elif mutation=='extra':training[0]['owner_assigned']=False
    else:training.append({**training[0],'id':'fourth','proposed_time_span':{'char_start':0,'char_end':len('Train0')}})
    with pytest.raises(ValueError):m._splits(training,tuning)


@pytest.mark.parametrize('mutation',['authority','producer','parent_file','parent_payload','config','extra','zero_shape','zero_head','source_embedding'])
def test_checkpoint_provenance_and_zero_step_tampering_fail_closed(toy,mutation):
    cp=checkpoint(toy)
    if mutation=='authority':cp['authority']['owner_assigned']=True
    elif mutation=='producer':cp['implementation']={}
    elif mutation=='parent_file':cp['parent_file_sha256']='b'*64
    elif mutation=='parent_payload':cp['parent']['fictional_test_carrier']=False
    elif mutation=='config':cp['config']['shape_loss_weight']=1.
    elif mutation=='extra':cp['shape_verified']=True
    elif mutation=='zero_shape':cp['model_state']['shape_head.bias'][0]+=.1
    elif mutation=='zero_head':cp['model_state']['head.0.bias'][0]+=.1
    else:cp['model_state']['source.byte_embedding.weight'][1][0]+=.1
    with pytest.raises(ValueError):m.validate_checkpoint(cp)


@pytest.mark.parametrize('mutation',['adam_step','negative_square','missing_moment','extra_moment','frozen_projection','frozen_control_shape'])
def test_trained_checkpoint_moment_and_frozen_tensor_contract(toy,mutation):
    cp,_=m.train(checkpoint(toy,'binary_control'),rows('Train'),rows('Tune',4),additional_steps=1)
    moments=cp['optimizer_state']['parameters']
    if mutation=='adam_step':moments['head.0.bias']['step']=2
    elif mutation=='negative_square':moments['head.0.bias']['exp_avg_sq'][0]=-.1
    elif mutation=='missing_moment':moments.pop('head.0.bias')
    elif mutation=='extra_moment':moments['shape_head.bias']=deepcopy(moments['head.0.bias'])
    elif mutation=='frozen_projection':cp['model_state']['source.token_projection.bias'][0]+=.1
    else:cp['model_state']['shape_head.bias'][0]+=.1
    with pytest.raises(ValueError):m.validate_checkpoint(cp)


def test_parent_authentication_and_training_manifest_bind_shape_targets(toy):
    with pytest.raises(ValueError):m.build_checkpoint(toy[0],rows('Train'),rows('Tune',4),arm='binary_control',seed=1730,parent_file_sha256='b'*64)
    cp=checkpoint(toy);changed=rows('Train');changed[0]['shape_label']=None
    with pytest.raises(ValueError):m.train(cp,changed,rows('Tune',4),additional_steps=1)
    with pytest.raises(ValueError):m.train(cp,rows('Train'),rows('Tune',4),additional_steps=401)


def test_exclusive_save_and_authenticated_load(toy,tmp_path):
    cp=checkpoint(toy);p=tmp_path/'shape.json';ref=m.save_checkpoint(cp,p)
    assert m.load_checkpoint(p,expected_sha256=ref['sha256'])==cp
    with pytest.raises(FileExistsError):m.save_checkpoint(cp,p)
    with pytest.raises(ValueError):m.load_checkpoint(p,expected_sha256='0'*64)


def test_authenticated_real_parent_two_arm_fictional_smoke():
    path=Path('/home/barberb/lift_coding/artifacts/legal-decoder-relative-owner-20261004/run-01/relative_position-1730/checkpoint-200.json')
    raw=path.read_bytes();assert hashlib.sha256(raw).hexdigest()==m.PARENT_FILE_SHA256
    parent=json.loads(raw);assert m.digest(parent)==m.PARENT_PAYLOAD_SHA256
    training=rows('SmokeTrain');tuning=rows('SmokeTune',2)
    initials={};evidence={}
    for arm in m.ARMS:
        cp=m.build_checkpoint(parent,training,tuning,arm=arm,seed=1730,parent_file_sha256=m.PARENT_FILE_SHA256)
        initials[arm]=cp['initial_state_sha256'];trained,report=m.train(cp,training,tuning,additional_steps=1)
        model=m.TemporalEventShapeEligibility(trained);predictions=model.predict_joint(m.source_queries(tuning))
        assert len(predictions['binary'])==len(predictions['shapes'])==2
        assert report['encoder_batch_forwards']==model.encoder_batch_forwards==1
        changed=[k for k in cp['model_state'] if cp['model_state'][k]!=trained['model_state'][k]]
        assert any(k.startswith('source.encoder.') for k in changed)
        assert any(k.startswith('shape_head.') for k in changed)==(arm=='auxiliary_shape')
        evidence[arm]={'test_optimizer_updates':1,'test_training_encoder_batch_forwards':1,'test_training_query_evaluations':16,
                       'test_inference_encoder_batch_forwards':1,'test_inference_query_evaluations':2,
                       'changed_tensor_names':changed,'prediction_sha256':m.digest(predictions)}
    assert len(set(initials.values()))==1
    assert str(m._torch().__version__)==parent['model_config']['torch_version']
    output={'schema':'event-shape-authenticated-carrier-fictional-smoke/v1',
            'parent':{'path':str(path),'sha256':m.PARENT_FILE_SHA256,'bytes':len(raw)},
            'parent_payload_sha256':m.PARENT_PAYLOAD_SHA256,'torch_version':str(m._torch().__version__),
            'training_manifest_sha256':m.digest(training),'tuning_manifest_sha256':m.digest(tuning),
            'same_initial_state_sha256':next(iter(initials.values())),'arms':evidence,'fictional_inputs_only':True,
            'experiment_optimizer_updates':0,'experiment_corpus_reads':0,'test_checkpoint_saved':False,'formula_admission':False}
    destination=os.environ.get('SHAPE_SMOKE_RECEIPT_PATH')
    if destination:
        with Path(destination).open('x') as stream:json.dump(output,stream,sort_keys=True,indent=2);stream.write('\n')
