"""Declared expanded-target bounds are enforced and owner-verified, without training."""
from dataclasses import replace
import hashlib
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.bridge.multiview import LegalIRTrainingTarget
from ipfs_datasets_py.logic.bridge.types import LegalIRDocument, LogicIRView
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_coordinator as owner
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_target_bundle as bundle
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_target_preparation import target_snapshot_config
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import ModalAutoencoderTrainingState


def job(tmp_path, **updates):
    parent=tmp_path/'parent.json'
    parent.write_text(ModalAutoencoderTrainingState().to_json())
    data=parent.read_bytes()
    raw=dict(job_id='controlled-job',run_id='controlled-run',base_version_id='controlled-parent',
        base_checkpoint={'path':str(parent),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)},
        output_directory=str(tmp_path/'output'),code_identity='controlled-source',
        dataset_snapshot_id='controlled-data',split_snapshot_id='controlled-split',
        samples=[{'title':'5','section':'1','text':'The agency shall retain records.'}],
        autoencoder_config={'compute_device':'python'})
    return worker.TrainingJobSpec.from_dict({**raw,**updates})


def with_target(tmp_path, *, shard_bound=64*1024*1024):
    base=job(tmp_path)
    sample=build_us_code_sample(**base.samples[0].__dict__)
    config=target_snapshot_config(base.training_config)
    document=LegalIRDocument(sample.sample_id,sample.text,sample.normalized_text,
        citation=sample.citation,views={'deontic.ir':LogicIRView('deontic.ir',{'rules':['retain(records)']})},
        metadata={'created_at':'controlled-fixture'})
    target=LegalIRTrainingTarget(config.bridge_names,document,
        {'legal_ir_multiview_total_loss':.25},{'deontic_norms':{'controlled':.25}}, {'deontic.ir':1.},False)
    artifact=bundle.write_target_bundle(tmp_path/'targets.bundle',[(sample,target,None)],config=config)
    spec=replace(base,target_snapshot_id=artifact['snapshot_id'],
        target_snapshot_artifact=worker.CheckpointArtifact.from_dict({key:artifact[key] for key in ('path','sha256','bytes')}),
        target_shard_max_bytes=shard_bound)
    return spec,artifact


def trainer(model,samples,*,validation_samples,**kwargs):
    assert kwargs['legal_ir_targets']
    return {'accepted_epochs':0,'after':{'legal_ir_target_count':len(samples)},'stopped_reason':'controlled_no_fit'}


def test_default_bound_preserves_archived_job_identity(tmp_path):
    default=job(tmp_path)
    assert default.target_shard_max_bytes==bundle.DEFAULT_MAX_SHARD_BYTES==64*1024*1024
    assert worker.MAX_TARGET_SHARD_BYTES==bundle.MAX_TARGET_SHARD_BYTES==256*1024*1024
    assert 'target_shard_max_bytes' not in default.to_dict()
    assert replace(default,target_shard_max_bytes=64*1024*1024).canonical_sha256==default.canonical_sha256
    assert worker.TrainingJobSpec.from_dict(default.to_dict()).canonical_sha256==default.canonical_sha256


@pytest.mark.parametrize('value',[0,-1,True,False,1.0,'67108864',None,256*1024*1024+1])
def test_bound_requires_positive_bounded_integer(tmp_path,value):
    with pytest.raises(worker.TrainingJobValidationError,match='positive integer'):
        job(tmp_path,target_shard_max_bytes=value)


def test_nondefault_bound_requires_artifact(tmp_path):
    with pytest.raises(worker.TrainingJobValidationError,match='requires a target snapshot'):
        job(tmp_path,target_shard_max_bytes=128*1024*1024)


def test_explicit_shard_policy_changes_job_identity_but_not_training_policy(tmp_path):
    spec,_=with_target(tmp_path)
    large=replace(spec,target_shard_max_bytes=256*1024*1024)
    assert spec.canonical_sha256!=large.canonical_sha256
    assert spec.training_config.to_dict()==large.training_config.to_dict()
    assert large.to_dict()['target_shard_max_bytes']==256*1024*1024
    assert worker.TrainingJobSpec.from_dict(large.to_dict()).canonical_sha256==large.canonical_sha256


def test_loader_receives_exact_declared_bound_and_owner_checks_receipt(tmp_path,monkeypatch):
    spec,_=with_target(tmp_path,shard_bound=128*1024*1024)
    load=bundle.load_target_artifact;seen=[]
    def observe(*args,**kw):
        seen.append(kw['max_shard_bytes'])
        return load(*args,**kw)
    monkeypatch.setattr(bundle,'load_target_artifact',observe)
    receipt=worker.execute_training_job(spec,trainer=trainer)
    assert seen==[128*1024*1024]
    assert receipt['target_shard_max_bytes']==128*1024*1024
    owner._verify_receipt_payload(spec,receipt,native=False,corpus_verification=receipt['corpus_verification'])
    for invalid in (64*1024*1024,256*1024*1024,float(128*1024*1024),str(128*1024*1024),True,None):
        with pytest.raises(owner.TrainingCoordinationError,match='target_shard_max_bytes'):
            owner._verify_receipt_payload(spec,{**receipt,'target_shard_max_bytes':invalid},native=False,
                corpus_verification=receipt['corpus_verification'])
    missing=dict(receipt);missing.pop('target_shard_max_bytes')
    with pytest.raises(owner.TrainingCoordinationError,match='target_shard_max_bytes'):
        owner._verify_receipt_payload(spec,missing,native=False,corpus_verification=receipt['corpus_verification'])


def test_small_declared_shard_limit_fails_before_trainer_and_no_candidate(tmp_path):
    spec,_=with_target(tmp_path,shard_bound=1)
    with pytest.raises(ValueError,match='shard|bound'):
        worker.execute_training_job(spec,trainer=lambda *args,**kw:pytest.fail('oversize target reached training'))
    assert not Path(spec.output_directory).exists()


def test_legacy_receipt_without_new_bound_still_means_default(tmp_path):
    spec,_=with_target(tmp_path)
    receipt=worker.execute_training_job(spec,trainer=trainer)
    receipt.pop('target_shard_max_bytes')
    owner._verify_receipt_payload(spec,receipt,native=False,corpus_verification=receipt['corpus_verification'])


def test_incremental_resume_policy_binds_nondefault_shard_bound(tmp_path):
    from types import SimpleNamespace
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_incremental_training as incremental
    spec,_=with_target(tmp_path)
    registry=SimpleNamespace(
        get_version=lambda version:{'variant_id':'controlled','artifact':{'sha256':spec.base_checkpoint.sha256,'bytes':spec.base_checkpoint.bytes}},
        get_variant=lambda variant:{'manifest':{'controlled':True}})
    default=incremental._policy(registry,spec)
    assert 'target_shard_max_bytes' not in default
    first=incremental._policy(registry,replace(spec,target_shard_max_bytes=128*1024*1024))
    second=incremental._policy(registry,replace(spec,target_shard_max_bytes=256*1024*1024))
    assert first['target_shard_max_bytes']==128*1024*1024
    assert second['target_shard_max_bytes']==256*1024*1024
    assert default != first != second
