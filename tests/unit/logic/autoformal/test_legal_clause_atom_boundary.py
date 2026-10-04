"""Warm lineage, unchanged scope and balanced token-preservation behavior."""
from copy import deepcopy
import json

import pytest
import torch

from ipfs_datasets_py.logic.autoformal import legal_clause_boundary_decoder as base
from ipfs_datasets_py.logic.autoformal import legal_clause_heading_boundary as heading
from ipfs_datasets_py.logic.autoformal import legal_clause_atom_boundary as subject


@pytest.fixture(scope='module')
def parents():
    torch.set_num_threads(1)
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(751);network=base.model(torch)
    original=base.checkpoint(network,steps=800,training_manifest_sha256='a'*64,tuning_manifest_sha256='b'*64)
    warm=heading.build_checkpoint(original,arm='rehearsal',training_manifest_sha256='c'*64,
        tuning_manifest_sha256='d'*64,parent_file_sha256='e'*64)
    # A synthetic nonzero predecessor state tests warm initialization, without
    # running or claiming a400-step experiment in this fixture.
    warm['model_state']['boundary_residual.weight'][0]=torch.tensor([.02*(i-7) for i in range(16)],dtype=torch.float32).tolist()
    warm['model_state']['boundary_residual.bias'][0]=float(torch.tensor(.17,dtype=torch.float32))
    warm['additional_optimizer_steps']=400;warm['optimizer_steps']=1200
    heading.restore(warm)
    return original,warm


@pytest.fixture(scope='module')
def initial(parents):
    return {arm:subject.build_checkpoint(parents[1],arm=arm,training_manifest_sha256='f'*64,
        tuning_manifest_sha256='1'*64,parent_file_sha256='2'*64) for arm in subject.ARMS}


@pytest.fixture
def rows():
    texts=['Records.—Board must retain reports. Council may file notices.',
        'Agency must publish the current register.',
        'Unless Council may file notices, Board must retain all published reports.']
    result=[]
    for i,text in enumerate(texts):
        ends=[text.index('reports.')+len('reports.'),len(text)] if i==0 else [len(text)] if i==1 else []
        result.append({'candidate_id':str(i),'source_text':text,'source_sha256':base.text_sha(text),
            'supported':i<2,'clauses':[{'char_start':0,'char_end':end} for end in ends]})
    return result


def source_rows(rows):
    return [{k:r[k] for k in ('candidate_id','source_text','source_sha256')} for r in rows]


def tensors(rows):
    ids,features,lengths,labels,scopes,valid=base.tensor_batch(torch,rows,labels=True)
    positive=valid & scopes.bool()[:,None] & labels.bool()
    editorial=torch.zeros_like(valid);editorial[0,1:3]=True
    terminal=torch.arange(valid.shape[1])[None,:] == lengths[:,None]-1
    transition=positive & ~terminal
    atom=torch.zeros_like(valid)
    for i,row in enumerate(rows[:2]):
        for j,t in enumerate(base.tokenize(row['source_text'])):
            if t['text'] in ('Board','Council','Agency'):atom[i,j]=True
    return (ids,features,lengths),(labels,valid,scopes,positive,editorial,transition,atom)


@pytest.mark.parametrize('arm',subject.ARMS)
def test_initial_state_and_full_outputs_equal_warm_not_original(parents,initial,rows,arm):
    original,warm=parents;_,network=subject.restore(initial[arm]);_,prior=heading.restore(warm);_,teacher=base.restore(original)
    args,_=tensors(rows)
    with torch.inference_mode(): actual=network(*args);expected=prior(*args);old=teacher(*args)
    assert all(torch.equal(a,b) for a,b in zip(actual,expected))
    assert torch.equal(actual[1],old[1]) and not torch.equal(actual[0],old[0])
    assert initial[arm]['model_state'] == warm['model_state']
    assert all(initial[arm]['model_state']==cp['model_state'] for cp in initial.values())
    assert initial[arm]['parent_checkpoint']==warm and initial[arm]['original_parent_checkpoint_sha256']==base.digest(original)
    assert initial[arm]['original_parent_file_sha256']==warm['parent_file_sha256']
    assert initial[arm]['optimizer_steps']==1200 and initial[arm]['additional_optimizer_steps']==0
    sources=source_rows(rows)
    assert subject.decoder(initial[arm]).decode(sources)['rows']==subject.decoder(warm).decode(sources)['rows']
    assert subject.decoder(original).checkpoint==original


