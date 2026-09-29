"""Distributed feature policy/execution checks; fixtures are not native evidence."""
from copy import deepcopy
from dataclasses import asdict
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_distributed_features as feature
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_feature_inputs as inputs
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_feature_inputs import fixture


def setup_inputs(tmp_path):
    manifest, split, entries = fixture(tmp_path)
    target = tmp_path/'targets.json'; target.write_text('{}')
    local = dict(manifest_path=str(manifest), training_path=split['artifacts']['training']['rows']['path'],
        validation_path=split['artifacts']['validation']['rows']['path'], shared_targets=str(target),
        target_snapshot_id='sha256:'+'a'*64)
    train = feature._samples(local['training_path']); validation = feature._samples(local['validation_path'])
    policy = feature.build_feature_policy(local, train, validation)
    policy.update(source_identity={'fixture':'b'*64},max_seconds=60.,source_language='en',model_variant='feature-test',
        feature_optimizer=dict(epochs=3,learning_rate=.35,line_search_attempts=2,
            projection_optimizer_mode='productive_adaptive',projection_momentum=.25,
            projection_candidate_update_order='decoded_embedding_structural'))
    assignment=dict(run_id='assignment',generation=1,base_version_id='parent',record={'record_id':'c'*64,'sample':train[0]},
                    source_observation=None,policy=policy)
    return local,policy,assignment


def test_policy_is_compact_portable_and_independently_reverified(tmp_path):
    local,policy,assignment=setup_inputs(tmp_path)
    assert 'validation_samples' not in policy
    checked=feature.validate_feature_inputs(policy,local)
    assert checked['training_samples']==[assignment['record']['sample']]
    serialized=json.dumps(policy)
    assert str(tmp_path) not in serialized
    assert 'embedding_vector' not in serialized
    assert len(serialized)<16000
    for flag in feature.FALSE_FLAGS:
        assert policy['feature_input_binding'][flag] is False
    Path(local['shared_targets']).write_text('{"drift":1}')
    with pytest.raises(ValueError,match='differ'):
        feature.validate_feature_inputs(policy,local)


@pytest.mark.parametrize('kind',['order','missing','vector','timeout','shard'])
def test_policy_rejects_changed_or_out_of_bounds_inputs(tmp_path,kind):
    local,policy,assignment=setup_inputs(tmp_path)
    checked=feature.validate_feature_inputs(policy,local)
    if kind in ('order','missing','vector'):
        train=deepcopy(checked['training_samples']);tune=checked['validation_samples']
        if kind=='order':train,tune=tune,train
        elif kind=='missing':train=[]
        else:train[0]['embedding_vector'][0]=.25
        with pytest.raises(ValueError):feature.build_feature_policy(local,train,tune)
    else:
        local['target_timeout_seconds' if kind=='timeout' else 'target_shard_max_bytes']=601 if kind=='timeout' else 256*1024*1024+1
        with pytest.raises(ValueError):feature.validate_feature_inputs(policy,local)


def test_assignment_manifest_keeps_exact_verified_rows_and_can_relocate(tmp_path):
    local,policy,assignment=setup_inputs(tmp_path)
    checked=feature.validate_feature_inputs(policy,local)
    path=feature._assignment_manifest(assignment,checked,tmp_path/'assignment')
    split=json.loads(path.read_bytes())
    proof=inputs.verify_feature_training_inputs(path,split['artifacts']['training']['rows']['path'],
                                               split['artifacts']['validation']['rows']['path'])
    assert proof['local_embedding_verification'] is True
    assert proof['training']['input_ids']==checked['verification']['training']['input_ids']
    assert Path(split['artifacts']['training']['rows']['path']).read_bytes()==feature.inc._raw(checked['training_rows'][0])+b'\n'
    assert feature._assignment_manifest(assignment,checked,tmp_path/'assignment')==path
    changed=deepcopy(assignment);changed['record']['sample']['embedding_vector'][0]=.25
    with pytest.raises(ValueError,match='unique verified'):
        feature._assignment_manifest(changed,checked,tmp_path/'other')


