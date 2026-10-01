"""Two real Security objectives, exact source-role joins and partial recovery."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from .test_security_formula_decoder_v2 import expanded_checkpoint, parent_checkpoint
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import security_joint_training as api
from ipfs_datasets_py.logic.ir_core.identity import canonical_identity
from ipfs_datasets_py.logic.ir_core.provenance import SourceRef
from ipfs_datasets_py.logic.security_ir.cvefixes.schemas import CodeUnit
from ipfs_datasets_py.logic.security_ir.code_logic_projection import CodeLogicEvidence
from ipfs_datasets_py.logic.security_ir.code_program_derivation import derive_code_program
from ipfs_datasets_py.logic.software_verification.program import ProgramIR


def _samples():
    return [
        {'id':'joint-train','split':'train','source':'def f(value):\n    return value + 2\n'},
        {'id':'joint-validation','split':'validation','source':'def f(value):\n    first = value + 1\n    second = first * 2\n    return second + 3\n'},
        {'id':'joint-test','split':'test','source':'def f(value):\n    first = value - 2\n    second = first * 5\n    third = second + 4\n    return third * 7\n'},
    ]


def _typed(sample):
    raw = sample['source'].encode()
    cid = canonical_identity({'fixture':'joint'},domain='authored',schema_version='v1').cid
    body_cid = canonical_identity({'body':raw.decode()},domain='cvefixes-security-ir/code-body',schema_version='cvefixes-code-body/v1').cid
    unit = CodeUnit(source_cids=(cid,),parent_cids=(cid,),config_cid=cid,unit_kind='symbol',language='Python',path=sample['id']+'.py',polarity='fixed',
        payload={'body_sha256':hashlib.sha256(raw).hexdigest(),'body_cid':body_cid})
    derived = derive_code_program(code_unit=unit,source_bytes=raw)
    assert derived['status']=='derived', derived
    document = ProgramIR.from_dict(derived['projection']['targets'][0]['native_document'])
    return {'sample_id':sample['id'],'group_id':sample['id']+'-application','split':sample['split'],
        'code_unit':unit,'source_bytes':raw,'typed_inputs':[CodeLogicEvidence(document,document.sources[0])]}


def _arguments(parent, output):
    samples = _samples()
    return dict(source_samples=samples,parent_source_checkpoint=parent,family_training_inputs=[_typed(samples[0])],
        family_validation_inputs=[_typed(samples[1])],output_dir=output,
        source_settings={'epochs':1,'max_seconds':60},family_settings={'epochs':1,'latent_width':2,'max_seconds':60})


@pytest.fixture(scope='module')
def completed(expanded_checkpoint,tmp_path_factory):
    arguments = _arguments(expanded_checkpoint,tmp_path_factory.mktemp('joint')/'complete')
    return api.train_security_joint_autoencoder(**arguments)


def test_default_runs_both_actual_objectives_with_source_bound_native_targets(completed):
    report=completed['report']
    assert report['status']=='complete',report.get('family_error')
    assert report['source_stage']==report['family_stage']=='complete'
    assert report['both_objectives_executed'] is True
    assert report['source_optimizer_steps']>0 and report['family_training_report']['optimizer_steps']>0
    assert report['family_training_report']['trained_logic_families']==['program']
    assert report['family_training_report']['frontier']  # Other families lack supplied models.
    assert report['objectives_share_source_splits'] and not report['objectives_share_weights']
    assert report['source_descriptor']['schema']!=report['family_descriptor']['schema']
    assert api._load(completed['descriptor'])==report
    source=api.production.decode_security_formula_continuation(source_bytes=_samples()[0]['source'].encode(),
        checkpoint=report['source_descriptor'],source_path='joint.py')
    assert source['status']=='candidate'
    assert not report['source_semantics_verified'] and not report['security_specification_inferred']


@pytest.mark.parametrize('mutation',['role','bytes','id','group','unit'])
def test_family_relabeling_or_unbound_source_stops_before_optimization(expanded_checkpoint,tmp_path,monkeypatch,mutation):
    args=_arguments(expanded_checkpoint,tmp_path/'bad')
    row=args['family_training_inputs'][0]
    if mutation=='role': row['split']='validation'
    elif mutation=='bytes': row['source_bytes']+=b'\n'
    elif mutation=='id': row['sample_id']='joint-validation'
    elif mutation=='group': row['group_id']=args['family_validation_inputs'][0]['group_id']
    elif mutation=='unit': row['code_unit']=args['family_validation_inputs'][0]['code_unit']
    monkeypatch.setattr(api.production,'train_security_formula_decoder_continuation',lambda **kw:pytest.fail('invalid rows reached optimizer'))
    with pytest.raises(ValueError,match='split|bytes|binding'):
        api.train_security_joint_autoencoder(**args)
    assert not (tmp_path/'bad').exists()


def test_family_fit_failure_retains_complete_source_stage(expanded_checkpoint,tmp_path,monkeypatch):
    args=_arguments(expanded_checkpoint,tmp_path/'partial')
    def failed(*a,**kw): raise RuntimeError('deliberate family-stage failure')
    monkeypatch.setattr(api.families,'train_family_projection_autoencoder',failed)
    result=api.train_security_joint_autoencoder(**args)
    report=result['report']
    assert report['status']=='partial' and report['source_stage']=='complete' and report['family_stage']=='failed'
    assert report['family_descriptor'] is None and not report['both_objectives_executed']
    assert report['family_error']=={'type':'RuntimeError','message':'deliberate family-stage failure'}
    assert api.production.load_security_formula_decoder_continuation(report['source_descriptor'])
    assert api._load(result['descriptor'])==report
    assert json.loads((tmp_path/'partial/receipt.json').read_bytes())==report
    assert (tmp_path/'partial/family_targets.json').is_file()


def test_mixed_parent_histories_are_rejected_before_fit(completed,expanded_checkpoint,tmp_path,monkeypatch):
    args=_arguments(expanded_checkpoint,tmp_path/'wrong-parent')
    args['parent_descriptor']=completed['descriptor']
    monkeypatch.setattr(api.production,'train_security_formula_decoder_continuation',lambda **kw:pytest.fail('mixed history reached optimizer'))
    with pytest.raises(ValueError,match='parent histories'):
        api.train_security_joint_autoencoder(**args)


def test_actual_joint_continuation_keeps_parent_bytes_and_group_history(completed,tmp_path):
    parent=Path(completed['descriptor']['path']).parent
    before={str(path.relative_to(parent)):path.read_bytes() for path in parent.rglob('*') if path.is_file()}
    args=_arguments(completed['report']['source_descriptor'],tmp_path/'child')
    args['parent_descriptor']=completed['descriptor']
    result=api.train_security_joint_autoencoder(**args)
    assert result['report']['status']=='complete',result['report'].get('family_error')
    assert result['report']['family_training_report']['initialization']=='complete_parent_structural_head'
    assert result['report']['training_history']==completed['report']['training_history']
    assert before=={str(path.relative_to(parent)):path.read_bytes() for path in parent.rglob('*') if path.is_file()}


def test_missing_typed_evidence_is_rejected_before_either_optimizer(expanded_checkpoint,tmp_path,monkeypatch):
    args=_arguments(expanded_checkpoint,tmp_path/'missing-evidence')
    args['family_training_inputs'][0]['typed_inputs']=[]
    monkeypatch.setattr(api.production,'train_security_formula_decoder_continuation',lambda **kw:pytest.fail('missing targets reached source optimizer'))
    monkeypatch.setattr(api.families,'train_family_projection_autoencoder',lambda *a,**kw:pytest.fail('missing targets reached family optimizer'))
    with pytest.raises(ValueError,match='ready native typed projection'):
        api.train_security_joint_autoencoder(**args)
    assert not args['output_dir'].exists()


def test_test_source_cannot_be_relabelled_for_family_validation(expanded_checkpoint,tmp_path,monkeypatch):
    args=_arguments(expanded_checkpoint,tmp_path/'leaked-test')
    row=_typed(_samples()[2]); row['split']='validation'
    args['family_validation_inputs']=[row]
    monkeypatch.setattr(api.production,'train_security_formula_decoder_continuation',lambda **kw:pytest.fail('test target reached optimizer'))
    with pytest.raises(ValueError,match='split role'):
        api.train_security_joint_autoencoder(**args)
    assert not args['output_dir'].exists()


def test_composite_target_artifact_tampering_is_rejected(completed,tmp_path):
    import shutil
    parent=Path(completed['descriptor']['path']).parent
    copied=tmp_path/'copied'; shutil.copytree(parent,copied)
    descriptor=deepcopy(completed['descriptor']); descriptor['path']=str(copied/'receipt.json')
    target=copied/'family_targets.json';target.write_bytes(target.read_bytes()+b' ')
    with pytest.raises(ValueError,match='target receipt drift'):
        api._load(descriptor)
