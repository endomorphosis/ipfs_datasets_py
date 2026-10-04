"""Behavioral checks for immutable token states and the residual scope readout."""
from copy import deepcopy
import json

import pytest
import torch

from ipfs_datasets_py.logic.autoformal import legal_clause_boundary_decoder as parent_runtime
from ipfs_datasets_py.logic.autoformal import legal_clause_scope_adapter as subject


def source(text, identity='opaque-source'):
    return {'candidate_id':identity,'source_text':text,'source_sha256':parent_runtime.text_sha(text)}


@pytest.fixture(scope='module')
def parent():
    torch.set_num_threads(1)
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(419)
        network=parent_runtime.model(torch)
    return parent_runtime.checkpoint(network,steps=800,training_manifest_sha256='a'*64,tuning_manifest_sha256='b'*64)


@pytest.fixture(scope='module')
def checkpoints(parent):
    return {arm:subject.build_checkpoint(parent,arm=arm,seed=1730,training_manifest_sha256='c'*64,
        tuning_manifest_sha256='d'*64,parent_file_sha256='e'*64) for arm in subject.ARMS}


@pytest.fixture
def sources():
    return [source('Board must retain reports.'),
        source('When the permit is active, Council may archive the dated filing packet.','opaque-long')]


@pytest.mark.parametrize('arm',subject.ARMS)
def test_initial_logits_exact_parent_and_shared_complete_initial_state(parent,checkpoints,sources,arm):
    _,original=parent_runtime.restore(parent);_,network=subject.restore(checkpoints[arm])
    batch=parent_runtime.tensor_batch(torch,sources)
    with torch.inference_mode():
        before=original(*batch[:3]);after=network(*batch[:3])
    assert all(torch.equal(a,b) for a,b in zip(before,after))
    assert checkpoints['control']['model_state']==checkpoints['adapter']['model_state']
    assert checkpoints['control']['initial_model_state_sha256']==checkpoints['adapter']['initial_model_state_sha256']
    assert checkpoints[arm]['optimizer_steps']==800 and checkpoints[arm]['additional_optimizer_steps']==0


@pytest.mark.parametrize('arm',subject.ARMS)
def test_initial_decode_complete_rows_equal_parent_and_ids_are_metadata(parent,checkpoints,sources,arm):
    old=subject.decoder(parent).decode(sources);new=subject.decoder(checkpoints[arm]).decode(sources)
    assert old['rows']==new['rows']
    renamed=[{**s,'candidate_id':f'x{index}'} for index,s in enumerate(sources)]
    result=subject.decoder(checkpoints[arm]).decode(renamed)
    for actual,prior in zip(result['rows'],new['rows']):
        assert actual['scope_logits']==prior['scope_logits'] and actual['boundary_logits']==prior['boundary_logits']
    assert new['target_access'] is new['references_supplied'] is new['training_executed'] is False


@pytest.mark.parametrize('arm',subject.ARMS)
def test_trainable_counts_and_exact_frozen_gradient_inventory(checkpoints,sources,arm):
    _,network=subject.restore(checkpoints[arm]);parameters=subject.configure_trainable(network,arm)
    assert sum(p.numel() for p in parameters)==subject.TRAINABLE_COUNTS[arm]
    assert {n for n,p in network.named_parameters() if p.requires_grad}==subject.trainable_names(arm)
    network.train();assert network.training and not network.encoder.training and not network.embedding.training
    batch=parent_runtime.tensor_batch(torch,sources);token,scope=network(*batch[:3])
    loss,_=subject.scope_loss(torch,scope,torch.tensor([0,1]));loss.backward()
    assert token.requires_grad is False
    assert all(p.grad is None for n,p in network.named_parameters() if n not in subject.trainable_names(arm))
    assert network.scope.weight.grad is not None and bool((network.scope.weight.grad!=0).any())
    if arm=='adapter':
        assert bool((network.scope_residual.weight.grad!=0).any())
        assert torch.count_nonzero(network.attention_hidden.weight.grad)==0


def test_adapter_attention_receives_gradients_after_first_residual_update(checkpoints,sources):
    _,network=subject.restore(checkpoints['adapter']);optimizer=torch.optim.Adam(subject.configure_trainable(network,'adapter'),lr=.004)
    batch=parent_runtime.tensor_batch(torch,sources)
    for _ in range(2):
        optimizer.zero_grad(set_to_none=True)
        loss,_=subject.scope_loss(torch,network(*batch[:3])[1],torch.tensor([0,1]));loss.backward()
        optimizer.step()
    assert bool((network.attention_hidden.weight.grad!=0).any())
    assert bool((network.attention_score.weight.grad!=0).any())