@pytest.mark.parametrize('arm',subject.ARMS)
def test_updates_only_residuals_and_preserve_scope_and_original_heads(parents,initial,rows,arm):
    _,network=subject.restore(initial[arm]);parameters=subject.configure_trainable(network,arm)
    assert sum(p.numel() for p in parameters)==1057
    optimizer=torch.optim.Adam(parameters,lr=.004);assert not optimizer.state
    args,lossargs=tensors(rows);_,teacher=base.restore(parents[0])
    with torch.no_grad():teacher_logits,original_scope=teacher(*args)
    for _ in range(3):
        network.train();optimizer.zero_grad(set_to_none=True)
        logits,scope=network(*args)
        assert torch.equal(scope,original_scope) and not scope.requires_grad
        loss,_=subject.objective_loss(torch,logits,*lossargs,teacher_logits=teacher_logits,arm=arm)
        loss.backward();torch.nn.utils.clip_grad_norm_(parameters,5.);optimizer.step()
        assert all(p.grad is None for n,p in network.named_parameters() if n not in subject.ADAPTER_PARAMETERS)
    assert {int(optimizer.state[p]['step']) for p in parameters}=={3}
    cp=subject.checkpoint(network,initial_checkpoint=initial[arm],additional_steps=3)
    assert cp['optimizer_steps']==1203 and cp['additional_optimizer_steps']==3
    assert cp['optimizer_resumption_supported'] is False
    assert cp['model_state']!=parents[1]['model_state']
    assert all(cp['model_state'][k]==v for k,v in parents[0]['model_state'].items())
    assert subject.assert_frozen_state(parents[0]['model_state'],cp['model_state'])==subject.assert_frozen_state(parents[1]['model_state'],cp['model_state'])
    _,restored=subject.restore(json.loads(json.dumps(cp)))
    with torch.inference_mode(): replay=restored(*args);actual=network(*args)
    assert all(torch.equal(a,b) for a,b in zip(actual,replay))


def test_continuation_matches_previous_heading_optimizer_exactly(parents,initial,rows):
    _,old=heading.restore(parents[1]);_,new=subject.restore(initial['continuation'])
    optimizers=[torch.optim.Adam([p for p in n.parameters() if p.requires_grad],lr=.004) for n in (old,new)]
    args,lossargs=tensors(rows);_,teacher=base.restore(parents[0])
    with torch.no_grad():teacher_logits=teacher(*args)[0]
    for _ in range(3):
        for i,(network,optimizer) in enumerate(zip((old,new),optimizers)):
            network.train();optimizer.zero_grad(set_to_none=True);logits=network(*args)[0]
            if i==0:loss,_=heading.objective_loss(torch,logits,*lossargs[:5],arm='rehearsal')
            else:loss,_=subject.objective_loss(torch,logits,*lossargs,teacher_logits=teacher_logits,arm='continuation')
            loss.backward();torch.nn.utils.clip_grad_norm_([p for p in network.parameters() if p.requires_grad],5.);optimizer.step()
        assert all(torch.equal(value,new.state_dict()[name]) for name,value in old.state_dict().items())


def kl_case(kind):
    logits=torch.tensor([[.8,-.6,1.2,-1.9],[-.3,.6,-.7,.8]],dtype=torch.float64,requires_grad=True)
    labels=torch.tensor([[1.,0.,1.,0.],[0.,1.,0.,1.]],dtype=torch.float64)
    valid=torch.tensor([[True,True,True,False],[True,True,True,True]])
    supported=torch.tensor([True,False])
    values={'both':[[0.,-1.,3.,7.],[3.,3.,3.,3.]],'positive':[[0.,1.,3.,7.],[3.,3.,3.,3.]],
        'negative':[[-1.,-1.,-1.,7.],[3.,3.,3.,3.]],'empty':[[-1.,1.,-1.,7.],[3.,3.,3.,3.]]}[kind]
    teacher=torch.tensor(values,dtype=torch.float64,requires_grad=True)
    return logits,labels,valid,supported,teacher