def test_configuration_preserves_raw_objective_and_private_supervised_path(tmp_path,monkeypatch):
    local,policy,assignment=setup_inputs(tmp_path)
    checked=feature.validate_feature_inputs(policy,local)
    config=feature._config(assignment,policy,{'checkpoint_path':tmp_path/'base'},tmp_path/'run',checked,tmp_path/'ledger')
    assert config['training_purpose']=='feature_pretraining' and config['publish_repository'] is None
    assert config['projection_candidate_update_order']==['decoded_embedding_structural']
    assert config['max_batches']==1 and config['max_training_rounds']==1
    expected=feature._expected_training_config(policy)
    assert expected.projection_reconstruction_objective=='raw_decoder'
    assert expected.projection_optimizer_mode=='productive_adaptive'
    env='IPFS_DATASETS_LEGAL_IR_TARGET_TIMEOUT_SECONDS';monkeypatch.setenv(env,'17')
    with feature._target_environment(checked['binding']):assert os.environ[env]=='60.0'
    assert os.environ[env]=='17'


def test_execute_rejects_source_or_generation_before_training(tmp_path,monkeypatch):
    local,policy,assignment=setup_inputs(tmp_path)
    installed={'binding':{'generation':2,'version_id':'parent'}}
    monkeypatch.setattr(feature.work,'identity',lambda:{'other':'d'*64})
    with pytest.raises(ValueError,match='source differs'):
        feature.execute_feature_assignment(assignment,policy,installed,tmp_path/'run',feature_inputs=local)
    monkeypatch.setattr(feature.work,'identity',lambda:policy['source_identity'])
    with pytest.raises(ValueError,match='generation differs'):
        feature.execute_feature_assignment(assignment,policy,installed,tmp_path/'run',feature_inputs=local)


def test_execute_preserves_capacity_deferral_and_timeout_environment(tmp_path,monkeypatch):
    local,policy,assignment=setup_inputs(tmp_path)
    checkpoint=tmp_path/'parent';checkpoint.write_bytes(b'{}')
    installed={'binding':{'generation':1,'version_id':'parent','artifact':feature._artifact(checkpoint)},'checkpoint_path':str(checkpoint)}
    monkeypatch.setattr(feature.work,'identity',lambda:policy['source_identity'])
    calls=[]
    def execute(config):
        calls.append(config)
        assert os.environ['IPFS_DATASETS_LEGAL_IR_TARGET_TIMEOUT_SECONDS']=='60.0'
        assert config['training_purpose']=='feature_pretraining'
        return {'deferred':True}
    with pytest.raises(feature.work.CapacityDeferred):
        feature.execute_feature_assignment(assignment,policy,installed,tmp_path/'run',feature_inputs=local,execute_cycle=execute)
    assert len(calls)==1 and not (tmp_path/'run'/'feature-training-result.json').exists()


def test_remote_binding_rejects_qualification_and_changed_source(tmp_path):
    local,policy,assignment=setup_inputs(tmp_path)
    checked=feature.validate_feature_inputs(policy,local)
    report={'training_purpose':'feature_pretraining','assignment_binding':assignment,
            'assignment_sha256':feature.inc._sha(assignment),**feature.FALSE_FLAGS}
    report['qualified']=True
    with pytest.raises(ValueError,match='claims qualification'):
        feature._bind_remote_report(report,assignment,policy,checked,{'sha256':'d'*64,'bytes':1})
    report['qualified']=False;report['source_provenance']={}
    with pytest.raises(ValueError,match='source or parent'):
        feature._bind_remote_report(report,assignment,policy,checked,{'sha256':'d'*64,'bytes':1})


