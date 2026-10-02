"""Real source/queue/model owners under the live default-host resource bridge."""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_accelerate_py.agent_supervisor.runtime import repository_resource_bridge as bridge
from ipfs_accelerate_py.agent_supervisor.runtime.resource_scheduler import ResourceScheduler, ResourcePolicy
from ipfs_accelerate_py.p2p_tasks.task_queue import TaskQueue
from ipfs_accelerate_py.p2p_tasks.codebase_federated_dispatch import CodebaseQueueDispatcher, TASK_TYPE
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry, RegistryError
from ipfs_datasets_py.logic.software_contracts import codebase_source_training as source
from ipfs_datasets_py.logic.software_contracts import codebase_federated_training as federation
from ipfs_datasets_py.logic.software_contracts import codebase_dispatched_federation as dispatched
from ipfs_datasets_py.logic.software_contracts import codebase_federated_admission as admission
from ipfs_datasets_py.logic.software_contracts.codebase_federated_artifacts import CodebaseFederatedArtifactWorker
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import codebase_runtime_8d as runtimes
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features


@contextmanager
def envelope(value,slots=1):
    local = ResourceScheduler(ResourcePolicy(max_lanes=8))
    with bridge.RepositoryResourceBridge(local).reserve(repository_id='federation8d-real',workspace=value.root,
            budget=bridge.RepositoryResourceBudget(cpu_slots=slots,memory_mb=1024*slots,process_slots=slots,
                disk_bytes=512*1024**2,wall_time_ms=180000)) as parent:
        yield parent
    assert parent.receipt()['closed'] and not local.active_leases
    value.receipts.append(parent.receipt())


@pytest.fixture(scope='module')
def current(tmp_path_factory):
    import duckdb
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
    from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
    from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
    from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
    from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
    root=tmp_path_factory.mktemp('federation8d');repo=root/'repo';repo.mkdir()
    for name,offset in (('a.py',1),('b.py',2),('c.py',3),('tune.py',7),('canary.py',9)):
        (repo/name).write_text(f'def step(n: int) -> int:\n    return n + {offset}\n')
    cx=duckdb.connect(str(root/'source.duckdb'),config={'threads':1,'memory_limit':'64MB'})
    store=DuckDBASTStore(connection=cx);cas=ImmutableCAS(root/'cas')
    index=RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store),artifacts=cas,catalog=CodebaseCatalog(store,cas))
    policy=admission.RetentionPolicy(index)
    registry=AutoencoderRegistry(root/'models.duckdb',root/'models',promotion_validator=policy);policy.bind(registry)
    queue=TaskQueue(str(root/'queue.duckdb'))
    worker=CodebaseFederatedArtifactWorker(cas,root/'worker-receipts',memory_mb=1024)
    value=SimpleNamespace(root=root,repo=repo,cx=cx,index=index,cas=cas,registry=registry,queue=queue,
        worker=worker,dispatcher=CodebaseQueueDispatcher(queue,worker),receipts=[],results=[])
    value.clients=[federation.CodebaseFederatedClient('one',('c.py',)),federation.CodebaseFederatedClient('two',('a.py','b.py'))]
    selections=[source.CodebaseTrainingSelection(path,'train' if path in ('a.py','b.py','c.py') else path[:-3])
        for path in ('a.py','b.py','c.py','tune.py','canary.py')]
    with envelope(value) as parent:
        with parent.phase(bridge.RepositoryPhaseDemand('scan',memory_mb=1024)) as phase:
            value.head=index.prepare_current(repo,repository_id='repository:federation8d',operation_id='capture',
                expected_head=None,**phase.native_options()).head
        with parent.phase(bridge.RepositoryPhaseDemand('training',memory_mb=1024)) as phase:
            value.parent=source.train_current_codebase_features(index,repo,expected_head=value.head,registry=registry,
                selections=selections,operation_id='root',epochs=1,learning_rate=.002,**phase.native_options())
        value.variant=value.parent.to_dict()['variant_id']
        registry.initialize_head('initialize-main',value.variant,'main',value.parent.to_dict()['version_id'])
        value.model_head=registry.resolve_head(value.variant,'main')
        value.round=train(value,parent)
    try:yield value
    finally:
        (root/'qualification.json').write_bytes(source._wire(dict(source_head=value.head.to_dict(),
            parent=value.parent.to_dict(),round=value.round.to_dict(),results=value.results,envelopes=value.receipts,
            model_provider_calls=0,scope='five-row structural-feature development cohort; no formal decoder or unseen test claim')))
        queue.close();registry.close();cx.close()