@pytest.mark.parametrize('kind,classes',[('both',2),('positive',1),('negative',1),('empty',0)])
def test_KL_available_class_mean_masks_tie_and_teacher_detachment(kind,classes):
    logits,labels,valid,supported,teacher=kl_case(kind)
    loss,report=subject.teacher_token_kl(torch,logits,labels,valid,supported,teacher_logits=teacher)
    groups={0:[],1:[]}
    for i in range(len(logits)):
        for j in range(logits.shape[1]):
            if not(valid[i,j] and supported[i]) or bool(teacher[i,j]>=0)!=bool(labels[i,j]):continue
            t=teacher[i,j].detach();x=logits[i,j]
            p=torch.sigmoid(t);q=torch.sigmoid(-t)
            groups[int(labels[i,j])].append(p*(torch.log(p)-torch.nn.functional.logsigmoid(x)) + q*(torch.log(q)-torch.nn.functional.logsigmoid(-x)))
    means=[torch.stack(g).mean() for g in groups.values() if g]
    oracle=sum(means)/len(means) if means else logits.sum()*0.
    torch.testing.assert_close(loss,oracle,rtol=1e-12,atol=1e-12)
    gradient,teacher_gradient=torch.autograd.grad(loss,(logits,teacher),allow_unused=True,retain_graph=True)
    expected=torch.autograd.grad(oracle,logits)[0]
    torch.testing.assert_close(gradient,expected,rtol=1e-12,atol=1e-12)
    assert teacher_gradient is None and report['teacher_available_class_count']==classes
    mask=torch.tensor(report['teacher_correct_mask'])
    assert torch.count_nonzero(gradient[~mask])==0
    assert report['teacher_empty_mask'] is (classes==0)
    assert report['teacher_correct_positive_count']==len(groups[1]) and report['teacher_correct_negative_count']==len(groups[0])
    if kind in ('both','positive'):assert report['teacher_positive_mask'][0][0] is True


@pytest.mark.parametrize('scale',[1.,100.,1000.])
def test_KL_is_finite_for_saturated_logits_and_identical_teacher_is_zero(scale):
    logits=torch.tensor([[-scale,scale]],dtype=torch.float64,requires_grad=True)
    labels=torch.tensor([[0.,1.]],dtype=torch.float64);valid=torch.ones_like(labels,dtype=torch.bool);supported=torch.tensor([True])
    loss,report=subject.teacher_token_kl(torch,logits,labels,valid,supported,teacher_logits=logits.detach().clone())
    assert float(loss)==0. and report['teacher_available_class_count']==2
    assert bool(torch.isfinite(torch.autograd.grad(loss,logits)[0]).all())


@pytest.mark.parametrize('arm',subject.ARMS)
def test_objective_components_values_and_gradients_match_independent_formula(rows,arm):
    _,args=tensors(rows);labels,valid,supported,positive,editorial,transition,atom=args
    labels=labels.double();args=(labels,valid,supported,positive,editorial,transition,atom)
    logits=torch.linspace(-2.,2.,labels.numel(),dtype=torch.float64).reshape_as(labels).requires_grad_()
    teacher=torch.where(labels.bool(),torch.ones_like(labels),-torch.ones_like(labels)).requires_grad_()
    loss,parts=subject.objective_loss(torch,logits,*args,teacher_logits=teacher,arm=arm)
    common,_=heading.objective_loss(torch,logits,*args[:5],arm='rehearsal')
    atom_term=.5*(torch.logaddexp(torch.zeros_like(logits[transition]),-logits[transition]).mean()+
        torch.logaddexp(torch.zeros_like(logits[atom]),logits[atom]).mean())
    kl,_=subject.teacher_token_kl(torch,logits,labels,valid,supported,teacher_logits=teacher)
    oracle=common+subject.ATOM_WEIGHTS[arm]*atom_term+subject.TEACHER_WEIGHTS[arm]*kl
    assert loss==oracle and parts['heading_objective']==float(common.detach())
    gradient,teacher_gradient=torch.autograd.grad(loss,(logits,teacher),allow_unused=True)
    assert teacher_gradient is None
    assert torch.count_nonzero(gradient[~(valid & supported.bool()[:,None])])==0
    assert parts['atom_positive_count']==1 and parts['atom_negative_count']==3