def test_tuning_order_matches_existing_cli_for_reversed_verified_rows(tmp_path):
    local, policy, assignment = setup_inputs(tmp_path)
    manifest = json.loads(Path(local['manifest_path']).read_bytes())
    production = json.loads(Path(manifest['embedding_production_receipt']['path']).read_bytes())
    first = json.loads(Path(local['validation_path']).read_text())
    second = {**first, 'section':'2', 'text':'The agency shall retain record 2.', 'citation':'5 USC 2'}
    (tmp_path/'source-2.txt').write_text(second['text'])
    rows = sorted((first, second), key=lambda row: feature.inc._sha(feature._sample(row)), reverse=True)
    path = Path(local['validation_path']);path.write_bytes(b''.join(feature.inc._raw(row)+b'\n' for row in rows))
    # Input identities come from the exact production receipt; neither vectors nor evidence are regenerated.
    from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_feature_inputs import reference
    ids = {row['section']: row['input_id'] for row in production['inputs']}
    manifest['artifacts']['validation'] = {'rows':reference(path),'count':2,'input_ids':[ids[row['section']] for row in rows]}
    Path(local['manifest_path']).write_bytes(feature.inc._raw(manifest))
    train = feature._samples(local['training_path']);tune = feature._samples(local['validation_path'])
    policy = feature.build_feature_policy(local,train,tune)
    checked = feature.validate_feature_inputs(policy,local)
    expected = [feature._sample(row) for row in feature.work.local_cli().local_records(local['validation_path'])]
    assert checked['validation_samples'] == expected
    assert checked['validation_samples'] != tune
    assert checked['validation_rows'] == rows


def _execution_fixture(tmp_path, monkeypatch):
    local, policy, assignment = setup_inputs(tmp_path)
    root = tmp_path/'run';root.mkdir()
    checkpoint = tmp_path/'parent';checkpoint.write_bytes(b'{}')
    artifact = feature._artifact(checkpoint)
    installed = {'binding':{'generation':1,'version_id':'parent','artifact':artifact},'checkpoint_path':str(checkpoint)}
    evidence = {'run_id':'local-job','base_version_id':'local-parent','candidate_version_id':'candidate',
        'optimizer_accepted_epochs':0,'publication_performed':False,**feature.FALSE_FLAGS}
    worker = {'base_version_id':'local-parent','base_materialized_checkpoint':artifact,
        'candidate_materialized_checkpoint':artifact,'job_spec':{'training_config':{},'autoencoder_config':{}}}
    worker_path = root/'fixture-worker.json';worker_path.write_bytes(feature.inc._raw(worker)+b'\n')
    evidence['worker_receipt_artifact'] = feature._artifact(worker_path)
    receipt = root/'cycle.json';receipt.write_bytes(feature.inc._raw({'training_purpose':'feature_pretraining','training':{'completed':[evidence]}}))
    result = {'sparse_replay_verified':True,'worker_receipt_artifact':evidence['worker_receipt_artifact']}
    class Registry:
        def __init__(self,*args):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def verify_artifact(self,ref):assert ref == evidence['worker_receipt_artifact']
        def artifact_path(self,ref):return worker_path
        def get_run(self,run_id):assert run_id == evidence['run_id'];return {'result':result}
    from ipfs_datasets_py.duckdb_control import autoencoder_registry
    monkeypatch.setattr(autoencoder_registry,'AutoencoderRegistry',Registry)
    monkeypatch.setattr(feature.work,'identity',lambda:policy['source_identity'])
    monkeypatch.setattr(feature.work,'retry_publication',lambda function:function())
    calls=[]
    def execute(config):calls.append(config);return {'receipt':str(receipt)}
    return local,policy,assignment,installed,root,execute,calls,result


def test_publication_failure_resumes_same_training_receipt_without_second_training(tmp_path,monkeypatch):
    local,policy,assignment,installed,root,execute,calls,result = _execution_fixture(tmp_path,monkeypatch)
    uploads=[]
    def publish(report,*args,**kwargs):
        uploads.append(report)
        assert report['completion']['result'] == result
        if len(uploads)==1:raise RuntimeError('injected upload interruption')
        return {'report_reference':{'sha256':'f'*64,'bytes':1}}
    exchange=SimpleNamespace(REPORT_SCHEMA='autoencoder-feature-attempt/v1',publish_feature_report=publish)
    with pytest.raises(RuntimeError,match='upload interruption'):
        feature.execute_feature_assignment(assignment,policy,installed,root,feature_inputs=local,execute_cycle=execute,exchange=exchange)
    assert (root/'feature-training-result.json').exists()
    completed=feature.execute_feature_assignment(assignment,policy,installed,root,feature_inputs=local,execute_cycle=execute,exchange=exchange)
    assert len(calls)==1 and len(uploads)==2 and uploads[0]==uploads[1]
    assert completed['feature_disposition']=='feature_no_update' and completed['weight_reference'] is None


