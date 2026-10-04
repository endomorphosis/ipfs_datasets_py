"""Exact isolation of readout freezing and correct-teacher KL preservation."""
from copy import deepcopy
import json

import pytest
import torch

from ipfs_datasets_py.logic.autoformal import legal_clause_scope_preservation as subject


@pytest.fixture(scope='module')
def parent():
    torch.set_num_threads(1)
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(109)
        network=subject.boundary.model(torch)
    return subject.boundary.checkpoint(network,steps=800,training_manifest_sha256='a'*64,tuning_manifest_sha256='b'*64)


@pytest.fixture(scope='module')
def checkpoints(parent):
    return {arm:subject.build_checkpoint(parent,arm=arm,training_manifest_sha256='c'*64,
        tuning_manifest_sha256='d'*64,parent_file_sha256='e'*64) for arm in subject.ARMS}


@pytest.fixture
def sources():
    texts=['Board must retain reports.',
        'When the permit is active, Council may archive the dated filing packet.']
    return [{'candidate_id':f'opaque{index}','source_text':text,'source_sha256':subject.boundary.text_sha(text)}
        for index,text in enumerate(texts)]


@pytest.mark.parametrize('arm',subject.ARMS)
def test_exact_initial_graph_parent_logits_and_source_only_policy(parent,checkpoints,sources,arm):
    cp=checkpoints[arm];_,network=subject.restore(cp);_,old=subject.boundary.restore(parent)
    batch=subject.boundary.tensor_batch(torch,sources)
    with torch.inference_mode():
        actual=network(*batch[:3]);expected=old(*batch[:3])
    assert all(torch.equal(a,b)for a,b in zip(actual,expected))
    assert subject.decoder(cp).decode(sources)['rows']==subject.decoder(parent).decode(sources)['rows']
    assert all(cp['model_state']==value['model_state'] for value in checkpoints.values())
    assert cp['additional_optimizer_steps']==0 and cp['optimizer_steps']==800 and cp['optimizer_resumption_supported'] is False
    assert cp['parent_checkpoint']==parent and cp['adapter_implementation_sha256']==subject.adapter.implementation_sha()
    renamed=[{**s,'candidate_id':f'hidden-{index}'}for index,s in enumerate(sources)]
    left,right=subject.decoder(cp).decode(sources),subject.decoder(cp).decode(renamed)
    assert all(a['scope_logits']==b['scope_logits'] and a['boundary_logits']==b['boundary_logits']for a,b in zip(left['rows'],right['rows']))


@pytest.mark.parametrize('arm',subject.ARMS)
def test_trainable_inventory_gradients_fresh_adam_and_frozen_token_outputs(parent,checkpoints,sources,arm):
    _,network=subject.restore(checkpoints[arm]);trainable=subject.configure_trainable(network,arm)
    _,teacher=subject.boundary.restore(parent)
    teacher.requires_grad_(False);teacher.eval()
    before_teacher={name:t.clone()for name,t in teacher.state_dict().items()}
    optimizer=torch.optim.Adam(trainable,lr=.004);assert not optimizer.state
    assert sum(p.numel()for p in trainable)==subject.TRAINABLE_COUNTS[arm]
    assert {n for n,p in network.named_parameters()if p.requires_grad}==subject.trainable_names(arm)
    batch=subject.boundary.tensor_batch(torch,sources);labels=torch.tensor([0,1]);network.train()
    for _ in range(3):
        optimizer.zero_grad(set_to_none=True)
        with torch.no_grad():old_token,teacher_logits=teacher(*batch[:3])
        token,logits=network(*batch[:3]);loss,_=subject.objective_loss(torch,logits,labels,teacher_logits=teacher_logits,arm=arm)
        loss.backward();torch.nn.utils.clip_grad_norm_(trainable,5.);optimizer.step()
        assert token.requires_grad is False and torch.equal(token,old_token)
        assert all(p.grad is None for n,p in network.named_parameters()if n not in subject.trainable_names(arm))
        assert all(p.grad is None for p in teacher.parameters())
    assert not network.encoder.training and not network.boundary.training
    assert all(torch.equal(value,before_teacher[name])for name,value in teacher.state_dict().items())
    assert set(int(optimizer.state[p]['step'])for p in trainable)=={3}
    cp=subject.checkpoint(network,initial_checkpoint=checkpoints[arm],additional_steps=3)
    assert cp['optimizer_steps']==803
    if subject.READOUT_FROZEN[arm]:assert all(cp['model_state'][name]==parent['model_state'][name]for name in subject.SCOPE_PARAMETERS)
    else:assert any(cp['model_state'][name]!=parent['model_state'][name]for name in subject.SCOPE_PARAMETERS)
    assert cp['model_state']['scope_residual.weight']!=checkpoints[arm]['model_state']['scope_residual.weight']
    _,restored=subject.restore(json.loads(json.dumps(cp)))
    with torch.inference_mode():
        left,right=network(*batch[:3]),restored(*batch[:3])
    assert all(torch.equal(a,b)for a,b in zip(left,right))