@pytest.mark.parametrize('change',['empty_transition','final_terminal','empty_atom','positive_atom','unsupported_atom','padding_atom','wrong_teacher_shape','teacher_nan'])
def test_invalid_atom_or_teacher_masks_fail_closed(rows,change):
    _,args=tensors(rows);args=[t.clone() for t in args];labels,valid,supported,positive,editorial,transition,atom=args
    teacher=torch.zeros_like(labels)
    if change=='empty_transition':transition.zero_()
    elif change=='final_terminal':transition |= positive
    elif change=='empty_atom':atom.zero_()
    elif change=='positive_atom':atom |= positive
    elif change=='unsupported_atom':atom[2,0]=True
    elif change=='padding_atom':atom[1,-1]=True
    elif change=='wrong_teacher_shape':teacher=teacher[:1]
    elif change=='teacher_nan':teacher[0,0]=float('nan')
    with pytest.raises(ValueError):subject.objective_loss(torch,torch.zeros_like(labels),*args,teacher_logits=teacher,arm='continuation')


@pytest.mark.parametrize('name',['embedding.weight','encoder.weight_ih_l0','boundary.weight','scope.weight'])
def test_repaired_frozen_hash_cannot_change_original_state(initial,name):
    cp=deepcopy(initial['distill']);cp['additional_optimizer_steps']=1;cp['optimizer_steps']+=1
    cp['model_state'][name][0][0]+=.25
    cp['frozen_parent_state_sha256']=subject.digest(subject.frozen_state(cp['model_state']))
    with pytest.raises(ValueError,match='frozen'):subject.restore(cp)


@pytest.mark.parametrize('mutate',[
    lambda c:c.update(extra=True),lambda c:c.update(parent_checkpoint_sha256='0'*64),
    lambda c:c.update(original_parent_checkpoint_sha256='0'*64),lambda c:c.update(original_parent_file_sha256='0'*64),
    lambda c:c.update(heading_implementation_sha256='0'*64),lambda c:c.update(initial_model_state_sha256='0'*64),
    lambda c:c.update(additional_optimizer_steps=401),lambda c:c.update(optimizer_steps=800),
    lambda c:c.update(optimizer_resumption_supported=True),lambda c:c.update(warm_parent_is_unqualified_research_candidate=False),
    lambda c:c['model_state']['boundary_residual.bias'].__setitem__(0,float('nan')),
    lambda c:c['model_state']['boundary_residual.bias'].__setitem__(0,.91),
    lambda c:c['teacher_config'].__setitem__('reduction','all_tokens'),
    lambda c:c['training_config'].__setitem__('teacher_kl_weight',.5),
])
def test_checkpoint_lineage_counter_config_and_initial_state_rejections(initial,mutate):
    cp=deepcopy(initial['distill']);mutate(cp)
    with pytest.raises(ValueError):subject.restore(cp)


def test_wrong_warm_arm_or_step_is_rejected(parents):
    for change in ('control','step'):
        warm=deepcopy(parents[1])
        if change=='control':warm['arm']='control';warm['training_config']=heading.arm_config('control')
        else:warm['additional_optimizer_steps']=200;warm['optimizer_steps']=1000
        with pytest.raises(ValueError):subject.build_checkpoint(warm,arm='continuation',training_manifest_sha256='a'*64,tuning_manifest_sha256='b'*64,parent_file_sha256='c'*64)


def test_RNG_and_source_only_contract(parents,initial,rows):
    torch.manual_seed(31);state=torch.random.get_rng_state().clone()
    subject.build_checkpoint(parents[1],arm='distill',training_manifest_sha256='a'*64,tuning_manifest_sha256='b'*64,parent_file_sha256='c'*64)
    subject.restore(initial['distill']);assert torch.equal(state,torch.random.get_rng_state())
    sources=source_rows(rows);decoder=subject.decoder(initial['distill'])
    original=decoder.decode(sources)['rows'];other=decoder.decode([{**s,'candidate_id':'other'+str(i)} for i,s in enumerate(sources)])['rows']
    assert all(a['scope_logits']==b['scope_logits'] and a['boundary_logits']==b['boundary_logits'] for a,b in zip(original,other))
    with pytest.raises(ValueError,match='source-only'):decoder.decode([{**sources[0],'atom_spans':[]}])


