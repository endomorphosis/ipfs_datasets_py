"""Exact arithmetic, provenance and continuation for prepared native heads."""
import copy
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training as codec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training_v2 as reference
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training_prepared as api
from ipfs_datasets_py.logic.formalization.autoencoder.family_training import prepare_family_training_targets
from ipfs_datasets_py.logic.intent_ir.formalize.rich_grammar import parse_instruction


def target(text):
    return prepare_family_training_targets('intent_ir', document=parse_instruction(text), source_text=text,
        requested_families=['deontic', 'dcec', 'tdfol', 'frame_logic'])


@pytest.fixture
def corpus():
    return ([target(f'The {actor} {modal} {action} the {name}.') for actor,modal,action,name in
             [('agent','must','save','record'),('reviewer','may','view','report'),
              ('officer','must','submit','file'),('agent','must','save','message')]],
            [target('The auditor must save the validationunique record.')])


def comparable(report):
    return {k:v for k,v in report.items() if k not in ('schema','elapsed_seconds','prepared_execution','parent_descriptor')}


@pytest.mark.parametrize('value', [None, True, False, 1, 0, 1., 0., -0., 'a_B <= 3 α',
    {'b':[False,0,None,-0.0,0.0], 'a':{'nested':['token x','token y']}}])
def test_atom_cache_exact_typed_atoms(value):
    atoms, info = api._atom_encoder()
    # Populate numeric collisions first, including signed zero.
    for previous in [True,1,1.,False,0,0.,-0.]:
        assert list(atoms(previous)) == list(codec._atoms(previous))
    assert list(atoms(value)) == list(codec._atoms(value))
    assert list(atoms(value)) == list(codec._atoms(value))
    assert info().currsize <= 8192


def test_atom_cache_bound_and_depth():
    atoms, info = api._atom_encoder()
    list(atoms([f'unique_{i}' for i in range(9000)]))
    assert info().currsize == 8192
    nested = 0
    for _ in range(34): nested = [nested]
    with pytest.raises(ValueError, match='depth'): list(atoms(nested))


@pytest.mark.parametrize('seed', range(6))
def test_masked_objective_and_full_gradients_exact(seed):
    import torch
    gen=torch.Generator().manual_seed(seed)
    descriptors={'a':{'logic_family':'fol'},'b':{'logic_family':'temporal'},
                 'c':{'logic_family':'fol'},'d':{'logic_family':'rare'}}
    spans={'a':(0,2),'b':(2,5),'c':(5,6),'d':(6,8)}
    mask=torch.rand((5,4),generator=gen)>.4
    mask[:,3]=False  # rare projection contributes denominator even when absent
    mask[0,0]=True
    target_=torch.randn((5,8),generator=gen,dtype=torch.float64)
    one=torch.randn((5,8),generator=gen,dtype=torch.float64,requires_grad=True)
    two=one.detach().clone().requires_grad_()
    population=(30,[20.,15.,25.,2.])
    expected,_=codec._objective(torch,one,target_,mask,spans,descriptors,population=population)
    actual=api._PreparedObjective(torch,target_,mask,spans,descriptors,population)(two)
    expected.backward(); actual.backward()
    assert torch.equal(expected,actual)
    assert torch.equal(one.grad,two.grad)