def _evaluation_fixture(checked,config,accepted=1):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as ma
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import _sample_id
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_modal_parser import LegalModalParser
    normalizer=LegalModalParser()
    ids=[_sample_id(row['title'],row['section'],normalizer.normalize_text(row['text'])) for row in checked['validation_samples']]
    result={'bridge_names':list(feature.BRIDGE_NAMES),'target_sample_count':len(ids)+1,'legal_ir_evaluate_provers':False,
        'metric_disk_cache':0,'legal_ir_parallel_workers':1,'use_sample_memory':False,
        'shared_target_supervision_verified':True,'raw_observations':{},'pareto_regressions':{},**feature.FALSE_FLAGS}
    for phase in ('before','after'):
        value=.2 if phase=='after' and accepted else .1
        result[phase]={'sample_count':len(ids),'legal_ir_target_count':len(ids), 'embedding_cosine_similarity':value,
            'reconstruction_loss':.5-value,'cross_entropy_loss':.3,'legal_ir_losses':{'fixture_loss':.2}}
        result['raw_observations'][phase]={'complete':True,'finite':True,'used_for_acceptance':True,'sample_memory_used':False,
            'requested_sample_count':len(ids),'observed_sample_count':len(ids),'embedding_cosine_similarity_mean':value,
            'reconstruction_loss_mean':.5-value,'sample_metrics':[{'sample_id':key,'embedding_cosine_similarity':value,
            'reconstruction_loss':.5-value} for key in ids]}
    weights={'cross_entropy':config.objective_cross_entropy_weight,'reconstruction':config.objective_reconstruction_weight,
        'cosine_gap':config.objective_cosine_gap_weight,'legal_ir':config.objective_legal_ir_weight}
    result['objective_weights']=weights
    result['objective_delta']=ma._evaluation_objective_for_training(SimpleNamespace(**result['before']),**weights)-ma._evaluation_objective_for_training(SimpleNamespace(**result['after']),**weights)
    return result


@pytest.mark.parametrize('change',['valid','target','nonfinite','raw_id','raw_mean','objective','qualified','ir_regression'])
def test_retained_owner_evaluation_rechecks_native_guard_evidence(tmp_path,change):
    local,policy,assignment=setup_inputs(tmp_path);checked=feature.validate_feature_inputs(policy,local)
    config=feature._expected_training_config(policy);evaluation=_evaluation_fixture(checked,config)
    if change=='target':evaluation['after']['legal_ir_target_count']=0
    elif change=='nonfinite':evaluation['after']['cross_entropy_excess_loss']=float('nan')
    elif change=='raw_id':evaluation['raw_observations']['after']['sample_metrics'][0]['sample_id']='unassigned'
    elif change=='raw_mean':evaluation['raw_observations']['after']['embedding_cosine_similarity_mean']=.8
    elif change=='objective':evaluation['objective_delta']=-1
    elif change=='qualified':evaluation['qualified']=True
    elif change=='ir_regression':evaluation['after']['legal_ir_losses']['fixture_loss']=2
    if change=='valid':feature._validate_owner_evaluation(evaluation,checked,config,1)
    else:
        with pytest.raises(ValueError):feature._validate_owner_evaluation(evaluation,checked,config,1)