@pytest.mark.parametrize('arm',subject.ARMS)
def test_loss_correct_mask_denominator_direction_and_gradients(arm):
    candidate=torch.tensor([[.4,-.8],[.8,.1],[-.5,1.2],[.1,.2]],dtype=torch.float64,requires_grad=True)
    teacher=torch.tensor([[1.,-.4],[1.4,-.1],[-1.,.9],[0.,0.]],dtype=torch.float64,requires_grad=True)
    labels=torch.tensor([0,1,1,0])
    total,parts=subject.objective_loss(torch,candidate,labels,teacher_logits=teacher,arm=arm)
    mask=torch.tensor([True,False,True,True]);weight=subject.DISTILLATION_WEIGHTS[arm]
    teacher_probability=torch.softmax(teacher.detach(),dim=-1)
    log_candidate=torch.log_softmax(candidate,dim=-1)
    kl=(teacher_probability*(torch.log_softmax(teacher.detach(),dim=-1)-log_candidate)).sum(-1)[mask].mean()
    nll=-log_candidate[torch.arange(4),labels]
    ce=(3*nll[0]+nll[1]+nll[2]+3*nll[3])/8
    torch.testing.assert_close(total,ce+weight*kl,rtol=0,atol=1e-15)
    assert parts['teacher_correct_mask']==mask.tolist() and parts['teacher_correct_count']==3
    assert parts['teacher_correct_unsupported_count']==2 and parts['teacher_correct_supported_count']==1
    assert parts['weighted_denominator']==8 and parts['teacher_scope_logits_sha256']==subject.digest(teacher.detach().tolist())
    assert parts['teacher_kl']==pytest.approx(float(kl.detach()),abs=1e-15)
    assert parts['teacher_kl_weight']==weight and parts['teacher_logits_detached'] and not parts['teacher_kl_class_weighted']
    total.backward()
    probability=torch.softmax(candidate.detach(),dim=-1)
    truth=torch.nn.functional.one_hot(labels,2).to(torch.float64)
    expected=(probability-truth)*torch.tensor([3,1,1,3],dtype=torch.float64)[:,None]/8
    expected+=weight*mask[:,None]*(probability-teacher_probability)/3
    torch.testing.assert_close(candidate.grad,expected,rtol=0,atol=1e-15)
    assert teacher.grad is None


@pytest.mark.parametrize('arm',subject.ARMS)
def test_empty_teacher_mask_is_finite_zero_and_exact_ce_gradient(arm):
    logits=torch.tensor([[1.,-2.],[-3.,4.]],dtype=torch.float64,requires_grad=True)
    teacher=torch.tensor([[-1.,2.],[3.,-4.]],dtype=torch.float64,requires_grad=True);labels=torch.tensor([0,1])
    loss,parts=subject.objective_loss(torch,logits,labels,teacher_logits=teacher,arm=arm)
    ce=torch.nn.functional.cross_entropy(logits,labels,weight=logits.new_tensor([3.,1.]))
    assert parts['teacher_correct_count']==0 and parts['teacher_kl']==parts['weighted_teacher_kl']==0.
    assert torch.equal(loss,ce)
    a=torch.autograd.grad(loss,logits,retain_graph=True)[0];b=torch.autograd.grad(ce,logits)[0]
    assert torch.equal(a,b) and teacher.grad is None


def test_zero_kl_for_identical_teacher_candidate_and_temperature_one():
    logits=torch.tensor([[400.,-100.],[-800.,200.]],dtype=torch.float64,requires_grad=True)
    loss,parts=subject.objective_loss(torch,logits,torch.tensor([0,1]),teacher_logits=logits.detach().clone(),arm='distill')
    assert parts['teacher_kl']==0. and parts['teacher_kl_temperature']==1.
    loss.backward();assert torch.isfinite(logits.grad).all()