@pytest.fixture
def atom_example():
    text='Records.—Board Dept. must retain reports within 12 days unless the permit is active.'
    source=text+' '+text
    rule={'actor':'Board Dept.','temporal':['within 12 days'],'exceptions':['the permit is active']}
    clauses=[{'char_start':start,'char_end':start+len(text),'rule':deepcopy(rule)} for start in (0,len(text)+1)]
    row={'candidate_id':'opaque-repeated','source_text':source,'source_sha256':base.text_sha(source),'supported':True,'clauses':clauses}
    spans=[]
    for clause in clauses:
        for kind,atom in [('actor',rule['actor']),('temporal',rule['temporal'][0]),('exceptions',rule['exceptions'][0])]:
            start=clause['char_start']+text.index(atom)
            spans.append({'kind':kind,'char_start':start,'char_end':start+len(atom)})
    tokens=base.tokenize(source);ends={c['char_end'] for c in clauses}
    positive=[i for i,t in enumerate(tokens) if t['char_end'] in ends and t['char_end'] != len(source)]
    negative=[i for i,t in enumerate(tokens) if t['char_end'] not in ends
        and any(s['char_start'] <= t['char_start'] < t['char_end'] <= s['char_end'] for s in spans)]
    record={'candidate_id':row['candidate_id'],'source_sha256':row['source_sha256'],
        'inter_clause_end_token_indices':positive,'atom_interior_negative_token_indices':negative,
        'atom_spans':spans,'provenance':subject.ATOM_PROVENANCE}
    return row,record


def test_atom_roles_bind_repeated_occurrences_and_include_words_numbers_punctuation(atom_example):
    row,record=atom_example
    assert subject.validate_atom_roles(row,record)==record
    unsupported={'candidate_id':'unsupported','source_text':'Both following rules apply.','supported':False}
    positive,negative=subject.atom_role_masks(torch,[row,unsupported],[record])
    tokens=base.tokenize(row['source_text'])
    negative_text=[token['text'] for i,token in enumerate(tokens) if negative[0,i]]
    assert negative_text.count('12')==2 and negative_text.count('Board')==2 and negative_text.count('.')==2
    assert len(record['atom_spans'])==6 and int(positive.sum())==1
    assert int(positive[1].sum())==int(negative[1].sum())==0
    assert not bool((positive & negative).any())
    assert not positive[0,len(tokens)-1] and not negative[0,len(tokens)-1]
    other=subject.atom_role_masks(torch,[row],{row['candidate_id']:record})
    assert torch.equal(other[0][0],positive[0]) and torch.equal(other[1][0],negative[0])


@pytest.mark.parametrize('change',['kind','offset','missing_span','omit_word','terminal_positive','omit_transition','bool_index','source_hash','extra_key','bad_provenance'])
def test_repaired_atom_metadata_does_not_allow_unbound_roles(atom_example,change):
    row,record=deepcopy(atom_example)
    if change=='kind':record['atom_spans'][0]['kind']='exceptions'
    elif change=='offset':record['atom_spans'][0]['char_start']+=1
    elif change=='missing_span':record['atom_spans'].pop()
    elif change=='omit_word':record['atom_interior_negative_token_indices'].pop(0)
    elif change=='terminal_positive':record['inter_clause_end_token_indices'].append(len(base.tokenize(row['source_text']))-1)
    elif change=='omit_transition':record['inter_clause_end_token_indices']=[]
    elif change=='bool_index':record['atom_interior_negative_token_indices'][0]=True
    elif change=='source_hash':record['source_sha256']='0'*64
    elif change=='extra_key':record['predicted_correct']=True
    elif change=='bad_provenance':record['provenance']='heuristic'
    with pytest.raises(ValueError):subject.validate_atom_roles(row,record)


@pytest.mark.parametrize('change',['ambiguous_actor','overlap','duplicate_qualifier','unsupported_annotation','missing_annotation','duplicate_annotation'])
def test_ambiguous_overlap_and_missing_atom_supervision_rejected(atom_example,change):
    row,record=deepcopy(atom_example)
    if change=='ambiguous_actor':
        row['clauses'][0]['rule']['actor']='.'
    elif change=='overlap':
        row['clauses'][0]['rule']['exceptions']=[row['clauses'][0]['rule']['actor']]
    elif change=='duplicate_qualifier':row['clauses'][0]['rule']['temporal']*=2
    elif change=='unsupported_annotation':row['supported']=False
    annotations=[] if change=='missing_annotation' else [record,deepcopy(record)] if change=='duplicate_annotation' else [record]
    with pytest.raises(ValueError):subject.atom_role_masks(torch,[row],annotations)