def test_control_optimizer_matches_original_scope_only_continuation_exactly(parent,checkpoints,sources):
    _,original=parent_runtime.restore(parent);_,control=subject.restore(checkpoints['control'])
    for name,parameter in original.named_parameters():parameter.requires_grad_(name in subject.SCOPE_PARAMETERS)
    old_optimizer=torch.optim.Adam([p for p in original.parameters() if p.requires_grad],lr=.004)
    new_optimizer=torch.optim.Adam(subject.configure_trainable(control,'control'),lr=.004)
    batch=parent_runtime.tensor_batch(torch,sources);labels=torch.tensor([0,1])
    for _ in range(3):
        for network,optimizer in ((original,old_optimizer),(control,new_optimizer)):
            optimizer.zero_grad(set_to_none=True)
            loss,_=subject.scope_loss(torch,network(*batch[:3])[1],labels);loss.backward()
            torch.nn.utils.clip_grad_norm_([p for p in network.parameters() if p.requires_grad],5.)
            optimizer.step()
        assert all(torch.equal(value,control.state_dict()[name]) for name,value in original.state_dict().items())


def test_attention_masks_padding_and_valid_tokens_have_unit_mass(checkpoints):
    _,network=subject.restore(checkpoints['adapter'])
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(81);values=torch.randn(3,7,64)
    lengths=torch.tensor([1,4,7]);pooled,weights=network.attend(values,lengths)
    mask=torch.arange(7)[None,:]<lengths[:,None]
    assert torch.count_nonzero(weights[~mask])==0
    torch.testing.assert_close(weights.sum(1),torch.ones(3),rtol=0,atol=1e-7)
    changed=values.clone();changed[~mask]=10000
    other,other_weights=network.attend(changed,lengths)
    assert torch.equal(pooled,other) and torch.equal(weights,other_weights)


def test_attention_extra_padding_does_not_change_pooling(checkpoints):
    _,network=subject.restore(checkpoints['adapter'])
    torch.manual_seed(11);values=torch.randn(2,4,64);lengths=torch.tensor([2,4])
    padded=torch.cat([values,torch.randn(2,9,64)],dim=1)
    pool,weights=network.attend(values,lengths);other,other_weights=network.attend(padded,lengths)
    torch.testing.assert_close(pool,other,rtol=1e-6,atol=1e-7)
    torch.testing.assert_close(weights,other_weights[:,:4],rtol=1e-6,atol=1e-7)
    assert torch.count_nonzero(other_weights[:,4:])==0


@pytest.mark.parametrize('lengths',[torch.tensor([0]),torch.tensor([4])])
def test_attention_rejects_empty_or_out_of_bounds_lengths(checkpoints,lengths):
    _,network=subject.restore(checkpoints['adapter'])
    with pytest.raises(ValueError,match='lengths'):network.attend(torch.zeros(1,3,64),lengths)


@pytest.mark.parametrize('arm',subject.ARMS)
def test_trained_scope_changes_but_token_logits_remain_bitexact_and_restore(checkpoints,parent,sources,arm):
    _,network=subject.restore(checkpoints[arm]);parameters=subject.configure_trainable(network,arm)
    optimizer=torch.optim.Adam(parameters,lr=.004);assert not optimizer.state
    _,original=parent_runtime.restore(parent);batch=parent_runtime.tensor_batch(torch,sources)
    with torch.inference_mode():initial=original(*batch[:3])
    for _ in range(3):
        optimizer.zero_grad(set_to_none=True);network.train()
        loss,_=subject.scope_loss(torch,network(*batch[:3])[1],torch.tensor([0,1]));loss.backward()
        torch.nn.utils.clip_grad_norm_(parameters,5.);optimizer.step()
    cp=subject.checkpoint(network,initial_checkpoint=checkpoints[arm],additional_steps=3)
    assert cp['optimizer_steps']==803 and cp['optimizer_resumption_supported'] is False
    _,restored=subject.restore(json.loads(json.dumps(cp)))
    with torch.inference_mode():
        actual=network(*batch[:3]);replayed=restored(*batch[:3])
    assert torch.equal(actual[0],initial[0]) and not torch.equal(actual[1],initial[1])
    assert all(torch.equal(a,b) for a,b in zip(actual,replayed))
    assert subject.assert_frozen_state(parent['model_state'],cp['model_state'])==cp['frozen_non_scope_state_sha256']


