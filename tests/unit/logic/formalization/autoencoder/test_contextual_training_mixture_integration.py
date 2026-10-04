"""Tiny random CPU sidecars test wiring only; no saved model/native training."""
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import subprocess
from types import SimpleNamespace
import sys
import time

import pytest
torch=pytest.importorskip('torch')
from ipfs_datasets_py.logic.formalization import autoencoder as package
from ipfs_datasets_py.logic.formalization.autoencoder import contextual_training_mixture as mixture
from ipfs_datasets_py.logic.formalization.autoencoder import long_span_source_value_training as trainer
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core
from . import test_action_contrastive_decoder_training as action_fixtures
from . import test_source_modality_training_integration as integration
from .test_contextual_training_mixture import fixture as corpus_fixture


@pytest.fixture(autouse=True)
def cpu():
    old=torch.get_num_threads();torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


def fixture(monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment_v2 as conditioning
    from ipfs_datasets_py.logic.formalization.autoencoder import ordered_clause_recurrent_decoder_experiment as recurrent
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as numerical
    _,_,prepared,_=corpus_fixture(monkeypatch)
    _,_,_,options,_=action_fixtures.sources(duplicate=False)
    codec=prepared['codec'];options['codec']=codec
    options['input_transform']=dict(mode='none',origin='training_only',mean=[0.]*384,scale=1.)
    options['lineage']['teacher_codec_sha256']=core.digest(codec)
    options['lineage']['teacher_output_limit']=512
    rule=dict(actor='registrar',action='approve',object='notice',modality='O',conditions=[],exceptions=[],temporal=[])
    rules=[rule,dict(rule,actor='trustee'),dict(rule,actor='secretary',action='preserve')]
    contexts={};splits={};references={}
    for split,start in (('train',0),('validation',4)):
        rows=[];refs=[];cache=[]
        for i,r in enumerate(rules):
            text=split+' tiny source '+str(i)+'.';identity=split+'-'+str(i);target={'rules':[r]}
            vector=[float(j==start+i) for j in range(384)]
            rows.append(dict(id=identity,source_text=text,input=vector,target_ids=mixture.authored.base._encode(target,codec)))
            refs.append(dict(id=identity,source_text=text,target=target,clause_count=1))
            cache.append(dict(id=identity,source_text=text,input=vector))
        splits[split]=rows;references[split]=refs
        contexts[split]=mixture.context.build_source_contexts(mixture._source_rows(rows),cache)
    train,tune=splits['train'],splits['validation']
    options.update(training_references=references['train'],validation_references=references['validation'],
        curriculum=[dict(name='all',training_ids=[r['id'] for r in train],epochs=2)])
    options['config'].update(max_target_tokens=512,max_memory_bytes=1073741824,max_seconds=30,batch_size=4,max_optimizer_steps=2)
    raw=numerical._model(dict(dimension=384),codec,dict(seed=2026,projection_width=2,hidden_size=8,token_embedding_dim=16))
    for name,p in raw.named_parameters():
        if name.startswith(('projection_down.','projection_up.')):p.requires_grad_(False)
    base=conditioning.bind_persistent_model(raw,dimension=384,conditioning='every_step')
    with monkeypatch.context() as patch:
        patch.setattr(action_fixtures,'sources',lambda **kw:(base,train,tune,options,contexts))
        donor,*_=action_fixtures.actual_fixture()
    model=recurrent.bind_ordered_clause_recurrent_model(donor,codec=codec)
    extra_rows=[dict(row,target_ids=ref['target_ids']) for row,ref in zip(prepared['mixture']['source_inputs']['rows'],prepared['mixture']['corpus']['references'])]
    extra_refs=prepared['mixture']['corpus']['references'];extra_ctx=prepared['mixture']['source_inputs']['source_contexts']
    seen=[]
    def prepare(training_rows,validation_rows,**kwargs):
        assert training_rows==train and validation_rows==tune
        assert kwargs['source_contexts']==contexts and kwargs['training_references']==references['train']
        seen.append(kwargs)
        return mixture.Selector(train,train+extra_rows,references['train']+extra_refs,
            dict(contexts['train'],**extra_ctx),extra_refs,dict(schema=mixture.SCHEMA,policy=kwargs['mixture']['policy']))
    monkeypatch.setattr(mixture,'prepare',prepare)
    return model,train,tune,options,contexts,seen


def boundary(monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import contextual_generated_boundary_training as owner
    seen=[]
    def collect(model,rows,**kwargs):
        assert all(set(r)=={'id','source_text','input'} for r in rows)
        assert set(kwargs['source_contexts'])=={r['id'] for r in rows}
        assert 'training_references' not in kwargs and 'training_counts_by_id' not in kwargs
        seen.append(dict(rows=deepcopy(rows),contexts=deepcopy(kwargs['source_contexts'])))
        return dict(rows=rows)
    def loss(torch,model,collection,counts,**kwargs):
        assert all(r['id'] in counts for r in collection['rows'])
        parameter=next(p for p in model.parameters() if p.requires_grad)
        value=parameter.square().mean()+.125
        return dict(loss=value,receipt=dict(mean_loss=float(value.detach()),row_ids=[r['id'] for r in collection['rows']]))
    monkeypatch.setattr(owner,'collect_source_boundary_prefixes',collect)
    monkeypatch.setattr(owner,'generated_boundary_loss',loss)
    return seen


def fit(args,**extra):
    model,train,tune,options,contexts,*_=args
    return integration.fit(model,train,tune,options,contexts,generated_boundary_retry_on_mismatch=True,**extra)


def test_none_default_never_imports_or_prepares(monkeypatch):
    args=fixture(monkeypatch);boundary(monkeypatch)
    monkeypatch.setitem(sys.modules,package.__name__+'.contextual_training_mixture',None)
    a=fit(args);b=fit(args,source_training_mixture=None,training_deadline=None)
    integration.same(a,b)
    assert not any(k.startswith('source_training_mixture') for k in b['report'])


def test_none_replays_published_preimage_exactly(monkeypatch,tmp_path):
    """A pinned historical source comparison, separate from omitted/explicitNone."""
    root=Path(__file__).resolve().parents[5]
    relative='ipfs_datasets_py/logic/formalization/autoencoder/long_span_source_value_training.py'
    captured=subprocess.run(['git','show','fd89d2a48aa0de771dd22ec8fd079af10732051f:'+relative],
        cwd=root,capture_output=True,check=False)
    if captured.returncode:
        pytest.skip('pinned published Git object unavailable; historical replay not executed')
    assert hashlib.sha256(captured.stdout).hexdigest()=='21f300fbc969c2b34be355b633c46a616d83d451207cc5f3bd56537d40bd0498'
    path=tmp_path/'published_trainer.py';path.write_bytes(captured.stdout)
    spec=importlib.util.spec_from_file_location(package.__name__+'._mixture_published_trainer',path)
    old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    args=fixture(monkeypatch);boundary(monkeypatch)
    model,train,tune,options,contexts,_=args
    baseline=old.train(model,train,tune,source_contexts=contexts,source_value_weight=.25,
        cardinality_weight=.25,count_exposure='balanced_all',action_contrastive_weight=.05,
        non_action_learning_rate_multiplier=10.,generated_boundary_weight=.05,
        generated_boundary_retry_on_mismatch=True,**options)
    actual=fit(args)
    integration.same(baseline,actual)


def test_identity_exact_states_predictions_rng_updates_and_selection(monkeypatch):
    args=fixture(monkeypatch);boundary(monkeypatch);rng=torch.random.get_rng_state().clone()
    a=fit(args);b=fit(args,source_training_mixture={'policy':'original_only'})
    assert torch.equal(rng,torch.random.get_rng_state())
    for role in ('state_dict','last_complete_attempt_state_dict'):
        assert all(torch.equal(v,b[role][n]) for n,v in a[role].items())
    for name in ('predictions','last_complete_attempt_predictions'):assert a[name]==b[name]
    for name in ('history','selected_epoch','selection','gradient_norms','committed_decoder_batch_ids_sha256','committed_count_batch_ids_sha256'):
        assert a['report'][name]==b['report'][name]
    for left,right in zip(a['report']['committed_updates'],b['report']['committed_updates']):
        right=deepcopy(right);right.pop('source_training_mixture');right.pop('decoder_parent_row_ids')
        left=deepcopy(left)
        left['action_contrastive'].pop('inventory_sha256');right['action_contrastive'].pop('inventory_sha256')
        assert left==right
    assert b['report']['source_training_mixture']['final']['committed_replacements']==0


def test_replacement_reaches_every_ordinary_loss_while_count_aux_and_buffers_remain_original(monkeypatch):
    args=fixture(monkeypatch);seen=boundary(monkeypatch);aux=integration.fake_auxiliary(monkeypatch)
    model,train,tune,options,contexts,_=args;before=core.tensor_digest(model);buffers={n:b.clone() for n,b in model.named_buffers()}
    result=fit(args,source_training_mixture={'policy':'half_paraphrases'},auxiliary_source_modality_weight=.05,
        auxiliary_source_modality_bank={'synthetic_training_bank':True})
    report=result['report'];assert report['optimizer_steps']==2
    assert aux['bindings']==[(train,tune,contexts,options['codec'])]
    assert core.tensor_digest(model)==before
    assert report['source_training_mixture']['final']['committed_replacements']==3
    assert not report['source_training_mixture_preprocessing_refitted']
    assert 'effective TRAIN' in report['source_context_training_policy']
    for n,b in buffers.items():
        assert torch.equal(b,result['state_dict'][n]) and torch.equal(b,result['last_complete_attempt_state_dict'][n])
    for index,(u,call) in enumerate(zip(report['committed_updates'],seen)):
        assert set(u['count_row_ids'])<={r['id'] for r in train}
        assert u['decoder_row_ids']==[r['id'] for r in call['rows']]==u['action_contrastive']['row_ids']
        assert set(call['contexts'])==set(u['decoder_row_ids'])
        assert all(i.startswith('authored-training-v1:') for i in u['decoder_row_ids']) if index else all(i.startswith('train-') for i in u['decoder_row_ids'])
        expected=u['weighted_token_ce']+.25*u['count_ce']+.25*u['source_value_ce']
        expected+=report['config']['reconstruction_weight']*u['raw_reconstruction_mse']
        expected+=.05*(u['action_contrastive']['loss'] or 0)+.05*u['generated_boundary']['mean_loss']
        expected+=u['auxiliary_source_modality']['weighted_loss']
        assert u['objective']==pytest.approx(expected,abs=2e-6)
        assert u['source_value_presentations']==u['source_training_mixture']['source_value_presentations']==12
        assert u['target_token_presentations']==u['source_training_mixture']['target_token_presentations']==117


@pytest.mark.parametrize('bad',[True,float('nan'),float('inf'),'soon'])
def test_invalid_absolute_deadline_refused_before_copy(monkeypatch,bad):
    args=fixture(monkeypatch)
    monkeypatch.setattr(trainer,'deepcopy',lambda *a:pytest.fail('private model copied'))
    with pytest.raises(ValueError,match='absolute training deadline'):fit(args,training_deadline=bad)


def test_expired_absolute_deadline_or_prepare_cannot_allocate_private_model(monkeypatch):
    args=fixture(monkeypatch)
    monkeypatch.setattr(trainer,'deepcopy',lambda *a:pytest.fail('private model copied'))
    with pytest.raises(TimeoutError):fit(args,training_deadline=time.monotonic()-1)
    monkeypatch.setattr(mixture,'prepare',lambda *a,**kw:(_ for _ in ()).throw(TimeoutError('prepare')))
    with pytest.raises(TimeoutError):fit(args,source_training_mixture={'policy':'half_paraphrases'})


def test_expired_selection_cannot_commit_update(monkeypatch):
    args=fixture(monkeypatch);boundary(monkeypatch)
    monkeypatch.setattr(mixture.Selector,'select',lambda *a,**kw:(_ for _ in ()).throw(TimeoutError('selection')))
    monkeypatch.setattr(torch.optim.AdamW,'step',lambda *a,**kw:pytest.fail('expired work committed'))
    result=fit(args,source_training_mixture={'policy':'half_paraphrases'})
    assert result['report']['optimizer_steps']==0
    assert result['report']['stopped_reason']=='deadline_during_training_mixture_selection'
    assert result['report']['source_training_mixture']['final']['committed_rows']==0


def test_deadline_expiring_during_private_copy_never_constructs_optimizer(monkeypatch):
    args=fixture(monkeypatch);clock=[time.monotonic()];real_copy=trainer.deepcopy
    monkeypatch.setattr(trainer,'time',SimpleNamespace(monotonic=lambda:clock[0]))
    def copying(value):
        result=real_copy(value)
        if isinstance(value,torch.nn.Module):clock[0]+=100
        return result
    monkeypatch.setattr(trainer,'deepcopy',copying)
    monkeypatch.setattr(torch.optim,'AdamW',lambda *a,**kw:pytest.fail('optimizer created after expired copy'))
    with pytest.raises(TimeoutError,match='during private model copy'):
        fit(args,training_deadline=clock[0]+30)


def test_expired_backward_records_draw_without_committed_training(monkeypatch):
    args=fixture(monkeypatch);boundary(monkeypatch);clock=[time.monotonic()]
    monkeypatch.setattr(trainer,'time',SimpleNamespace(monotonic=lambda:clock[0]))
    integration.fake_auxiliary(monkeypatch,expire='backward',clock=clock)
    monkeypatch.setattr(torch.optim.AdamW,'step',lambda *a,**kw:pytest.fail('expired gradient committed'))
    result=fit(args,source_training_mixture={'policy':'half_paraphrases'},training_deadline=clock[0]+30,
        auxiliary_source_modality_weight=.05,auxiliary_source_modality_bank={'synthetic_training_bank':True})
    report=result['report'];snapshot=report['source_training_mixture']['final']
    assert report['optimizer_steps']==report['row_presentations']==report['count_training_row_presentations']==0
    assert snapshot['draw_rows']==3 and snapshot['committed_rows']==0 and snapshot['uncommitted_draw'] is not None


@pytest.mark.parametrize('extra',[{'order_augmentation':{}},{'source_gradient_preconditioning':'identity'},
    {'generated_field_weight':.1},{'auxiliary_source_object_bank':{},'auxiliary_source_object_weight':.05}])
def test_unreviewed_mixture_combinations_refused(monkeypatch,extra):
    args=fixture(monkeypatch)
    monkeypatch.setattr(trainer,'deepcopy',lambda *a:pytest.fail('private model copied'))
    with pytest.raises(ValueError):fit(args,source_training_mixture={'policy':'half_paraphrases'},**extra)