def train(value,parent,**changes):
    with parent.phase(bridge.RepositoryPhaseDemand('training',memory_mb=1024)) as phase:
        options=dict(expected_head=value.head,registry=value.registry,base_version_id=value.parent.to_dict()['version_id'],
            clients=value.clients,operation_id='round',dispatcher=value.dispatcher,worker=value.worker,artifacts=value.cas,
            epochs=1,learning_rate=.002,**phase.native_options());options.update(changes)
        return dispatched.train_current_dispatched_codebase_round(value.index,value.repo,**options)


def saved(value,version=None):
    version=value.round.to_dict()['version_id'] if version is None else version
    return runtimes._read_candidate(value.registry,value.registry.get_version(version))


def test_real_native_queue_source_training_binary_reduction_and_reset(current):
    child=saved(current);parent=saved(current,current.parent.to_dict()['version_id'])
    report=child['report']['codebase_federation']
    assert current.worker.numerical_invocations==2
    assert child['state']['parameters']!=parent['state']['parameters']
    assert [(r['client_id'],r['sample_count']) for r in report['round']['clients']]==[('one',1),('two',2)]
    assert all(r['training_report']['attempted_epochs']==1 for r in report['clients'])
    assert child['state']['completed_epochs']==0
    assert all(r['step']==0 for r in child['state']['adam'])
    assert child['contract']==parent['contract'] and child['feature_space']==parent['feature_space']
    for row in current.round.to_dict()['clients']:
        task=current.queue.get(row['task_id']);assert task['status']=='completed' and task['task_type']==TASK_TYPE
        assert 'parameters' not in task['payload'] and 'local_state' not in task['result']
    current.results.append(dict(control='actual_federation',evaluation=report['evaluation'],
        fixed_union=[r['name'] for r in report['round']['parameters']],optimizer_reset=True))


def test_completed_exact_retry_and_historical_load_do_not_fit(current,monkeypatch):
    monkeypatch.setattr(source,'_worker',lambda *a,**k:pytest.fail('replay fitted'))
    monkeypatch.setattr(current.dispatcher,'dispatch',lambda *a,**k:pytest.fail('replay dispatched'))
    with envelope(current) as parent:again=train(current,parent)
    assert again.artifact_cid==current.round.artifact_cid
    loaded=dispatched.load_dispatched_codebase_round(current.index,current.registry,current.round.to_dict()['version_id'],
        dispatcher=current.dispatcher,artifacts=current.cas,artifact_cid=current.round.artifact_cid)
    assert loaded.to_dict()==current.round.to_dict() and not loaded.observed_live


def test_independent_decoder_rejects_self_consistent_favorable_saved_diagnostics(current):
    child=saved(current);base=federation._parent(current.index,current.registry,
        current.parent.to_dict()['version_id'],source.CodebaseFeatureTrainingLimits())
    observation=deepcopy(child['report']['codebase_federation']['evaluation']['aggregate']['canary'])
    batch=[*base['canary'],*base['replay']]
    source._diagnostic(observation,base['canary'],child['state'],child['state']['contract_sha256'],
        child['feature_space'],batch_targets=batch,batch_start=0)
    vectors,_,_=features._matrix(child['feature_space'],base['canary'])
    for vector,row in zip(vectors,observation['inference']['rows']):
        offset=0
        for name in child['feature_space']['projection_ids']:
            count=sum(c[0]==name for c in child['feature_space']['columns'])
            row['reconstructed_projection_features'][name]=vector[offset:offset+count];offset+=count
    observation['mean_squared_errors']=[0.]*len(vectors);observation['mean_squared_error']=0.
    with pytest.raises(source.CodebaseFeatureTrainingError,match='independently replayed'):
        source._diagnostic(observation,base['canary'],child['state'],child['state']['contract_sha256'],
            child['feature_space'],batch_targets=batch,batch_start=0)


def test_owner_retention_replays_actual_weights_and_cas_is_parent_bound(current):
    with envelope(current) as parent:
        with parent.phase(bridge.RepositoryPhaseDemand('validation',memory_mb=1024)) as phase:
            value=admission.evaluate_retention(current.index,current.registry,current.round.to_dict()['version_id'])
            current.results.append(dict(control='retention',evaluation=value))
            assert value['nonzero_parameter_change'] and value['retained']
            receipt=admission.promote_current(current.index,current.repo,expected_head=current.head,
                registry=current.registry,version_id=current.round.to_dict()['version_id'],
                expected_model_head=current.model_head,operation_id='promote',**phase.native_options())
            assert receipt['generation']==2
            with pytest.raises(source.CodebaseFeatureTrainingError,match='parent head'):
                admission.promote_current(current.index,current.repo,expected_head=current.head,
                    registry=current.registry,version_id=current.round.to_dict()['version_id'],
                    expected_model_head=current.model_head,operation_id='stale-promotion',**phase.native_options())