def test_off_control_optimizer_bitmatches_previous_adapter(parent,checkpoints,sources):
    oldcp=subject.adapter.build_checkpoint(parent,arm='adapter',training_manifest_sha256='c'*64,
        tuning_manifest_sha256='d'*64,parent_file_sha256='e'*64)
    _,old=subject.adapter.restore(oldcp);_,new=subject.restore(checkpoints['control'])
    oldparameters=subject.adapter.configure_trainable(old,'adapter');newparameters=subject.configure_trainable(new,'control')
    optimizers=[torch.optim.Adam(p,lr=.004)for p in (oldparameters,newparameters)]
    batch=subject.boundary.tensor_batch(torch,sources);labels=torch.tensor([0,1]);_,teacher=subject.boundary.restore(parent)
    with torch.no_grad():teacher_logits=teacher(*batch[:3])[1]
    for _ in range(3):
        for network,optimizer,parameters in zip((old,new),optimizers,(oldparameters,newparameters)):
            optimizer.zero_grad(set_to_none=True);logits=network(*batch[:3])[1]
            loss=(subject.adapter.scope_loss(torch,logits,labels)[0] if network is old else
                subject.objective_loss(torch,logits,labels,teacher_logits=teacher_logits,arm='control')[0])
            loss.backward();torch.nn.utils.clip_grad_norm_(parameters,5.);optimizer.step()
        assert all(torch.equal(value,new.state_dict()[name])for name,value in old.state_dict().items())


@pytest.mark.parametrize('arm',['freeze_readout','freeze_distill'])
@pytest.mark.parametrize('name',['scope.weight','scope.bias'])
def test_frozen_readout_mutation_rejected_even_with_consistent_step_metadata(checkpoints,arm,name):
    cp=deepcopy(checkpoints[arm]);cp['additional_optimizer_steps']=1;cp['optimizer_steps']=801
    if name.endswith('weight'):cp['model_state'][name][0][0]+=.01
    else:cp['model_state'][name][0]+=.01
    with pytest.raises(ValueError,match='frozen scope readout'):subject.restore(cp)


@pytest.mark.parametrize('name',['embedding.weight','encoder.weight_ih_l0','boundary.weight'])
def test_non_scope_mutation_rejected_after_repairing_frozen_commitment(checkpoints,name):
    cp=deepcopy(checkpoints['distill']);cp['additional_optimizer_steps']=1;cp['optimizer_steps']=801
    cp['model_state'][name][0][0]+=.1
    cp['frozen_non_scope_state_sha256']=subject.digest(subject.frozen_state(cp['model_state']))
    with pytest.raises(ValueError,match='frozen'):subject.restore(cp)


@pytest.mark.parametrize('mutation',[
    lambda c:c.update(extra=1),lambda c:c.update(schema='unknown'),lambda c:c.update(implementation_sha256='0'*64),
    lambda c:c.update(adapter_implementation_sha256='0'*64),lambda c:c.update(readout_frozen=True),
    lambda c:c['training_config'].update(teacher_kl_weight=.5),lambda c:c['teacher_config'].update(temperature=2.),
    lambda c:c.update(trainable_parameter_count=130),lambda c:c.update(trainable_parameters=[]),
    lambda c:c.update(parent_checkpoint_sha256='0'*64),lambda c:c.update(initial_model_state_sha256='0'*64),
    lambda c:c.update(additional_optimizer_steps=401),lambda c:c.update(optimizer_steps=801),
    lambda c:c['model_state']['scope_residual.bias'].__setitem__(0,float('nan')),
])
def test_closed_provenance_loss_inventory_and_finite_shape_contract(checkpoints,mutation):
    cp=deepcopy(checkpoints['distill']);mutation(cp)
    with pytest.raises(ValueError):subject.restore(cp)


@pytest.mark.parametrize('teacher',[
    torch.tensor([[float('nan'),0.],[0.,1.]]),torch.zeros(2,3),torch.zeros(2,2,dtype=torch.float64),
])
def test_loss_rejects_nonfinite_or_misaligned_teacher(teacher):
    with pytest.raises(ValueError):subject.objective_loss(torch,torch.zeros(2,2),torch.tensor([0,1]),teacher_logits=teacher,arm='distill')


def test_decode_rejects_gold_fields_and_preserves_guard(checkpoints,sources):
    decoder=subject.decoder(checkpoints['freeze_distill'])
    with pytest.raises(ValueError,match='source-only'):decoder.decode([{**sources[0],'supported':True}])
    text='Both following rules apply: Board must retain reports. Council may file notices.'
    result=decoder.decode([{'candidate_id':'x','source_text':text,'source_sha256':subject.boundary.text_sha(text)}])
    assert result['rows'][0]['reason']=='declared_surface_policy_unsupported_scope' and result['rows'][0]['plan'] is None


def test_build_restore_isolate_rng_and_checkpoint_cannot_claim_resume(parent,checkpoints):
    torch.manual_seed(729);state=torch.random.get_rng_state().clone()
    subject.build_checkpoint(parent,arm='freeze_distill',training_manifest_sha256='c'*64,
        tuning_manifest_sha256='d'*64,parent_file_sha256='e'*64)
    subject.restore(checkpoints['freeze_distill'])
    assert torch.equal(state,torch.random.get_rng_state())
    cp=deepcopy(checkpoints['freeze_distill']);cp['optimizer_resumption_supported']=True
    with pytest.raises(ValueError):subject.restore(cp)
