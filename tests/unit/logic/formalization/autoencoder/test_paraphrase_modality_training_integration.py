"""Opt-in auxiliary preserves default math and original streams; tiny CPU fixtures."""
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest
torch=pytest.importorskip('torch')
from ipfs_datasets_py.logic.formalization import autoencoder as package
from ipfs_datasets_py.logic.formalization.autoencoder import long_span_source_value_training as trainer
from ipfs_datasets_py.logic.formalization.autoencoder import paraphrase_modality_auxiliary_training as auxiliary
from . import test_contextual_training_mixture_integration as tiny
from . import test_source_modality_training_integration as inherited
from .test_paraphrase_modality_auxiliary_training import bank_fixture,prepare


@pytest.fixture(autouse=True)
def cpu():
    old=torch.get_num_threads();torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


def fixture(monkeypatch):
    bank=prepare(bank_fixture(monkeypatch));args=tiny.fixture(monkeypatch);tiny.boundary(monkeypatch)
    seen=[]
    def prepare_bank(train,dev,**kwargs):
        assert train==args[1] and dev==args[2] and kwargs['source_contexts']==args[4]
        assert kwargs['training_references']==args[3]['training_references']
        assert kwargs['validation_references']==args[3]['validation_references']
        seen.append(1);return deepcopy(bank)
    monkeypatch.setattr(auxiliary,'prepare_bank',prepare_bank)
    return args,seen


def fit(args,weight=None,**kwargs):
    if weight is not None:kwargs['paraphrase_modality_auxiliary']=dict(source_inventory={'synthetic':True},weight=weight)
    return tiny.fit(args,**kwargs)


def compare_numerical(a,b):
    for role in ('state_dict','last_complete_attempt_state_dict'):
        assert all(torch.equal(t,b[role][n]) for n,t in a[role].items())
    assert a['predictions']==b['predictions'] and a['last_complete_attempt_predictions']==b['last_complete_attempt_predictions']
    left,right=deepcopy(a['report']),deepcopy(b['report'])
    for report in (left,right):
        for k in ('elapsed_seconds','tensor_work_estimate_bytes','paraphrase_modality_auxiliary',
            'source_context_training_policy','source_value_training_row_policy'):report.pop(k,None)
        for update in report['committed_updates']:update.pop('paraphrase_modality_auxiliary',None)
    assert left==right


def test_default_none_no_helper_import_or_preparation(monkeypatch):
    args,seen=fixture(monkeypatch)
    monkeypatch.setitem(sys.modules,package.__name__+'.paraphrase_modality_auxiliary_training',None)
    a=fit(args);b=fit(args,paraphrase_modality_auxiliary=None)
    inherited.same(a,b);assert not seen and 'paraphrase_modality_auxiliary' not in a['report']


def test_default_replays_published_aa586_trainer(monkeypatch,tmp_path):
    root=Path(__file__).resolve().parents[5]
    relative='ipfs_datasets_py/logic/formalization/autoencoder/long_span_source_value_training.py'
    old=subprocess.run(['git','show','aa586a9b9:'+relative],cwd=root,capture_output=True,check=True).stdout
    assert hashlib.sha256(old).hexdigest()=='c7ac8153acc04926bc2200e1031970c428090bc2132f31cc937fbdebdec3478f'
    path=tmp_path/'published_trainer.py';path.write_bytes(old)
    spec=importlib.util.spec_from_file_location(package.__name__+'._paraphrase_published_trainer',path)
    previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)
    args,seen=fixture(monkeypatch);model,train,dev,options,contexts,*_=args
    before=previous.train(model,train,dev,source_contexts=contexts,source_value_weight=.25,
        cardinality_weight=.25,count_exposure='balanced_all',action_contrastive_weight=.05,
        non_action_learning_rate_multiplier=10.,generated_boundary_weight=.05,
        generated_boundary_retry_on_mismatch=True,**options)
    after=fit(args);inherited.same(before,after);assert not seen


def test_real_zero_forward_exact_baseline_rng_streams_and_buffers(monkeypatch):
    args,seen=fixture(monkeypatch);rng=torch.random.get_rng_state().clone()
    state={n:t.clone() for n,t in args[0].state_dict().items()}
    before=fit(args);zero=fit(args,0.)
    compare_numerical(before,zero);report=zero['report']['paraphrase_modality_auxiliary']
    assert len(seen)==1 and report['committed_clause_presentations']==report['observed_clause_presentations']==12
    assert report['positively_supervised_clause_presentations']==0 and not report['zero_weight_graph_attached']
    assert torch.equal(rng,torch.random.get_rng_state())
    assert all(torch.equal(t,state[n]) for n,t in args[0].state_dict().items())
    assert all(not u['paraphrase_modality_auxiliary']['receipt']['gradient_enabled'] for u in zero['report']['committed_updates'])