@pytest.mark.parametrize('name',['embedding.weight','encoder.weight_ih_l0','boundary.weight'])
def test_repaired_frozen_hash_does_not_allow_non_scope_mutation(checkpoints,name):
    cp=deepcopy(checkpoints['adapter']);cp['additional_optimizer_steps']=1;cp['optimizer_steps']+=1
    cp['model_state'][name][0][0]+=.5
    cp['frozen_non_scope_state_sha256']=subject.digest(subject.frozen_state(cp['model_state']))
    with pytest.raises(ValueError,match='frozen'):subject.restore(cp)


def test_control_rejects_any_adapter_change_even_with_step_and_repaired_hash(checkpoints):
    cp=deepcopy(checkpoints['control']);cp['additional_optimizer_steps']=1;cp['optimizer_steps']+=1
    cp['model_state']['scope_residual.bias'][0]=.1
    with pytest.raises(ValueError,match='control adapter'):subject.restore(cp)


@pytest.mark.parametrize('mutate',[
    lambda c:c.update(extra=True), lambda c:c.update(implementation_sha256='0'*64),
    lambda c:c.update(parent_checkpoint_sha256='0'*64), lambda c:c.update(initial_model_state_sha256='0'*64),
    lambda c:c.update(additional_optimizer_steps=-1), lambda c:c.update(additional_optimizer_steps=401),
    lambda c:c.update(optimizer_steps=801), lambda c:c.update(optimizer_resumption_supported=True),
    lambda c:c['model_state']['scope_residual.bias'].append(0),
    lambda c:c['model_state']['scope_residual.bias'].__setitem__(0,float('nan')),
    lambda c:c['model_state']['scope.bias'].__setitem__(0,100),
])
def test_closed_finite_initial_checkpoint_and_provenance_rejections(checkpoints,mutate):
    cp=deepcopy(checkpoints['adapter']);mutate(cp)
    with pytest.raises(ValueError):subject.restore(cp)


def test_weighted_loss_denominator_and_gradients_match_analytic_class_nll():
    logits=torch.tensor([[1.,-.2],[.3,-.7],[-.4,.9]],dtype=torch.float64,requires_grad=True)
    labels=torch.tensor([0,0,1]);loss,report=subject.scope_loss(torch,logits,labels)
    nll=-torch.log_softmax(logits,dim=-1)[torch.arange(3),labels]
    expected=(3*nll[:2].sum()+nll[2])/7
    assert report['weighted_denominator']==7 and report['unsupported_count']==2 and report['supported_count']==1
    torch.testing.assert_close(loss,expected,rtol=0,atol=1e-15)
    a=torch.autograd.grad(loss,logits,retain_graph=True)[0];b=torch.autograd.grad(expected,logits)[0]
    torch.testing.assert_close(a,b,rtol=0,atol=1e-15)
    assert abs(report['cross_entropy']-(3*report['unsupported_nll_sum']+report['supported_nll_sum'])/7)<1e-15


def test_build_and_restore_preserve_callers_rng(parent,checkpoints):
    torch.manual_seed(777);initial=torch.random.get_rng_state().clone()
    subject.build_checkpoint(parent,arm='adapter',training_manifest_sha256='c'*64,tuning_manifest_sha256='d'*64,parent_file_sha256='e'*64)
    assert torch.equal(initial,torch.random.get_rng_state())
    subject.restore(checkpoints['adapter'])
    assert torch.equal(initial,torch.random.get_rng_state())


def test_source_labels_cannot_enter_adapter_decode(checkpoints,sources):
    with pytest.raises(ValueError,match='source-only'):
        subject.decoder(checkpoints['adapter']).decode([{**sources[0],'supported':True}])


def test_surface_policy_and_unsupported_profile_stay_unchanged(checkpoints):
    decoder=subject.decoder(checkpoints['adapter'])
    result=decoder.decode([source('Both following rules apply: Board must retain reports. Council may file notices.')])
    assert result['rows'][0]['reason']=='declared_surface_policy_unsupported_scope'
    assert result['rows'][0]['plan'] is None
    with pytest.raises(ValueError,match='profile'):
        decoder.decode([source('Board must retain reports.')],source_profile='nested_scope')