def test_caller_favorable_metrics_cannot_replace_independent_policy(current):
    value=admission.evaluate_retention(current.index,current.registry,current.round.to_dict()['version_id'])
    value['scores']['canary']['candidate']['mean_squared_error']=0.
    with pytest.raises(RegistryError,match='qualified owner-side'):
        current.registry.promote_head('forged-retention',current.variant,'main',current.round.to_dict()['version_id'],
            expected_version_id=current.round.to_dict()['version_id'],expected_generation=2,evaluation=value)


def test_actual_lost_queue_completion_reply_recovers_without_second_local_fit(current,monkeypatch):
    original_complete=current.queue.complete;original_dispatch=current.dispatcher.dispatch
    lost=[];before=current.worker.numerical_invocations
    def complete(*args,**kwargs):
        result=original_complete(*args,**kwargs)
        if not lost:
            lost.append(True)
            raise OSError('injected lost committed completion reply')
        return result
    def retry_same_request(*args,**kwargs):
        try:return original_dispatch(*args,**kwargs)
        except OSError as error:
            assert str(error)=='injected lost committed completion reply'
            return original_dispatch(*args,**kwargs)
    monkeypatch.setattr(current.queue,'complete',complete)
    monkeypatch.setattr(current.dispatcher,'dispatch',retry_same_request)
    with envelope(current) as parent:result=train(current,parent,operation_id='lost-queue-reply')
    assert lost and current.worker.numerical_invocations-before==2
    assert all(current.queue.get(row['task_id'])['attempt']==1 for row in result.to_dict()['clients'])
    current.results.append(dict(control='lost_queue_reply',record=result.to_dict(),local_fits=2))


def test_missing_transfer_artifact_cannot_start_local_optimizer(current,monkeypatch):
    from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
    parent=current.registry.get_version(current.parent.to_dict()['version_id'])
    forbidden=cid_for_bytes(current.registry.artifact_path(parent['artifact']).read_bytes())
    original=current.cas.get_bytes
    def unavailable(cid):
        if cid==forbidden:raise FileNotFoundError('unavailable admitted parent checkpoint')
        return original(cid)
    monkeypatch.setattr(current.cas,'get_bytes',unavailable)
    monkeypatch.setattr(source,'_worker',lambda *a,**k:pytest.fail('missing artifact fitted'))
    with envelope(current) as parent:
        with pytest.raises(FileNotFoundError,match='unavailable admitted'):
            train(current,parent,operation_id='missing-artifact')
    row=current.registry.get_run('codebase-dispatched-fed:missing-artifact')
    assert row['status']=='failed' and row['lease'] is None
    assert current.registry.get_run_completion(row['run_id']) is None


def test_actual_source_change_after_local_fit_refuses_queue_and_native_completion(current,monkeypatch):
    original=source._worker;path=current.repo/'c.py';prior=path.read_bytes();before=current.worker.numerical_invocations
    def edit_after(*args,**kwargs):
        result=original(*args,**kwargs)
        path.write_text('def step(n: int) -> int:\n    return n + 99\n')
        return result
    monkeypatch.setattr(source,'_worker',edit_after)
    try:
        with envelope(current) as parent:
            with pytest.raises(Exception,match='source|head|repository|changed|differs'):
                train(current,parent,operation_id='stale-source')
    finally:path.write_bytes(prior)
    row=current.registry.get_run('codebase-dispatched-fed:stale-source')
    assert row['status']=='failed' and row['lease'] is None
    assert current.registry.get_run_completion(row['run_id']) is None
    assert current.worker.numerical_invocations-before==1
    tasks=[row for row in current.queue.list(task_types=[TASK_TYPE])
        if row['payload']['declaration']['payload']['work_binding']['round']['round_id']=='codebase-dispatched-fed:stale-source']
    assert len(tasks)==1 and tasks[0]['status']!='completed'