def test_positive_adds_exact_loss_keeps_original_consumers_and_existing_auxiliary(monkeypatch):
    args,seen=fixture(monkeypatch);old=inherited.fake_auxiliary(monkeypatch)
    result=fit(args,.05,auxiliary_source_modality_bank={'synthetic_training_bank':True},auxiliary_source_modality_weight=.05)
    report=result['report'];counts=report['paraphrase_modality_auxiliary']
    assert report['optimizer_steps']==2 and counts['positively_supervised_clause_presentations']==12
    assert old['steps']==[0,1] and counts['committed_presentations_per_modality']=={'O':4,'P':4,'F':4}
    assert all(v==6 for v in counts['committed_presentations_per_template'].values())
    for update in report['committed_updates']:
        assert set(update['decoder_row_ids'])==set(update['count_row_ids'])=={r['id'] for r in args[1]}
        assert update['action_contrastive']['row_ids']==update['decoder_row_ids']==update['generated_boundary']['row_ids']
        added=update['paraphrase_modality_auxiliary']
        assert added['receipt']['gradient_enabled'] and added['weighted_loss']==pytest.approx(.05*added['receipt']['mean_cross_entropy'])
        expected=update['weighted_token_ce']+.25*update['count_ce']+.25*update['source_value_ce']
        expected+=report['config']['reconstruction_weight']*update['raw_reconstruction_mse']
        expected+=.05*(update['action_contrastive']['loss'] or 0)+.05*update['generated_boundary']['mean_loss']
        expected+=update['auxiliary_source_modality']['weighted_loss']+added['weighted_loss']
        assert update['objective']==pytest.approx(expected,abs=2e-6)
    assert 'original paragraph contexts' in report['source_context_training_policy']


@pytest.mark.parametrize('bad',[{},True,{'source_inventory':{},'weight':True},{'source_inventory':{},'weight':.1},
    {'source_inventory':{},'weight':float('nan')},{'source_inventory':{},'weight':0,'extra':1}])
def test_invalid_closed_hook_refused_before_private_copy(monkeypatch,bad):
    args,seen=fixture(monkeypatch)
    monkeypatch.setattr(trainer,'deepcopy',lambda *a:pytest.fail('private copy made'))
    with pytest.raises(ValueError):fit(args,paraphrase_modality_auxiliary=bad)


@pytest.mark.parametrize('extra',[{'source_training_mixture':{}},{'source_gradient_preconditioning':'identity'},
    {'generated_field_weight':.1},{'auxiliary_source_object_bank':{},'auxiliary_source_object_weight':.05}])
def test_unreviewed_loss_combinations_refused(monkeypatch,extra):
    args,seen=fixture(monkeypatch)
    monkeypatch.setattr(trainer,'deepcopy',lambda *a:pytest.fail('private copy made'))
    with pytest.raises(ValueError):fit(args,0.,**extra)


def test_expired_bank_preparation_has_no_private_copy(monkeypatch):
    args,seen=fixture(monkeypatch)
    monkeypatch.setattr(auxiliary,'prepare_bank',lambda *a,**kw:(_ for _ in ()).throw(TimeoutError('bank preparation')))
    monkeypatch.setattr(trainer,'deepcopy',lambda *a:pytest.fail('private copy made'))
    with pytest.raises(TimeoutError):fit(args,0.)


@pytest.mark.parametrize('stage',['cache','forward','backward'])
def test_expiry_never_commits_update_and_reports_only_committed_exposure(monkeypatch,stage):
    args,seen=fixture(monkeypatch);clock=[time.monotonic()]
    monkeypatch.setattr(trainer,'time',SimpleNamespace(monotonic=lambda:clock[0]))
    monkeypatch.setattr(torch.optim.AdamW,'step',lambda *a,**kw:pytest.fail('expired work committed'))
    if stage=='cache':
        monkeypatch.setattr(auxiliary,'prepare_tensor_cache',lambda *a,**kw:(_ for _ in ()).throw(TimeoutError('cache')))
    elif stage=='forward':
        monkeypatch.setattr(auxiliary,'modality_loss',lambda *a,**kw:(_ for _ in ()).throw(TimeoutError('forward')))
    else:
        original=auxiliary.modality_loss
        def loss(*a,**kw):
            result=original(*a,**kw)
            def expire(gradient):clock[0]+=100.;return gradient
            result['loss'].register_hook(expire);return result
        monkeypatch.setattr(auxiliary,'modality_loss',loss)
    result=fit(args,.05,training_deadline=clock[0]+30)
    report=result['report'];aux=report['paraphrase_modality_auxiliary']
    assert report['optimizer_steps']==report['row_presentations']==aux['committed_clause_presentations']==0
    assert aux['positively_supervised_clause_presentations']==0
    assert aux['observed_clause_presentations']==(6 if stage=='backward' else 0)
    assert len(aux['uncommitted_observations'])==(1 if stage=='backward' else 0)