def _remote_fixture(tmp_path):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import TrainingJobSpec, CheckpointArtifact, SOURCE_MODULE_NAMES
    local,policy,assignment=setup_inputs(tmp_path)
    hashes={key:'a'*64 for key in SOURCE_MODULE_NAMES}
    policy['source_identity']={'native:'+key:value for key,value in hashes.items()}
    checked=feature.validate_feature_inputs(policy,local);config=feature._expected_training_config(policy)
    parent=tmp_path/'parent.json';parent.write_bytes(b'{}');artifact=feature._artifact(parent)
    spec=TrainingJobSpec(job_id='job',run_id='local-run',base_version_id='local-parent',
        base_checkpoint=CheckpointArtifact(str(parent),**artifact),output_directory=str(tmp_path/'worker'),
        code_identity='fixture',dataset_snapshot_id='fixture',split_snapshot_id='fixture',
        samples=tuple(feature.SampleRecord.from_dict(row) for row in checked['training_samples']),
        validation_samples=tuple(feature.SampleRecord.from_dict(row) for row in checked['validation_samples']),
        training_config=config,autoencoder_config={'compute_device':'python'},expected_source_sha256=hashes,
        target_snapshot_id=checked['binding']['target_snapshot_id'],
        target_snapshot_artifact=CheckpointArtifact(local['shared_targets'],**checked['binding']['shared_target_artifact']))
    worker={'job_spec':spec.to_dict(),'job_spec_canonical_sha256':spec.canonical_sha256,
        'base_version_id':spec.base_version_id,'tree_file_sha256':hashes,'source_manifest_verified':True,
        'training_report':{'accepted_epochs':0},'base_materialized_checkpoint':artifact,
        'candidate_materialized_checkpoint':artifact}
    worker=json.loads(feature.inc._raw(worker))
    worker_raw=feature.inc._raw(worker)+b'\n'
    import hashlib
    worker_ref={'sha256':hashlib.sha256(worker_raw).hexdigest(),'bytes':len(worker_raw)}
    evidence={'optimizer_accepted_epochs':0,'candidate_version_id':'candidate','run_id':spec.run_id,
        'next_base_version_id':spec.base_version_id,'base_version_id':spec.base_version_id,
        'worker_receipt_artifact':worker_ref,'batch_id':'fixture','lane_index':0,**feature.FALSE_FLAGS}
    report={'training_purpose':'feature_pretraining','assignment_binding':assignment,'assignment_sha256':feature.inc._sha(assignment),
        'base_artifact':artifact,'candidate_artifact':artifact,'candidate_version_id':'candidate','disposition':'feature_no_update',
        'source_provenance':{'source_record':assignment['record'],'source_observation':assignment['source_observation'],
            'canonical_generation':1,'canonical_version_id':'parent','canonical_artifact':artifact,
            'source_identity':policy['source_identity'],'feature_input_binding':checked['binding']},
        'training_config':config.to_dict(),'autoencoder_config':{'compute_device':'python'},
        'training_samples':checked['training_samples'],'validation_samples':checked['validation_samples'],
        'worker_receipt':worker,'feature_evidence':evidence,
        'completion':{**evidence,'result':{'sparse_replay_verified':True,'worker_receipt_artifact':worker_ref}},
        'weight_publication':None,**feature.FALSE_FLAGS}
    return local,policy,assignment,checked,config,report,parent,artifact


def test_remote_native_source_manifest_must_match_owner_policy(tmp_path):
    local,policy,assignment,checked,config,report,parent,artifact=_remote_fixture(tmp_path)
    feature._bind_remote_report(report,assignment,policy,checked,artifact)
    report['worker_receipt']['tree_file_sha256']['parser']='b'*64
    with pytest.raises(ValueError,match='native source hashes differ'):
        feature._bind_remote_report(report,assignment,policy,checked,artifact)


