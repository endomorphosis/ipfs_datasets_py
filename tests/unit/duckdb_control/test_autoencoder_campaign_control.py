"""Campaign control history and one actual injected B2 transport/replay path.

Most cases use metadata-only fake B2 reports and tiny registry candidates to
isolate durable control behavior. They are never worker acceptance evidence.
The final case executes real shared-target/sparse/Arrow owner validation with
explicit injected worker/resource hooks. No listener, native training or network.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import socket
import subprocess
import threading
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.duckdb_control import autoencoder_campaign_control as control_module
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry, RegistryError
from ipfs_datasets_py.duckdb_control.contracts import canonical_json_bytes
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_campaign_owned_training as preparation
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_campaign_owned_execution as execution
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as resources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_campaign_training_request as codec
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_campaign_owned_training import (
    case, _prepare_owned, _request, _tables,
)

ERRORS = (ValueError, RegistryError, OSError)


def _forbidden(*args, **kwargs):
    pytest.fail('this boundary must not execute native/model/network work')


@pytest.fixture(autouse=True)
def no_native(monkeypatch):
    monkeypatch.setattr(socket.socket, 'connect', _forbidden)
    monkeypatch.setattr(socket.socket, 'connect_ex', _forbidden)
    monkeypatch.setattr(subprocess, 'Popen', _forbidden)
    monkeypatch.setattr(resources.DaemonResourceReservation, '__enter__', _forbidden)


@pytest.fixture
def protocol(case, monkeypatch):
    handle = _prepare_owned(case)
    controller = control_module.OwnedCampaignControl(case.registry, worker_id='campaign-owner',
        prepared_campaigns={handle['request_artifact']['sha256']: handle})
    value = SimpleNamespace(case=case, registry=case.registry, handle=handle,
        ref=handle['request_artifact'], request=_request(case, handle), control=controller,
        controls=[controller], calls=[])
    monkeypatch.setattr(preparation, 'execute_prepared_campaign_training', _fake_b2(value))
    try:
        yield value
    finally:
        for item in value.controls:
            item.close()


def _control(protocol, registry=None):
    controller = control_module.OwnedCampaignControl(registry or protocol.registry,
        worker_id='campaign-owner', prepared_campaigns={protocol.ref['sha256']:protocol.handle})
    protocol.controls.append(controller)
    return controller


def _fake_b2(protocol):
    def run(registry, ref, *, max_new_batches, max_workers):
        request = codec.decode_campaign_training_request(registry.artifact_path(ref).read_bytes())
        protocol.calls.append((deepcopy(ref), max_new_batches, max_workers))
        selected = [batch for batch in request['batches'] if registry.get_run(batch['run_id'])['status'] == 'queued'][:max_new_batches]
        for batch in selected:
            run_id = batch['run_id']
            lease = registry.claim_run('fake-claim:' + run_id, run_id, request['worker_id'])['lease']
            artifact = registry.get_version(batch['base_version_id'])['artifact']
            registry.complete_run('fake-complete:' + run_id, lease, artifact,
                {'admitted':False, 'execution_mode':'injected_test', 'control_fixture_only':True})
        rows, completed, deferred = [], [], []
        for batch in request['batches']:
            run = registry.get_run(batch['run_id'])
            row = {'batch_id':batch['batch_id'],'run_id':batch['run_id'],'job_id':batch['job_id'],
                   'registry_status':run['status'],'completion_verified':False,
                   'supervised_native_execution_verified':False,'status':'queued'}
            durable = registry.get_run_completion(batch['run_id'])
            if durable is not None:
                version = durable['candidate_version']
                row.update(status='completed', completion_verified=True, candidate_version_id=version['version_id'],
                           candidate=version['artifact'], execution_mode='injected_test')
                completed.append(batch['run_id'])
            else:
                deferred.append(batch['run_id'])
            rows.append(row)
        return {'schema_version':execution.STATUS_SCHEMA,'request_artifact':deepcopy(ref),
                'status':'ready' if deferred else 'complete','batch_count':len(rows),'batches':rows,
                'dispatched_run_ids':[row['run_id'] for row in selected], 'completed_run_ids':completed,
                'deferred_run_ids':deferred,'pending_operation_slots':[],'unresolved_operation_slots':[],
                'execution_mode':'injected_test','native_execution_verified':False,
                **{name:False for name in control_module._AUTHORITY_FALSE}}
    return run


def _submit(protocol):
    return protocol.control.submit('submit-once', protocol.ref)


def test_submission_is_exact_durable_intent_without_execution(protocol, monkeypatch):
    before = _tables(protocol.registry)
    assert protocol.control.read(protocol.ref)['status'] == 'not_submitted'
    assert protocol.control.resolve('submit-once',protocol.ref)['resolution'] == 'missing'
    accepted = _submit(protocol)
    monkeypatch.setattr(control_module.DurableDaemonOperationJournal, '__init__', _forbidden)
    assert _submit(protocol) == accepted
    assert protocol.control.resolve('submit-once',protocol.ref)['receipt'] == accepted
    assert protocol.control.read(protocol.ref)['status'] == 'accepted'
    assert not protocol.calls
    after = _tables(protocol.registry)
    assert {k:v for k,v in before.items() if k != 'operations'} == {k:v for k,v in after.items() if k != 'operations'}
    assert all(not Path(spec.output_directory).exists() for spec in protocol.case.specs)


@pytest.mark.parametrize('change', ['digest','bytes','extra_path','boolean_bytes','zero_bytes'])
def test_remote_descriptor_cannot_retarget_or_supply_paths(protocol, change):
    ref = deepcopy(protocol.ref)
    if change == 'digest': ref['sha256'] = '0' * 64
    elif change == 'bytes': ref['bytes'] += 1
    elif change == 'extra_path': ref['path'] = '/elsewhere'
    elif change == 'boolean_bytes': ref['bytes'] = True
    else: ref['bytes'] = 0
    before = _tables(protocol.registry)
    for method in (lambda:protocol.control.submit('bad',ref),lambda:protocol.control.read(ref),
                   lambda:protocol.control.resolve('bad',ref)):
        with pytest.raises(ERRORS): method()
    assert _tables(protocol.registry) == before and not protocol.calls


@pytest.mark.parametrize('change', ['worker','journal','registration','key'])
def test_constructor_rejects_changed_prebinding(protocol, change):
    handle, worker = deepcopy(protocol.handle), 'campaign-owner'
    key = protocol.ref['sha256']
    if change == 'worker': worker = 'other-owner'
    elif change == 'journal': handle['journal_path'] += '-other'
    elif change == 'registration': handle['registration']['status'] = 'other'
    else: key = '0' * 64
    with pytest.raises(ERRORS):
        control_module.OwnedCampaignControl(protocol.registry,worker_id=worker,prepared_campaigns={key:handle})
    assert not protocol.calls


@pytest.mark.parametrize('command', [control_module._SUBMIT,control_module._START,control_module._FINISH])
def test_lost_committed_responses_resolve_same_operation_without_second_call(protocol, monkeypatch, command):
    original, losses = protocol.registry._mutate, []
    def lose(operation_id, actual_command, payload, apply):
        result = original(operation_id, actual_command, payload, apply)
        if actual_command == command and not losses:
            losses.append(operation_id)
            raise OSError('lost committed response')
        return result
    monkeypatch.setattr(protocol.registry,'_mutate',lose)
    accepted = _submit(protocol)
    report = protocol.control.execute_pending(max_new_batches=2)
    assert report['results'][0]['status'] == 'complete' and len(protocol.calls) == 1 and len(losses) == 1
    assert _submit(protocol) == accepted
    assert protocol.control.execute_pending()['results'][0]['status'] == 'complete'
    assert len(protocol.calls) == 1


@pytest.mark.parametrize('command', [control_module._START,control_module._FINISH])
def test_uncertain_phase_after_restart_never_reexecutes(protocol, monkeypatch, command):
    original_mutate, original_resolve = protocol.registry._mutate, protocol.registry.resolve_operation
    def lose(operation_id, actual_command, payload, apply):
        if actual_command == command:
            if command == control_module._START:
                original_mutate(operation_id,actual_command,payload,apply)
            raise OSError('response unavailable')
        return original_mutate(operation_id,actual_command,payload,apply)
    def resolve(operation_id, actual_command, payload):
        if actual_command == command: return None
        return original_resolve(operation_id,actual_command,payload)
    _submit(protocol)
    monkeypatch.setattr(protocol.registry,'_mutate',lose)
    monkeypatch.setattr(protocol.registry,'resolve_operation',resolve)
    first = protocol.control.execute_pending(max_new_batches=1)
    assert first['results'][0]['status'] == 'recovery_required'
    calls = len(protocol.calls)
    assert calls == (0 if command == control_module._START else 1)
    monkeypatch.setattr(protocol.registry,'_mutate',original_mutate)
    monkeypatch.setattr(protocol.registry,'resolve_operation',original_resolve)
    restarted = _control(protocol)
    assert restarted.execute_pending(max_new_batches=2)['results'][0]['status'] == 'recovery_required'
    assert len(protocol.calls) == calls
    assert protocol.registry.get_run(protocol.case.specs[-1].run_id)['status'] == 'queued'


def test_partial_progress_needs_a_new_explicit_owner_drain(protocol, monkeypatch):
    _submit(protocol)
    first = protocol.control.execute_pending()
    assert first['results'][0]['status'] == 'ready' and len(protocol.calls) == 1
    assert first['remaining_batch_budget'] == 0
    monkeypatch.setattr(control_module.DurableDaemonOperationJournal,'__init__',_forbidden)
    polled = protocol.control.read(protocol.ref)
    assert polled['progress']['execution_mode'] == 'injected_test'
    assert polled['current_artifact_availability_checked'] is False
    assert _submit(protocol)['status'] == 'accepted' and len(protocol.calls) == 1
    second = protocol.control.execute_pending()
    assert second['results'][0]['status'] == 'complete' and len(protocol.calls) == 2
    assert second['results'][0]['drain_count'] == 2
    assert second['results'][0]['progress']['recorded_native_execution_verified'] is False


def test_start_without_call_remains_recovery_even_if_no_original_attempt(protocol, monkeypatch):
    _submit(protocol)
    monkeypatch.setattr(preparation,'execute_prepared_campaign_training',lambda *a,**k: (_ for _ in ()).throw(OSError('before B2')))
    assert protocol.control.execute_pending()['results'][0]['status'] == 'recovery_required'
    monkeypatch.setattr(preparation,'execute_prepared_campaign_training',_forbidden)
    assert _control(protocol).execute_pending()['results'][0]['status'] == 'recovery_required'
    assert all(protocol.registry.get_run(spec.run_id)['attempt'] == 0 for spec in protocol.case.specs)


def test_distinct_submission_cannot_replace_the_request_binding(protocol):
    accepted = _submit(protocol)
    with pytest.raises(ERRORS): protocol.control.submit('replacement',protocol.ref)
    assert protocol.control.resolve('submit-once',protocol.ref)['receipt'] == accepted
    assert protocol.control.resolve('replacement',protocol.ref)['resolution'] == 'missing'


@pytest.mark.parametrize('bounds', [{'max_new_batches':0},{'max_new_batches':True},{'max_new_batches':65},
    {'max_workers':0},{'max_workers':True},{'max_workers':3}])
def test_owner_drain_bounds_reject_before_start(protocol,bounds):
    _submit(protocol)
    before = _tables(protocol.registry)
    with pytest.raises(ERRORS): protocol.control.execute_pending(**bounds)
    assert _tables(protocol.registry) == before and not protocol.calls


def test_two_controllers_contend_on_durable_start_and_reads_do_not_lock_journal(protocol,monkeypatch):
    _submit(protocol)
    other = _control(protocol)
    entered, finish = threading.Event(), threading.Event()
    original = preparation.execute_prepared_campaign_training
    def blocked(*args,**kwargs):
        entered.set()
        assert finish.wait(5)
        return original(*args,**kwargs)
    monkeypatch.setattr(preparation,'execute_prepared_campaign_training',blocked)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(protocol.control.execute_pending,max_new_batches=1)
        assert entered.wait(5)
        try:
            monkeypatch.setattr(control_module.DurableDaemonOperationJournal,'__init__',_forbidden)
            assert protocol.control.read(protocol.ref)['status'] == 'running'
            assert other.read(protocol.ref)['status'] == 'recovery_required'
            assert other.execute_pending(max_new_batches=2)['results'][0]['status'] == 'recovery_required'
            with pytest.raises(ValueError): protocol.control.close()
        finally:
            finish.set()
        assert first.result(timeout=10)['results'][0]['status'] == 'ready'
    assert len(protocol.calls) == 1


def test_request_union_and_total_budget_across_independent_selections(case,monkeypatch):
    first = _prepare_owned(case,selected_batch_ids=case.selected[:1])
    second_path = case.root/'second-control'; second_path.mkdir()
    second = _prepare_owned(case,selected_batch_ids=case.selected[1:],output_root=str(second_path))
    handles = {handle['request_artifact']['sha256']:handle for handle in (first,second)}
    stub = SimpleNamespace(calls=[])
    monkeypatch.setattr(preparation,'execute_prepared_campaign_training',_fake_b2(stub))
    with control_module.OwnedCampaignControl(case.registry,worker_id='campaign-owner',prepared_campaigns=handles) as control:
        assert control.run_ids == frozenset(spec.run_id for spec in case.specs)
        for index,handle in enumerate((first,second)): control.submit('submit-'+str(index),handle['request_artifact'])
        first_result = control.execute_pending()
        assert len(stub.calls) == 1 and sum(row['status']=='complete' for row in first_result['results']) == 1
        assert sum(row['status']=='accepted' for row in first_result['results']) == 1
        second_result = control.execute_pending()
        assert len(stub.calls) == 2 and all(row['status']=='complete' for row in second_result['results'])
        assert [call[0]['sha256'] for call in stub.calls] == sorted(handles)


@pytest.mark.parametrize('kind',['phase_digest','finish_candidate','finish_mode'])
def test_corrupted_durable_phase_or_candidate_is_not_completed_authority(protocol,kind):
    accepted = _submit(protocol)
    assert protocol.control.execute_pending(max_new_batches=2)['results'][0]['status'] == 'complete'
    operation_id = control_module._phase_id(accepted['control_operation_id'],1,'finish')
    with protocol.registry._transaction() as connection:
        digest,raw = connection.execute('SELECT payload_digest,receipt FROM autoencoder_control.operations WHERE operation_id=?',[operation_id]).fetchone()
        if kind == 'phase_digest': digest = '0'*64
        else:
            receipt = json.loads(raw)
            if kind == 'finish_candidate': receipt['summary']['completed'][0]['candidate_version_id'] = 'forged'
            else: receipt['summary']['execution_mode'] = 'native_training'
            payload = {k:v for k,v in receipt.items() if k not in ('schema','operation_id','command','admitted')}
            digest = protocol.registry._command_digest(operation_id,control_module._FINISH,payload)
            raw = canonical_json_bytes(receipt).decode()
        connection.execute('UPDATE autoencoder_control.operations SET payload_digest=?,receipt=? WHERE operation_id=?',[digest,raw,operation_id])
    with pytest.raises(ERRORS): protocol.control.read(protocol.ref)
    calls = len(protocol.calls)
    assert protocol.control.execute_pending()['results'][0]['status'] == 'recovery_required'
    assert len(protocol.calls) == calls


def test_history_checks_each_completed_candidate_once_per_read_without_persistent_cache(protocol,monkeypatch):
    _submit(protocol)
    protocol.control.execute_pending(); protocol.control.execute_pending()
    calls=[]; original=protocol.registry.get_run_completion
    def counted(run_id):
        calls.append(run_id);return original(run_id)
    monkeypatch.setattr(protocol.registry,'get_run_completion',counted)
    assert protocol.control.read(protocol.ref)['status']=='complete'
    expected=[spec.run_id for spec in protocol.case.specs]
    assert calls==expected
    protocol.control.read(protocol.ref)
    assert calls==expected+expected


def test_missing_journal_after_submission_does_not_get_recreated_by_read(protocol,monkeypatch):
    _submit(protocol)
    Path(protocol.handle['journal_path']).unlink()
    monkeypatch.setattr(control_module.DurableDaemonOperationJournal,'__init__',_forbidden)
    assert protocol.control.read(protocol.ref)['status']=='accepted'
    assert _submit(protocol)['status']=='accepted'
    assert not Path(protocol.handle['journal_path']).exists()


@pytest.fixture
def isolated_target_provenance(monkeypatch):
    import platform
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_target_preparation as targets
    prior_context, prior_platform = targets._PROCESS_CONTEXT, platform.platform
    # One isolated synthetic producer lifetime. Normal source/runtime checks
    # stay active across target construction and every B2 worker verification.
    # Teardown must restore both the provider and its resident fingerprint.
    with monkeypatch.context() as isolated:
        isolated.setattr(platform,'platform',lambda:'campaign-control-injected-platform')
        isolated.setattr(targets,'_PROCESS_CONTEXT',None)
        yield targets
    assert targets._PROCESS_CONTEXT is prior_context
    assert platform.platform is prior_platform


def test_actual_injected_b2_targets_sparse_arrow_path_preserves_original_jobs(
        tmp_path,monkeypatch,isolated_target_provenance):
    from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_campaign_owned_execution import (
        _case, _run, _completed,
    )
    from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_campaign_shared_sparse_arrow import _assert_transport_result
    with AutoencoderRegistry(tmp_path/'owner.duckdb',tmp_path/'artifacts') as registry:
        actual = _case(registry,tmp_path,monkeypatch,arrow=True,artifact_format='bundle')
        calls=[]
        def injected(owner,ref,*,max_new_batches,max_workers):
            assert owner is registry and ref==actual.prepared['request_artifact']
            calls.append((max_new_batches,max_workers))
            return _run(actual,max_new_batches=max_new_batches,max_workers=max_workers)
        monkeypatch.setattr(preparation,'execute_prepared_campaign_training',injected)
        ref=actual.prepared['request_artifact']
        with control_module.OwnedCampaignControl(registry,worker_id=actual.request['worker_id'],
                prepared_campaigns={ref['sha256']:actual.prepared}) as control:
            control.submit('actual-injected',ref)
            result=control.execute_pending(max_new_batches=2,max_workers=2)
            assert result['results'][0]['status']=='complete' and calls==[(2,2)]
            progress=result['results'][0]['progress']
            assert progress['execution_mode']=='injected_test' and progress['recorded_native_execution_verified'] is False
            for spec in actual.combined.specs:
                completed=_completed(registry,spec)
                _assert_transport_result(registry,completed,spec,actual.observations[spec.run_id],actual.combined,
                                         arrow=True,artifact_format='bundle')
            before=dict(actual.observations)
            assert control.execute_pending()['results'][0]['status']=='complete'
            assert actual.observations==before and calls==[(2,2)]
            assert all(item.status=='released' for item in actual.reservations.instances)
            assert registry.pending_outbox('huggingface')==[]
            assert registry.resolve_head('english-0','best')['version_id']==actual.combined.specs[0].base_version_id
        # The fixture isolates a lifetime, not the guard: runtime drift during
        # that same lifetime must still fail and leave its fingerprint intact.
        import platform
        prior = isolated_target_provenance._PROCESS_CONTEXT
        assert prior is not None
        with monkeypatch.context() as drift:
            drift.setattr(platform,'platform',lambda:'changed-injected-platform')
            with pytest.raises(ValueError,match='code/runtime changed in resident process'):
                isolated_target_provenance.target_snapshot_config(actual.combined.specs[0].training_config)
        assert isolated_target_provenance._PROCESS_CONTEXT is prior


def test_finish_command_fits_all_64_maximum_length_run_ids_before_training():
    request={'batches':[{'run_id': str(index).zfill(3)+'r'*253} for index in range(64)]}
    ref={'sha256':'f'*64,'bytes':codec.MAX_REQUEST_BYTES}
    size=control_module._check_finish_capacity(AutoencoderRegistry,request,ref)
    assert size<=65_536
    assert len(request['batches'])==64 and all(len(row['run_id'])==256 for row in request['batches'])


def test_close_between_initial_check_and_drain_lock_cannot_start_work(protocol,monkeypatch):
    _submit(protocol)
    original=protocol.control._ensure_open
    seen=[]
    def checked():
        original()
        if not seen:
            seen.append(True)
            protocol.control.close()
    monkeypatch.setattr(protocol.control,'_ensure_open',checked)
    with pytest.raises(ValueError,match='closed'):
        protocol.control.execute_pending()
    assert not protocol.calls
    assert all(protocol.registry.get_run(spec.run_id)['attempt']==0 for spec in protocol.case.specs)


def test_owner_restart_preserves_finished_prefix_and_executes_only_remaining_job(protocol):
    _submit(protocol)
    assert protocol.control.execute_pending()['results'][0]['status']=='ready'
    first=protocol.case.specs[0].run_id
    before=protocol.registry.get_run_completion(first)
    database,artifacts=protocol.registry.database_path,protocol.registry.artifact_root
    protocol.control.close();protocol.registry.close()
    with AutoencoderRegistry(database,artifacts) as registry:
        with control_module.OwnedCampaignControl(registry,worker_id='campaign-owner',
                prepared_campaigns={protocol.ref['sha256']:protocol.handle}) as controller:
            assert controller.read(protocol.ref)['status']=='ready'
            assert controller.execute_pending()['results'][0]['status']=='complete'
            assert registry.get_run_completion(first)==before
    assert len(protocol.calls)==2
