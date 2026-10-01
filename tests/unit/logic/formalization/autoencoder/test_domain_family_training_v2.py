"""Actual three-domain numerical training and immutable split/source recipes."""
from copy import deepcopy
from pathlib import Path

import pytest

from .test_security_joint_training import _samples, _typed
from .test_security_formula_decoder_v2 import expanded_checkpoint, parent_checkpoint
from .test_ui_training_inputs import native_row
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_family_training_v2 as api
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalRoundTripIR, CanonicalRule


def _ui(index,split):
    row=native_row(index,group_id='application:'+str(index),split=split)
    return {'source_id':row['provenance']['row_id'],'group_id':row['provenance']['group_id'],
        'split':split,'inputs':{'ui_training_row':row}}


def _legal(index,split):
    text=f'Agency must publish notice {index}.'
    document=CanonicalRoundTripIR((CanonicalRule('O','Agency','publish',f'notice {index}'),))
    return {'source_id':f'law:{index}','group_id':f'code:{index}','split':split,
        'inputs':{'document':document,'source_text':text}}


def _security(sample):
    old=_typed(sample)
    return {'source_id':old['sample_id'],'group_id':old['group_id'],'split':old['split'],
        'inputs':{key:old[key] for key in ('code_unit','source_bytes','typed_inputs')}}


def _rows(domain):
    if domain=='security_ir':
        samples=_samples();return [_security(samples[0])],[_security(samples[1])],[_security(samples[2])]
    factory=_ui if domain=='ui_ux_ir' else _legal
    return [factory(i,'train') for i in (1,2)],[factory(i,'validation') for i in (3,4)],[factory(5,'test')]


def _fit(domain,path,**extra):
    train,validation,_=_rows(domain)
    return api.train_domain_family_autoencoder_v2(domain,train,validation,output_dir=path,
        epochs=2,latent_width=2,minibatch_size=1,max_seconds=60,**extra)


@pytest.mark.parametrize('domain',sorted(api.DOMAINS))
def test_actual_native_three_domain_training_and_saved_inference(domain,tmp_path):
    result=_fit(domain,tmp_path/domain)
    report=result['report'];assert report['status']=='complete',report['family_error']
    assert report['family_training_report']['training_executed']
    assert report['family_training_report']['decoder_calibration']['status']=='executed'
    assert report['family_training_report']['optimizer_steps']>0
    assert not report['source_model_reinitialized']
    assert not report['test_used_for_fit_or_selection']
    assert report['source_stage']=='not_requested'
    assert api._read(result['descriptor'])==report
    before=Path(report['family_descriptor']['path']).read_bytes()
    inferred=api.infer_domain_family_autoencoder_v2(result['descriptor'],_rows(domain)[2])
    assert inferred['training_steps']==0 and not inferred['formulas_generated'] and not inferred['source_text_decoded']
    assert len(inferred['native_inference']['latent'])==1
    assert before==Path(report['family_descriptor']['path']).read_bytes()
    if domain=='ui_ux_ir':
        assert len(report['family_training_report']['trained_logic_families'])>=4


def test_actual_security_two_stage_recipe_inherits_source_weights(expanded_checkpoint,tmp_path):
    training,validation,_=_rows('security_ir')
    result=api.train_security_joint_autoencoder_v2(training,validation,source_samples=_samples(),
        parent_source_checkpoint=expanded_checkpoint,source_settings={'epochs':1,'max_seconds':60},
        output_dir=tmp_path/'joint',epochs=1,latent_width=2,max_seconds=60)
    report=result['report'];assert report['status']=='complete',report['family_error']
    assert report['source_stage']=='complete' and report['source_optimizer_steps']>0
    source=api.source_decoder.load_security_formula_decoder_continuation(report['source_descriptor'])
    parent=api.source_decoder._parent(expanded_checkpoint)
    assert source['training']['initial_parameters_sha256']==api.source_decoder._sha(api.source_decoder._json(parent['weights']['parameters']))
    assert source['weights']['lexical']==parent['weights']['lexical']
    assert report['family_descriptor']['schema']!=report['source_descriptor']['schema']