def test_gradient_mode_refuses_before_owner_or_queue_access(monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_sync import TrainingMode,GradientBackendUnavailable
    monkeypatch.setattr(source,'_native_owners',lambda *a,**k:pytest.fail('gradient mode accessed owner'))
    with pytest.raises(GradientBackendUnavailable):
        dispatched.train_current_dispatched_codebase_round(None,None,
            expected_head=None,registry=None,base_version_id=None,clients=[],operation_id='gradient',
            dispatcher=None,mode=TrainingMode.GRADIENT_SYNCHRONIZED)


def test_actual_two_native_subprocesses_overlap_and_reduce_identically(current,monkeypatch):
    import psutil
    import threading
    from ipfs_datasets_py.logic.software_contracts import codebase_parallel_dispatched_federation as parallel
    stop=threading.Event();peaks=[]
    def monitor():
        process=psutil.Process()
        while not stop.wait(.02):
            count=0
            for child in process.children(recursive=True):
                try:count+=any('codebase_feature_worker.py' in word for word in child.cmdline())
                except psutil.NoSuchProcess:pass
            peaks.append(count)
    watcher=threading.Thread(target=monitor,daemon=True);watcher.start()
    before=current.worker.numerical_invocations
    try:
        with envelope(current,slots=3) as parent:
            with parent.phase(bridge.RepositoryPhaseDemand('training',cpu_slots=3,memory_mb=3072,process_slots=3)) as phase:
                options=phase.native_options();options.pop('memory_mb')
                result=parallel.train_current_parallel_dispatched_codebase_round(current.index,current.repo,
                    expected_head=current.head,registry=current.registry,base_version_id=current.parent.to_dict()['version_id'],
                    clients=current.clients,operation_id='parallel',dispatcher=current.dispatcher,worker=current.worker,
                    artifacts=current.cas,max_workers=2,worker_memory_mb=1024,control_memory_mb=1024,
                    epochs=1,learning_rate=.002,**options)
    finally:stop.set();watcher.join(timeout=3)
    assert peaks and max(peaks)==2
    assert current.worker.numerical_invocations-before==2
    assert saved(current,result.to_dict()['version_id'])['state']==saved(current)['state']
    current.parallel=result
    current.results.append(dict(control='actual_parallel_overlap',native_process_peak=max(peaks),
        record=result.to_dict(),same_exact_reduced_state_as_sequential=True))


def test_parallel_indexed_restart_replay_never_scans_or_fits(current,monkeypatch):
    from ipfs_datasets_py.logic.software_contracts import codebase_parallel_dispatched_federation as parallel
    current.queue.close();current.queue=TaskQueue(str(current.root/'queue.duckdb'))
    current.dispatcher=CodebaseQueueDispatcher(current.queue,current.worker)
    monkeypatch.setattr(current.queue,'list',lambda *a,**k:pytest.fail('indexed replay scanned inventory'))
    monkeypatch.setattr(source,'_worker',lambda *a,**k:pytest.fail('historical indexed replay fitted'))
    result=parallel.load_parallel_dispatched_codebase_round(current.index,current.registry,
        current.parallel.to_dict()['version_id'],queue=current.queue,artifacts=current.cas)
    assert result.to_dict()==current.parallel.to_dict() and not result.observed_live


def test_parallel_cancellation_reaps_actual_workers_before_parent_release(current):
    import psutil
    import threading
    from ipfs_datasets_py.logic.software_contracts import codebase_parallel_dispatched_federation as parallel
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import LeaseCancelledError
    cancelled=threading.Event();stop=threading.Event();observed=[]
    def pids():
        found=[]
        for child in psutil.Process().children(recursive=True):
            try:
                if any('codebase_feature_worker.py' in word for word in child.cmdline()):found.append(child.pid)
            except psutil.NoSuchProcess:pass
        return found
    def cancel_actual():
        while not stop.wait(.01):
            current_pids=pids()
            if len(current_pids)>=2:
                observed.extend(current_pids);cancelled.set();return
    watcher=threading.Thread(target=cancel_actual,daemon=True);watcher.start()
    try:
        with envelope(current,slots=3) as parent:
            with parent.phase(bridge.RepositoryPhaseDemand('training',cpu_slots=3,memory_mb=3072,process_slots=3)) as phase:
                options=phase.native_options();options.pop('memory_mb');options['cancel_event']=cancelled
                with pytest.raises(LeaseCancelledError):
                    parallel.train_current_parallel_dispatched_codebase_round(current.index,current.repo,
                        expected_head=current.head,registry=current.registry,base_version_id=current.parent.to_dict()['version_id'],
                        clients=current.clients,operation_id='parallel-cancel',dispatcher=current.dispatcher,worker=current.worker,
                        artifacts=current.cas,max_workers=2,worker_memory_mb=1024,control_memory_mb=1024,
                        epochs=1,learning_rate=.002,**options)
                assert not pids()
    finally:stop.set();watcher.join(timeout=3)
    assert len(observed)>=2
    current.results.append(dict(control='actual_parallel_cancel',observed_worker_pids=observed,all_reaped=True))