def test_owner_crash_retry_reuses_and_revalidates_retained_evidence(tmp_path,monkeypatch):
    local,policy,assignment,checked,config,report,parent,artifact=_remote_fixture(tmp_path)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_feature_training
    monkeypatch.setattr(autoencoder_feature_training,'_feature_evidence',lambda registry,spec,completion:report['feature_evidence'])
    monkeypatch.setattr(feature.work,'identity',lambda:policy['source_identity'])
    class Registry:
        paths={artifact['sha256']:parent}
        def get_version(self,version):assert version=='parent';return {'artifact':artifact}
        def artifact_path(self,ref):return self.paths[ref['sha256']]
        def verify_artifact(self,ref):assert feature._artifact(self.artifact_path(ref))==ref
        def stage_artifact(self,path,sha=None):
            ref=feature._artifact(path)
            if sha is not None:assert ref['sha256']==sha
            self.paths[ref['sha256']]=Path(path);return ref
    descriptor={'sha256':'e'*64,'bytes':123}
    exchange=SimpleNamespace(download_feature_report=lambda *args:{'report':report})
    evaluations=[]
    def evaluate(*args):
        evaluations.append(args)
        value=_evaluation_fixture(checked,config,0)
        value['elapsed_seconds']=len(evaluations)*.123
        return value
    verifier=feature.owner_feature_verifier(Registry(),policy,tmp_path/'owner',feature_inputs=local,exchange=exchange,evaluator=evaluate)
    first=verifier(assignment,descriptor)
    second=verifier(assignment,descriptor)
    assert first==second and len(evaluations)==1
    path=tmp_path/'owner'/descriptor['sha256']/'owner-feature-evidence.json'
    retained=json.loads(path.read_bytes());retained['evaluation']['after']['legal_ir_target_count']=0
    path.write_bytes(feature.inc._raw(retained))
    with pytest.raises(ValueError,match='incomplete'):
        verifier(assignment,descriptor)
    assert len(evaluations)==1


def test_stale_requeue_poll_ignores_old_attempt_after_rebased_source_completion():
    import duckdb
    from contextlib import contextmanager
    cx=duckdb.connect(':memory:')
    cx.execute('CREATE SCHEMA autoencoder_control')
    cx.execute('CREATE TABLE autoencoder_control.runs(run_id VARCHAR,status VARCHAR,base_version_id VARCHAR,spec JSON,result JSON)')
    cx.execute('CREATE TABLE autoencoder_control.operations(receipt JSON)')
    def add(run,base):
        cx.execute('INSERT INTO autoencoder_control.runs VALUES (?,?,?,?,?)',[run,'completed',base,
            json.dumps({'campaign_id':'campaign','kind':'generation_attempt','work_id':'source'}),
            json.dumps({'span_disposition':'feature_updated'})])
    add('old-attempt','parent0')
    cx.execute('INSERT INTO autoencoder_control.runs VALUES (?,?,?,?,?)',['source','source_completed','parent0','{}',
        json.dumps({'completion':{'run_id':'old-attempt'}})])
    class Registry:
        @contextmanager
        def _transaction(self):yield cx
        def get_run_completion(self,run):return {'candidate_version':{'version_id':run+'-version'}}
    class Campaign:
        binding={'policy':{'training_purpose':'feature_pretraining'}}
        binding_sha256='binding';campaign_id='campaign';registry=Registry()
        current={'version_id':'parent1','generation':2}
        calls=[]
        def status(self):return {'weights':self.current}
        def requeue_stale_feature_candidate(self,operation,version,**kwargs):
            self.calls.append(version)
            cx.execute("UPDATE autoencoder_control.runs SET status='queued' WHERE run_id='source'")
    campaign=Campaign()
    assert feature.advance_feature_generation(campaign) is None
    assert campaign.calls==['old-attempt-version']
    # Its source later completes a rebased attempt that becomes canonical.
    add('new-attempt','parent1')
    cx.execute("UPDATE autoencoder_control.runs SET status='source_completed',result=? WHERE run_id='source'",
               [json.dumps({'completion':{'run_id':'new-attempt'}})])
    cx.execute('INSERT INTO autoencoder_control.operations VALUES (?)',[json.dumps({'command':'AdvanceSpanGeneration',
        'campaign_id':'campaign','binding_sha256':'binding','version_id':'new-attempt-version'})])
    campaign.current={'version_id':'new-attempt-version','generation':3}
    assert feature.advance_feature_generation(campaign) is None
    assert feature.advance_feature_generation(campaign) is None
    assert campaign.calls==['old-attempt-version']
    cx.close()