@pytest.mark.parametrize('domain',sorted(api.DOMAINS))
def test_group_source_content_and_test_roles_cannot_leak(domain,tmp_path,monkeypatch):
    training,validation,_=_rows(domain)
    validation[0]['group_id']=training[0]['group_id']
    if domain=='ui_ux_ir':validation[0]['inputs']['ui_training_row']['provenance']['group_id']=training[0]['group_id']
    monkeypatch.setattr(api.numerical,'train_family_projection_autoencoder_v2',lambda *a,**kw:pytest.fail('leak reached fitter'))
    with pytest.raises(ValueError,match='leakage'):
        api.train_domain_family_autoencoder_v2(domain,training,validation,output_dir=tmp_path/'leaked')
    assert not (tmp_path/'leaked').exists()
    training,validation,_=_rows(domain);training[0]['split']='test'
    with pytest.raises(ValueError,match='test/canary'):
        api.train_domain_family_autoencoder_v2(domain,training,validation,output_dir=tmp_path/'test-data')


def test_ui_native_provenance_cannot_be_relabelled(tmp_path):
    training,validation,_=_rows('ui_ux_ir');training[0]['source_id']='made-up'
    with pytest.raises(ValueError,match='cannot relabel'):
        api.train_domain_family_autoencoder_v2('ui_ux_ir',training,validation,output_dir=tmp_path/'bad')


def test_legal_same_text_with_fresh_ids_still_leaks(tmp_path):
    training,validation,_=_rows('legal_ir')
    validation[0]['inputs']['source_text']=training[0]['inputs']['source_text']
    with pytest.raises(ValueError,match='source_content_sha256 leakage'):
        api.train_domain_family_autoencoder_v2('legal_ir',training,validation,output_dir=tmp_path/'bad')


def test_security_test_source_cannot_enter_family_validation(expanded_checkpoint,tmp_path,monkeypatch):
    training,validation,test=_rows('security_ir');test[0]['split']='validation'
    monkeypatch.setattr(api.source_decoder,'train_security_formula_decoder_continuation',lambda **kw:pytest.fail('heldout source reached fit'))
    with pytest.raises(ValueError,match='hash or split role differs'):
        api.train_security_joint_autoencoder_v2(training,test,source_samples=_samples(),parent_source_checkpoint=expanded_checkpoint,output_dir=tmp_path/'bad')
    assert not (tmp_path/'bad').exists()


def test_missing_typed_targets_reject_before_source_stage(expanded_checkpoint,tmp_path,monkeypatch):
    training,validation,_=_rows('security_ir');training[0]['inputs']['typed_inputs']=[]
    monkeypatch.setattr(api.source_decoder,'train_security_formula_decoder_continuation',lambda **kw:pytest.fail('unready target reached source fit'))
    with pytest.raises(ValueError,match='ready actual native target'):
        api.train_security_joint_autoencoder_v2(training,validation,source_samples=_samples(),parent_source_checkpoint=expanded_checkpoint,output_dir=tmp_path/'bad')


def test_family_failure_preserves_actual_source_checkpoint(expanded_checkpoint,tmp_path,monkeypatch):
    training,validation,_=_rows('security_ir')
    def fail(*a,**kw):raise RuntimeError('family training failed')
    monkeypatch.setattr(api.numerical,'train_family_projection_autoencoder_v2',fail)
    result=api.train_security_joint_autoencoder_v2(training,validation,source_samples=_samples(),parent_source_checkpoint=expanded_checkpoint,
        output_dir=tmp_path/'partial',source_settings={'epochs':1,'max_seconds':60})
    report=result['report'];assert report['status']=='partial' and report['family_stage']=='failed'
    assert report['source_stage']=='complete' and report['family_descriptor'] is None
    assert report['family_error']=={'type':'RuntimeError','message':'family training failed'}
    assert api.source_decoder.load_security_formula_decoder_continuation(report['source_descriptor'])
    assert api._read(result['descriptor'])==report


def test_actual_resume_keeps_historical_groups_and_parent(tmp_path):
    parent=_fit('legal_ir',tmp_path/'parent')
    before=Path(parent['report']['family_descriptor']['path']).read_bytes()
    child=_fit('legal_ir',tmp_path/'child',parent_descriptor=parent['descriptor'])
    assert child['report']['status']=='complete',child['report']['family_error']
    assert child['report']['family_training_report']['initialization']=='complete_parent_structural_head'
    assert child['report']['training_history']==parent['report']['training_history']
    assert before==Path(parent['report']['family_descriptor']['path']).read_bytes()
    training,validation,_=_rows('legal_ir');validation[0]=_legal(99,'validation')
    with pytest.raises(ValueError,match='fixed domain validation'):
        api.train_domain_family_autoencoder_v2('legal_ir',training,validation,parent_descriptor=parent['descriptor'],output_dir=tmp_path/'changed')


def test_target_tampering_rejected(tmp_path):
    result=_fit('legal_ir',tmp_path/'tamper')
    path=tmp_path/'tamper/targets.json';path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(ValueError,match='target artifact drift'):
        api._read(result['descriptor'])
