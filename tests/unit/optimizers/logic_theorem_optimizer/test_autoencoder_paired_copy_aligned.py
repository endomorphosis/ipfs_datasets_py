from pathlib import Path
import pytest
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_copy_alignment as alignment
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_paired_copy_aligned as child
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_paired_copy as base


def pairs():
    source='agent must inspect cache .';target='<actor> agent <action> inspect <object> cache <modality> required'
    return [{'id':'e','direction':'encode','source':source,'target':target},
            {'id':'d','direction':'decode','source':target,'target':source}], [
            {'id':'v','direction':'encode','source':'user must inspect novel .','target':'validationonly'}]


def test_lcs_repeats_align_distinct_occurrences_and_skip_control_words():
    assert alignment.ordered_matches(('must','cache','cache','required','<actor>','end'),
        ('<object>','cache','cache','required','end'))==((1,1),(2,2),(4,5))
    assert alignment.ordered_matches(('cache',),('cache','cache'))==((0,0),)


def test_lcs_reordering_is_skipped_not_forced():
    assert alignment.ordered_matches(('agent','inspect','cache'),('cache','agent','inspect'))==((1,0),(2,1))


def test_copy_only_dropout_preserves_transformed_modality_and_specials():
    import torch
    records=base.legacy._pairs(pairs()[0]);vocabulary=list(base.SPECIAL)+sorted({t for _,s,d in records for t in s+d})
    source,lengths,copied,target,mask,size,matches,counts=alignment.batch(torch,records,vocabulary,generator=torch.Generator().manual_seed(0),dropout=1)
    assert source[0,2].item()==vocabulary.index('must') and source[1,-1].item()==vocabulary.index('required')
    assert not mask[:,0].any() and not ((matches>=0)&~mask.gather(1,matches.clamp_min(0))).any()
    assert source[0,1].item()==3 and counts=={'encode':3,'decode':3}
    assert matches[0,-1].item()==-1


def test_coverage_distinguishes_repeats_and_generator_steps():
    import torch
    labels=torch.tensor([[1,2,-1]]);mask=torch.tensor([[False,True,True,False]])
    good=torch.tensor([[[0.,1.,0.,0.],[0.,0.,1.,0.],[0.,.5,.5,0.]]],requires_grad=True)
    a,c=alignment.auxiliary_losses(torch,good,labels,mask);assert a.item()==c.item()==0
    bad=torch.tensor([[[0.,.9,.1,0.],[0.,.9,.1,0.],[0.,.5,.5,0.]]],requires_grad=True)
    a,c=alignment.auxiliary_losses(torch,bad,labels,mask);assert a>0 and c>0
    (a+c).backward();assert bad.grad[0,:2].abs().sum()>0 and bad.grad[0,2].abs().sum()==0
    with pytest.raises(ValueError,match='padding'):alignment.auxiliary_losses(torch,bad,torch.tensor([[0,2,-1]]),mask)


@pytest.mark.parametrize('value',[True,float('nan'),-1,1.1])
def test_objective_bounds(value):
    with pytest.raises(ValueError):alignment.validate_settings({'alignment_weight':value,'coverage_weight':.05})


@pytest.fixture(scope='module')
def checkpoints(tmp_path_factory):
    import torch
    torch.set_num_threads(1);root=tmp_path_factory.mktemp('aligned');train,tune=pairs()
    parent=base.train_paired_copy(train,tune,output_dir=root/'parent',epochs=5,max_seconds=15,hidden_size=16,embedding_dim=16)
    before=Path(parent['path']).read_bytes()
    result=child.train_paired_copy_continuation(train,tune,parent_descriptor=parent,output_dir=root/'child',epochs=2,max_seconds=15)
    assert Path(parent['path']).read_bytes()==before
    return parent,result


def test_actual_training_transfer_vocabulary_pins_and_inference(checkpoints):
    parent,descriptor=checkpoints;prior=base.load_paired_copy(parent);loaded=child.load_paired_copy_continuation(descriptor)
    assert loaded['training']['initial_state_sha256']==prior['training']['final_state_sha256']
    assert loaded['training']['final_state_sha256']!=loaded['training']['initial_state_sha256']
    assert loaded['model'].lexical.tolist()==prior['model'].lexical.tolist()
    assert 'validationonly' not in loaded['config']['vocabulary']
    assert loaded['training']['tuning_used_for_fit_or_selection'] is False
    assert loaded['config']['alignment_objective']=={'alignment_weight':.1,'coverage_weight':.05}
    report=child.infer_paired_copy_continuation(descriptor,'agent inspect NewSlot','encode',max_new_tokens=20)
    assert report['teacher_forcing'] is False and report['target_access'] is False
    ablated=child.infer_paired_copy_continuation(descriptor,'agent inspect NewSlot','encode',max_new_tokens=20,weight_ablation='zero_output_head')
    assert report['copy_trace']!=ablated['copy_trace']
    beam=child.infer_paired_copy_continuation_beam(descriptor,'agent inspect NewSlot','encode',beam_width=2,max_new_tokens=20)
    assert beam['native_decoder_calls']>0 and beam['target_access'] is False


def test_child_loader_standalone_and_legacy_loader_rejects(checkpoints,tmp_path):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_paired_copy_continuation as old
    descriptor=checkpoints[1];path=tmp_path/'standalone.json';path.write_bytes(Path(descriptor['path']).read_bytes());moved={**descriptor,'path':str(path)}
    child.load_paired_copy_continuation(moved)
    with pytest.raises(ValueError):old.load_paired_copy_continuation(moved)


def test_tampered_objective_or_pins_rejected_even_resigned(checkpoints,tmp_path):
    for key,value in [('alignment_objective',{'alignment_weight':-1,'coverage_weight':0}),('implementation',{})]:
        package=base._json(Path(checkpoints[1]['path']).read_bytes());package['config'][key]=value
        raw=base._raw(package);path=tmp_path/(key+'.json');path.write_bytes(raw)
        with pytest.raises(ValueError):child.load_paired_copy_continuation({**checkpoints[1],'path':str(path),'sha256':base._sha(raw)})


def test_auxiliary_objective_reaches_actual_encoder_gradients(checkpoints):
    import torch
    loaded=child.load_paired_copy_continuation(checkpoints[1]);model=loaded['model']
    batch=alignment.batch(torch,base.legacy._pairs(pairs()[0]),loaded['config']['vocabulary'])
    model.zero_grad(set_to_none=True)
    ce,_,_=alignment.loss(torch,model,batch,{'alignment_weight':0.,'coverage_weight':0.})
    ce.backward();baseline=model.encoder.weight_ih_l0.grad.detach().clone()
    model.zero_grad(set_to_none=True)
    guided,_,_=alignment.loss(torch,model,batch,{'alignment_weight':.1,'coverage_weight':.05})
    guided.backward()
    assert guided.item()>ce.item()
    assert not torch.equal(baseline,model.encoder.weight_ih_l0.grad)
    assert model.lexical.grad is None