def test_immutable_publish_failure_before_commit_leaves_no_partial_final(tmp_path,monkeypatch):
    final=tmp_path/'record.json';unrelated=tmp_path/'.retained-other.tmp';unrelated.write_bytes(b'retained')
    original=feature.os.fsync
    monkeypatch.setattr(feature.os,'fsync',lambda fd:(_ for _ in ()).throw(OSError('injected fsync failure')))
    with pytest.raises(OSError,match='fsync failure'):
        feature._immutable_bytes(final,b'complete')
    assert not final.exists() and list(tmp_path.iterdir())==[unrelated]
    monkeypatch.setattr(feature.os,'fsync',original)
    feature._immutable_bytes(final,b'complete')
    assert final.read_bytes()==b'complete' and unrelated.read_bytes()==b'retained'


@pytest.mark.parametrize('same',[False,True])
def test_immutable_publish_preserves_concurrent_winner(tmp_path,monkeypatch,same):
    final=tmp_path/'record.json';winner=b'complete' if same else b'other writer'
    def race(source,destination,**kwargs):
        assert Path(source).read_bytes()==b'complete'
        Path(destination).write_bytes(winner)
        raise FileExistsError('concurrent publisher')
    monkeypatch.setattr(feature.os,'link',race)
    if same:feature._immutable_bytes(final,b'complete')
    else:
        with pytest.raises(ValueError,match='immutable'):
            feature._immutable_bytes(final,b'complete')
    assert final.read_bytes()==winner and list(tmp_path.iterdir())==[final]


def test_owner_plain_seed_anchor_binds_exact_parent_without_materialized_alias(tmp_path,monkeypatch):
    import hashlib
    local,policy,assignment,checked,config,report,parent,artifact=_remote_fixture(tmp_path)
    candidate=tmp_path/'candidate.json';candidate.write_bytes(b'{"candidate":1}')
    candidate_artifact=feature._artifact(candidate)
    report.update(candidate_artifact=candidate_artifact,disposition='feature_updated',
        weight_publication={'kind':'feature_sparse','anchor_reference':{
            'repository_id':'fixture','commit_sha':'a'*40,'path_in_repo':'parent.json',**artifact}})
    report['worker_receipt']['training_report']['accepted_epochs']=1
    report['worker_receipt']['candidate_materialized_checkpoint']=candidate_artifact
    raw=feature.inc._raw(report['worker_receipt'])+b'\n'
    worker_ref={'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
    report['feature_evidence'].update(optimizer_accepted_epochs=1,next_base_version_id='candidate',worker_receipt_artifact=worker_ref)
    report['completion']={**report['feature_evidence'],'result':{'sparse_replay_verified':True,'worker_receipt_artifact':worker_ref}}
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_feature_training
    monkeypatch.setattr(autoencoder_feature_training,'_feature_evidence',lambda *args:report['feature_evidence'])
    monkeypatch.setattr(feature.work,'identity',lambda:policy['source_identity'])
    installs=[]
    def install(generation,*args,**kwargs):
        installs.append(generation)
        return {'checkpoint_path':str(candidate),'download_receipt':{'replay_verified':True}}
    monkeypatch.setattr(feature.work,'install_generation',install)
    class Registry:
        paths={artifact['sha256']:parent}
        def get_version(self,version):assert version=='parent';return {'artifact':artifact}
        def artifact_path(self,ref):return self.paths[ref['sha256']]
        def verify_artifact(self,ref):assert feature._artifact(self.artifact_path(ref))==ref
        def stage_artifact(self,path,sha=None):
            ref=feature._artifact(path)
            if sha is not None:assert ref['sha256']==sha
            self.paths[ref['sha256']]=Path(path);return ref
    exchange=SimpleNamespace(download_feature_report=lambda *args:{'report':report})
    verifier=feature.owner_feature_verifier(Registry(),policy,tmp_path/'owner',feature_inputs=local,exchange=exchange,
        evaluator=lambda *args:_evaluation_fixture(checked,config,1))
    result=verifier(assignment,{'sha256':'e'*64,'bytes':123})
    assert len(installs)==1 and result['artifact']==candidate_artifact
    assert result['result']['span_disposition']=='feature_updated' and result['result']['admitted'] is False
    report['weight_publication']['anchor_reference']['sha256']='f'*64
    with pytest.raises(ValueError,match='sparse parent differs'):
        verifier(assignment,{'sha256':'f'*64,'bytes':123})
    assert len(installs)==1
