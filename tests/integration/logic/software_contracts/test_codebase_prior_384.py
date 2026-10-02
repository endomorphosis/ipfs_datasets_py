"""Real prior-centered numerical work and ordered native model continuation."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

_spec=importlib.util.spec_from_file_location('codebase_prior_live_fixture',Path(__file__).with_name('test_codebase_training_lifecycle.py'))
_fixture=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_fixture)
current,envelope=_fixture.current,_fixture.envelope
from ipfs_datasets_py.logic.software_contracts import codebase_prior_384 as prior
from ipfs_datasets_py.logic.software_contracts import codebase_training_corpus as corpus_owner
from ipfs_datasets_py.logic.software_contracts import codebase_source_384 as source384
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry,RegistryError
from ipfs_accelerate_py.agent_supervisor.runtime import repository_resource_bridge as bridge


def fit(current,operation,parent,model_head):
    with envelope(current) as host:
        with host.phase(bridge.RepositoryPhaseDemand('training',memory_mb=4096)) as phase:
            result=prior.train(current.index,current.repo,expected_head=current.head,
                frozen_corpus=current.frozen,registry=current.registry,parent_version_id=parent,
                expected_model_head=model_head,operation_id=operation,
                embedding_snapshot=os.environ['CODEBASE384_EMBEDDING_SNAPSHOT'],**phase.native_options())
    current.results.append(result)
    return result


def publish(current,result,operation):
    with envelope(current) as host:
        with host.phase(bridge.RepositoryPhaseDemand('validation',memory_mb=4096)) as phase:
            return prior.promote(current.index,current.repo,expected_head=current.head,
                registry=current.registry,version_id=result['version_id'],operation_id=operation,**phase.native_options())


@pytest.fixture(scope='module')
def first(current):
    current.registry.close()
    policy=prior.RetentionPolicy(current.index)
    current.registry=AutoencoderRegistry(current.root/'prior_models.duckdb',current.root/'prior_models',promotion_validator=policy)
    policy.bind(current.registry)
    path=Path(os.environ['CODEBASE384_CHECKPOINT'])
    original=source384.register_shared_parent(current.registry,checkpoint_path=path,expected_sha256=source384._sha(path.read_bytes()))
    current.parent=prior.register_parent(current.index,current.registry,source_parent_version_id=original)
    current.variant=current.registry.get_version(current.parent)['variant_id']
    current.registry.initialize_head('initialize-prior-main',current.variant,'main',current.parent)
    current.model_head=current.registry.resolve_head(current.variant,'main')
    value=fit(current,'prior-round-one',current.parent,current.model_head)
    loaded=prior.load(current.index,current.registry,value['version_id'])[0][1]
    (current.root/'first-fit.json').write_bytes(prior.raw(dict(result=value,fit=loaded['fit'],evaluation=loaded['evaluation'],
        source_head=loaded['request']['source_head'],canary_floor=loaded['canary_floor'])))
    return SimpleNamespace(result=value,value=loaded,policy=policy,original=original,head=deepcopy(current.model_head))


def test_actual_prior_head_refit_changes_weights_and_retains_fixed_holdout(current,first):
    fit_report=first.value['fit'];evaluation=first.value['evaluation']
    assert fit_report['nonzero_weight_update'] and fit_report['head_bytes_changed']
    assert fit_report['weight_delta_l2']>1e-12
    assert fit_report['embedded_rows']==9 and fit_report['reused_embedding_microbatches']==0
    assert fit_report['full_selected_training_head_refit'] and not fit_report['exact_optimizer_resume']
    assert fit_report['optimizer_steps']==0
    assert evaluation['parent_holdout']['count']==evaluation['child_holdout']['count']==3
    assert evaluation['parent_holdout']['exact_targets']==evaluation['child_holdout']['exact_targets']==3
    assert evaluation['byte_identical_parent_control']==evaluation['parent_holdout']
    assert not evaluation['holdout_used_for_selection']
    assert current.registry.resolve_head(current.variant,'main')==first.head


def test_exact_durable_native_fit_replay_performs_no_numerical_work(current,first,monkeypatch):
    def no_worker(*a,**k):pytest.fail('completed replay invoked numerical worker')
    with monkeypatch.context() as patch:
        patch.setattr(prior,'_worker',no_worker)
        result=fit(current,'prior-round-one',current.parent,current.model_head)
    assert result['version_id']==first.result['version_id'] and result['replayed'] and not result['training_executed']


@pytest.mark.parametrize('damage',[None,'request_parent','corpus','source','producer','profile','ridges',
    'head','run_id','floor','input_receipt','output_receipt','delta','topology','favorable_metrics','feature_hash','feature_assets','feature_shape','feature_population','feature_fields'])
def test_resealed_completed_copy_cannot_detach_exact_native_lineage(current,first,damage):
    """Native completed copies exercise joins; they are not additional numerical fits."""
    value=deepcopy(first.value)
    request=value['request'];request['operation_id']='copy-control-'+str(damage)
    if damage=='request_parent':request['parent_version_id']='sha256:'+'0'*64
    elif damage=='corpus':request['corpus_sha256']='0'*64
    elif damage=='source':request['source_head']['snapshot_cid']='wrong-source'
    elif damage=='producer':request['producer']={'forged':True}
    elif damage=='profile':request['profile']='wrong-profile'
    elif damage=='ridges':request['ridges']=[1.]
    elif damage=='head':request['expected_model_head']['generation']+=1
    elif damage=='topology':request['topology']='implicit-two-parent-merge'
    run_id='prior384:'+prior.sha(prior.raw(request))
    if damage=='run_id':run_id+='-altered'
    value['run_id']=run_id
    if damage=='floor':value['canary_floor']['exact_targets']=0
    elif damage=='input_receipt':value['worker_receipt']['input_sha256']='0'*64
    elif damage=='output_receipt':value['worker_receipt']['output_sha256']='0'*64
    elif damage in ('delta','favorable_metrics'):
        if damage=='delta':value['fit']['weight_delta_l2']+=1
        else:value['evaluation']['child_holdout']['exact_targets']=4
        result={key:value[key] for key in ('producer','checkpoint','features','embedding_assets','evaluation','fit')}
        value['worker_receipt']['output_sha256']=prior.sha(prior.raw(result))
    if damage in ('feature_hash','feature_assets','feature_shape','feature_population','feature_fields'):
        feature=value['features'][0]
        if damage=='feature_hash':feature['embedding_sha256']='0'*64
        elif damage=='feature_assets':feature['assets_sha256']='0'*64
        elif damage=='feature_shape':
            feature['embedding']=feature['embedding'][:-1]
            feature['embedding_sha256']=prior.sha(prior.raw(feature['embedding']))
        elif damage=='feature_population':value['features'][0],value['features'][1]=value['features'][1],value['features'][0]
        else:feature['undeclared_field']=True
        value['feature_artifacts']=[prior.generations._stage(current.registry,row) for row in value['features']]
        result={key:value[key] for key in ('producer','checkpoint','features','embedding_assets','evaluation','fit')}
        value['worker_receipt']['output_sha256']=prior.sha(prior.raw(result))
    registry=current.registry
    registry.create_run('create:'+run_id,run_id,current.variant,current.parent,request)
    policy=registry.get_run_lifecycle(first.value['run_id'])
    registry.configure_run_lifecycle(run_id,policy)
    lease=registry.claim_run('claim:'+run_id,run_id,'explicit-completed-copy-control',lease_seconds=20)['lease']
    artifact=prior.generations._stage(registry,value)
    receipt=registry.complete_run('complete:'+run_id,lease,artifact,dict(admitted=False,
        scope='completed-copy-control-not-another-numerical-fit'))
    if damage is None:
        assert prior.load(current.index,registry,receipt['version_id'])[0][1]==value
    elif damage=='favorable_metrics':
        assert prior.load(current.index,registry,receipt['version_id'])[0][1]==value
        evaluation=dict(candidate_version_id=receipt['version_id'],protocol_id='prior384-fixed-canary-retention@1',
            evaluation_sha256=prior.sha(prior.raw(value['evaluation'])))
        assert first.policy(registry.get_version(receipt['version_id']),evaluation) is False
        with pytest.raises(RegistryError,match='qualified owner-side'):
            registry.promote_head('forged-retention-promote',current.variant,'main',receipt['version_id'],
                expected_version_id=first.head['version_id'],expected_generation=first.head['generation'],evaluation=evaluation)
    else:
        with pytest.raises(ValueError,match='request|source|parent|head|floor|receipt|update|microbatch'):
            prior.load(current.index,registry,receipt['version_id'])
    assert registry.resolve_head(current.variant,'main')==first.head


def test_real_canary_policy_and_atomic_promotion_allow_ordered_changed_source_continuation(current,first):
    first_promotion=publish(current,first.result,'promote-prior-one')
    assert first_promotion['generation']==2
    model_head=current.registry.resolve_head(current.variant,'main')
    for i,operator in enumerate(('+','-','*')):
        (current.repo/f'train_{i}.py').write_text('def calculate(capacity: int, threshold: int) -> int:\n'
            f'    result = capacity {operator} threshold\n    return result\n')
    with envelope(current) as host:
        with host.phase(bridge.RepositoryPhaseDemand('scan',memory_mb=4096)) as phase:
            current.head=current.index.prepare_current(current.repo,repository_id=current.head.repository_id,
                operation_id='prior-changed-training-symbols',expected_head=current.head,**phase.native_options()).head
        with host.phase(bridge.RepositoryPhaseDemand('semantic_index',memory_mb=4096)):
            current.frozen=corpus_owner.freeze_corpus(current.index,expected_head=current.head,selections=current.selections)
    second=fit(current,'prior-round-two',first.result['version_id'],model_head)
    value=prior.load(current.index,current.registry,second['version_id'])[0][1]
    assert value['fit']['embedded_rows']==3 and value['fit']['reused_embedding_microbatches']==6
    assert value['fit']['weight_delta_l2']>1e-12
    assert value['canary_floor']==first.value['canary_floor']
    assert value['evaluation']['child_holdout']['exact_targets']==3
    assert value['checkpoint']['training']['base_checkpoint_sha256']==prior.sha(prior.raw(first.value['checkpoint']))
    parent_features={r['source_sha256']:r for r in first.value['features']}
    reused=[r for r in value['features'] if r['source_sha256'] in parent_features]
    assert len(reused)==6 and all(r==parent_features[r['source_sha256']] for r in reused)
    second_promotion=publish(current,second,'promote-prior-two')
    assert second_promotion['generation']==3
    with pytest.raises(ValueError,match='current prior child source'):
        publish(current,first.result,'stale-first-source-promotion')
    with pytest.raises(RegistryError,match='compare-and-swap'):
        current.registry.promote_head('stale-first-cas',current.variant,'main',first.result['version_id'],
            expected_version_id=first.head['version_id'],expected_generation=first.head['generation'],
            evaluation=dict(candidate_version_id=first.result['version_id'],protocol_id='prior384-fixed-canary-retention@1',
                evaluation_sha256=prior.sha(prior.raw(first.value['evaluation']))))
    current.second=(second,value)
    (current.root/'ordered-continuation.json').write_bytes(prior.raw(dict(first_promotion=first_promotion,
        second_promotion=second_promotion,first_fit=first.value['fit'],second_fit=value['fit'],
        first_evaluation=first.value['evaluation'],second_evaluation=value['evaluation'],
        fixed_canary_floor=value['canary_floor'],unchanged_microbatches_reused=6,
        source_head=value['request']['source_head'],original_shared_parent_version=first.original,
        final_head=current.registry.resolve_head(current.variant,'main'),provider_calls=0)))


def test_complete_ancestral_roles_fixed_canaries_and_no_implicit_merge(current,first):
    second,value=current.second
    chain=prior.load(current.index,current.registry,second['version_id'])
    assert len(chain)==3
    for damage in ('roles','canary'):
        candidate=deepcopy(value['corpus'])
        if damage=='roles':candidate['source_corpus']['selections']=candidate['source_corpus']['selections'][:-1]
        else:next(r for r in candidate['rows'] if r['role']=='holdout')['source_sha256']='0'*64
        with pytest.raises(ValueError,match='ancestral|canaries'):
            prior._successor(candidate,chain)
    with pytest.raises(ValueError,match='exact selected prior parent'):
        fit(current,'implicit-stale-lane',first.result['version_id'],first.head)


def test_caller_metrics_cannot_waive_native_fixed_canary_policy(current,first):
    second,value=current.second
    version=current.registry.get_version(second['version_id'])
    evaluation=dict(candidate_version_id=second['version_id'],protocol_id='prior384-fixed-canary-retention@1',
                    evaluation_sha256='0'*64)
    assert first.policy(version,evaluation) is False


def test_actual_model_dependent_projection_rebuilds_and_exact_retry_reuses_without_inference(current,first,monkeypatch):
    second,value=current.second
    options=dict(expected_head=current.head,registry=current.registry,paths=['holdout_0.py','holdout_1.py','holdout_2.py'],
        embedding_snapshot=os.environ['CODEBASE384_EMBEDDING_SNAPSHOT'])
    def infer(version):
        with envelope(current) as host:
            with host.phase(bridge.RepositoryPhaseDemand('inference',memory_mb=4096)) as phase:
                return prior.infer_and_index(current.index,current.repo,version_id=version,**options,**phase.native_options())
    older=infer(first.result['version_id']);newer=infer(second['version_id'])
    assert older['inference_executed'] and newer['inference_executed']
    assert older['artifact']!=newer['artifact']
    assert older['projection']['key']['source_head']==newer['projection']['key']['source_head']
    assert older['projection']['key']['checkpoint_sha256']!=newer['projection']['key']['checkpoint_sha256']
    with pytest.raises(ValueError,match='model-dependent projection key'):
        prior.load_projection(current.index,current.registry,older['artifact'],version_id=second['version_id'],
            **{k:v for k,v in options.items() if k!='registry'})
    def no_worker(*a,**k):pytest.fail('exact projection replay attempted model work')
    with monkeypatch.context() as patch:
        patch.setattr(source384,'_worker',no_worker)
        replay=infer(second['version_id'])
    assert not replay['inference_executed'] and replay['artifact']==newer['artifact']
    assert not replay['training_executed']
    for report in (older,newer):
        assert all(r['source_contract']['status']=='qualified' for r in report['projection']['inference']['rows'])
    (current.root/'projection-rebuild.json').write_bytes(prior.raw(dict(older=older,newer=newer,replay=replay,
        stale_model_projection_refused=True,deterministic_source_head_unchanged=True)))


def test_prior_runtime_registered_separately_from_unanchored_head_contract():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_modality_contracts as contracts
    from ipfs_datasets_py.logic.software_contracts import codebase_runtime_384 as old
    registry=contracts.ModalityAdapterRegistry()
    native=old.register_runtime(registry);anchored=prior.register_runtime(registry)
    assert anchored.contract.sha256!=native.contract.sha256
    assert registry.resolve(anchored.contract,required_capabilities=('train','evaluate')) is anchored
    contract=prior.describe()
    assert contract['optimizer_steps']==0 and not contract['exact_optimizer_resume']
    assert contract['holdout_role']=='fixed_deployment_canary_not_final_unseen_test'


def test_actual_running_prior_child_cancellation_cannot_complete_or_promote(current,first):
    from concurrent.futures import ThreadPoolExecutor
    import psutil,threading,time
    signal=threading.Event()
    second,value=current.second
    head=current.registry.resolve_head(current.variant,'main')
    captured=[]
    def execute(host):
        with host.phase(bridge.RepositoryPhaseDemand('training',memory_mb=4096)) as phase:
            return prior.train(current.index,current.repo,expected_head=current.head,frozen_corpus=current.frozen,
                registry=current.registry,parent_version_id=second['version_id'],expected_model_head=head,
                operation_id='cancel-actual-prior',embedding_snapshot=os.environ['CODEBASE384_EMBEDDING_SNAPSHOT'],
                **dict(phase.native_options(),cancel_event=signal))
    with envelope(current) as host,ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(execute,host)
        end=time.monotonic()+30
        while time.monotonic()<end:
            pids=[]
            for child in psutil.Process().children(recursive=True):
                try:
                    if any(part.endswith('codebase_prior_384_worker.py') for part in child.cmdline()):pids.append(child.pid)
                except psutil.NoSuchProcess:pass
            if pids:captured=pids;break
            if future.done():pytest.fail('prior child returned before cancellation: '+repr(future.result()))
            time.sleep(.02)
        assert captured
        signal.set()
        with pytest.raises(ValueError,match='cancel|bounded prior worker'):
            future.result(timeout=20)
    assert not any(psutil.pid_exists(pid) for pid in captured)
    assert current.registry.resolve_head(current.variant,'main')==head
    with current.registry._transaction() as cx:
        rows=cx.execute("SELECT run_id FROM autoencoder_control.runs WHERE status='cancelled'").fetchall()
    assert len(rows)==1 and current.registry.get_run_completion(rows[0][0]) is None
    with pytest.raises(RegistryError,match='terminal'):
        current.registry.claim_run('cancelled-prior-reclaim',rows[0][0],'stale',lease_seconds=1)
    (current.root/'cancelled-prior.json').write_bytes(prior.raw(dict(status='cancelled',actual_child_reaped=True,
        unchanged_head=head,native_run_id=rows[0][0],proof_rules_modified=False)))


def test_actual_prior_decoder_forced_literal_guard_feature_collisions_do_not_acquire_semantics(current,first):
    """Explicit equal-vector control, not a claim that native GTE collided."""
    from ipfs_datasets_py.logic.formalization.autoencoder.structured_source_384 import Runtime
    from ipfs_datasets_py.logic.formalization.autoencoder.source_program_runtime_384 import SourceProgramDecoder384
    second,value=current.second
    texts=[
        'def calculate(capacity: int, threshold: int) -> int:\n    return capacity + 1\n',
        'def calculate(capacity: int, threshold: int) -> int:\n    return capacity + 2\n',
        'def calculate(capacity: int, threshold: int) -> int:\n    if threshold > 0:\n        return capacity + threshold\n    return capacity - threshold\n',
        'def calculate(capacity: int, threshold: int) -> int:\n    if threshold >= 0:\n        return capacity + threshold\n    return capacity - threshold\n']
    embedding=value['features'][0]['embedding']
    rows=[dict(id='collision-'+str(i),source_text=text,embedding=deepcopy(embedding)) for i,text in enumerate(texts)]
    decoder=SourceProgramDecoder384(Runtime(value['checkpoint']),checkpoint_sha256=prior.sha(prior.raw(value['checkpoint'])))
    result=decoder.infer(rows)
    assert len({prior.sha(prior.raw(r['candidate_ir'])) for r in result['rows']})==1
    assert all(r['source_contract']['status']=='unsupported' and not r['source_contract']['proof_authority']
        for r in result['rows'])
    assert len({r['source_sha256'] for r in result['rows']})==4
    (current.root/'feature-collision-control.json').write_bytes(prior.raw(dict(
        scope='explicit_equal_embedding_control_not_observed_natural_GTE_collision',
        distinct_source_inputs=4,identical_learned_candidate=True,independent_unsupported=4,
        original_checked_source_semantics_unchanged=True,result=result)))


def test_cold_native_owner_replays_ordered_microbatches_without_training(current,first,monkeypatch):
    second,value=current.second
    current.registry.close()
    policy=prior.RetentionPolicy(current.index)
    current.registry=AutoencoderRegistry(current.root/'prior_models.duckdb',current.root/'prior_models',promotion_validator=policy)
    policy.bind(current.registry)
    def no_work(*a,**k):pytest.fail('cold historical read attempted model execution')
    with monkeypatch.context() as patch:
        patch.setattr(prior,'_worker',no_work);patch.setattr(source384,'_worker',no_work)
        restored=prior.load(current.index,current.registry,second['version_id'])
    assert len(restored)==3 and restored[0][1]==value
    assert current.registry.resolve_head(current.variant,'main')['version_id']==second['version_id']
    assert len(restored[0][1]['feature_artifacts'])==9
    (current.root/'cold-replay.json').write_bytes(prior.raw(dict(version_id=second['version_id'],
        ordered_generations=3,immutable_microbatches_verified=9,training_executed=False,inference_executed=False,
        native_head=current.registry.resolve_head(current.variant,'main'))))