@pytest.mark.parametrize('denoising',[0.,.05])
def test_native_v2_parameters_history_inference_and_continuation_exact(tmp_path,corpus,denoising):
    training, validation=corpus
    settings=dict(epochs=4,latent_width=3,minibatch_size=3,denoising=denoising,patience=4)
    old=reference.train_family_projection_autoencoder_v2(training,validation,output_dir=tmp_path/'old',**settings)
    new=api.train_family_projection_autoencoder_prepared(training,validation,output_dir=tmp_path/'new',**settings)
    assert comparable(new['report']) == comparable(old['report'])
    old_saved,_=reference._read(old['descriptor']); new_saved,_=api._read(new['descriptor'])
    assert new_saved['parameters'] == old_saved['parameters']
    assert new_saved['space'] == old_saved['space']
    assert new['report']['prepared_execution']['atom_cache']['hits'] > 0
    a=reference.infer_family_projection_autoencoder_v2(old['descriptor'],validation)
    b=api.infer_family_projection_autoencoder_prepared(new['descriptor'],validation)
    assert {k:v for k,v in a.items() if k not in ('schema','checkpoint_sha256')} == \
           {k:v for k,v in b.items() if k not in ('schema','checkpoint_sha256')}
    raw=Path(old['descriptor']['path']).read_bytes()
    nextold=reference.train_family_projection_autoencoder_v2(training,validation,output_dir=tmp_path/'old-next',parent_descriptor=old['descriptor'],**settings)
    nextnew=api.train_family_projection_autoencoder_prepared(training,validation,output_dir=tmp_path/'new-next',parent_descriptor=new['descriptor'],**settings)
    assert comparable(nextnew['report']) == comparable(nextold['report'])
    assert api._read(nextnew['descriptor'])[0]['parameters'] == reference._read(nextold['descriptor'])[0]['parameters']
    assert Path(old['descriptor']['path']).read_bytes() == raw
    # Explicit old-parent import uses its complete unchanged numerical state.
    inherited=api.train_family_projection_autoencoder_prepared(training,validation,output_dir=tmp_path/'inherited',parent_descriptor=old['descriptor'],**settings)
    assert api._read(inherited['descriptor'])[0]['parameters'] == api._read(nextnew['descriptor'])[0]['parameters']
    assert all(new['report'][key] is False for key in api.FALSE)


def test_source_overlap_rejected_before_output(tmp_path,corpus):
    training,_=corpus
    with pytest.raises(ValueError,match='source leakage'):
        api.train_family_projection_autoencoder_prepared(training,training,output_dir=tmp_path/'bad')
    assert not (tmp_path/'bad').exists()


def test_source_drift_since_import_rejected_before_training(tmp_path,corpus,monkeypatch):
    training,validation=corpus
    current=api._implementation()
    monkeypatch.setattr(api,'_implementation',lambda:{**current,'trainer':'0'*64})
    with pytest.raises(ValueError,match='changed since import'):
        api.train_family_projection_autoencoder_prepared(training,validation,output_dir=tmp_path/'bad')
    assert not (tmp_path/'bad').exists()


def test_inputs_mutated_during_training_rejected_before_publication(tmp_path,corpus,monkeypatch):
    training,validation=copy.deepcopy(corpus)
    calibrate=api._calibrate_decoder
    def mutate(*args,**kwargs):
        result=calibrate(*args,**kwargs)
        training[0]['unexpected_mutation']=True
        return result
    monkeypatch.setattr(api,'_calibrate_decoder',mutate)
    with pytest.raises(ValueError,match='inputs changed'):
        api.train_family_projection_autoencoder_prepared(training,validation,output_dir=tmp_path/'bad',epochs=1,latent_width=2)
    assert not (tmp_path/'bad').exists()


def test_expired_calibration_retains_initializer(tmp_path,corpus,monkeypatch):
    training,validation=corpus
    clock=[0.]
    calibrate=api._calibrate_decoder
    def expire(*args,**kwargs):
        result=calibrate(*args,**kwargs);clock[0]=121.;return result
    monkeypatch.setattr(api.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(api,'_calibrate_decoder',expire)
    result=api.train_family_projection_autoencoder_prepared(training,validation,output_dir=tmp_path/'late',epochs=1,latent_width=2,max_seconds=120)
    report=result['report']
    assert report['optimizer_steps']==0
    assert report['initial_parameters_sha256']==report['selected_parameters_sha256']
    assert report['decoder_calibration']['status']=='discarded_due_deadline'
    assert report['stopping']=='deadline'


def test_tampered_weights_rejected(tmp_path,corpus):
    result=api.train_family_projection_autoencoder_prepared(*corpus,output_dir=tmp_path/'model',epochs=1,latent_width=2)
    path=Path(result['descriptor']['path']);saved=json.loads(path.read_text())
    saved['parameters'][0][0][0]+=1
    raw=api._raw(saved);path.write_bytes(raw)
    with pytest.raises(ValueError,match='parameter identity'):
        api._read({**result['descriptor'],'sha256':api._sha(raw)})
