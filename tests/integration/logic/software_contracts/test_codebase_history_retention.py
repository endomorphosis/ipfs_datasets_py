"""Native durable leases/pins and actual GC of owned source-history envelopes."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from tests.integration.logic.software_contracts.test_codebase_ducklake_history import delivery
from tests.integration.logic.software_contracts.test_intent_codebase_catalog import case,current
from ipfs_datasets_py.duckdb_control.codebase_history_retention import ManagedCodebaseHistory,RetentionError,KIND,COMMAND,_derived
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry,RegistryError
from ipfs_datasets_py.ducklake.autoencoder_history import IsolatedNativeDuckLakeHistory


@pytest.fixture
def managed(delivery):
    owner=ManagedCodebaseHistory(delivery[3],delivery[4],delivery[5]/'managed-candidates',create=True)
    return delivery,owner


def stage(managed,operation='stage-source'):
    delivery,owner=managed
    return owner.stage(delivery[1],delivery[2]['record_cid'],operation=operation)['candidate_cid']


def test_real_producer_reader_history_delivery_pin_and_owned_artifact_deletion(managed):
    delivery,owner=managed
    retained=stage(managed,'retained-source');obsolete=stage(managed,'obsolete-source')
    with owner.read(retained,operation='reader') as value:
        assert value['request']==delivery[2]
        with pytest.raises(RetentionError,match='leases'):owner.quiesce('reader-active-gate')
    result=owner.deliver_and_pin(delivery[1],retained,operation='published-source',source_id='managed-fixture',output_directory=delivery[5]/'managed-journal')
    assert result['inspection']['retained_snapshot_records']==1
    source_path=delivery[0][0][1].artifacts.path_for(delivery[2]['record_cid']);source_bytes=source_path.read_bytes()
    unowned=owner.cas.put({'not':'a registered candidate'});unowned_path=owner.cas.path_for(unowned)
    gate=owner.quiesce('collect-gate')
    with pytest.raises(RetentionError,match='retained'):owner.collect(operation='try-pinned',gate_id=gate,candidate_cids=[retained])
    with pytest.raises(RetentionError):owner.collect(operation='try-unowned',gate_id=gate,candidate_cids=[unowned])
    with pytest.raises(RetentionError,match='gate'):owner.acquire('gate-refused-reader',kind='reader')
    deleted=owner.collect(operation='collect-obsolete',gate_id=gate,candidate_cids=[obsolete])
    assert deleted['deleted_candidate_cids']==[obsolete] and not owner.cas.path_for(obsolete).exists()
    assert source_path.read_bytes()==source_bytes and unowned_path.exists() and owner.cas.path_for(retained).exists()
    assert owner.collect(operation='collect-obsolete',gate_id=gate,candidate_cids=[obsolete])['historical_replay'] is True
    assert owner.inspect_pins()['pins'][0]['candidate_cid']==retained
    assert result['inspection']['records'][0]['snapshot_id']==owner.inspect_pins()['pins'][0]['snapshot']['snapshot_id']
    owner.unquiesce('release-gate',gate)
    owner.unpin('release-pin','published-source')
    gate=owner.quiesce('collect-unpinned-gate')
    owner.collect(operation='collect-unpinned',gate_id=gate,candidate_cids=[retained])
    assert owner.inspect_pins()['pins']==[]
    assert delivery[4]._connection.execute('SELECT count(*) FROM history.events').fetchone()[0]>0


def test_exact_retention_operation_and_lost_response_replay(managed,monkeypatch):
    delivery,owner=managed
    original=delivery[3]._mutate
    def lost(*args,**kwargs):
        value=original(*args,**kwargs)
        if args[1]==COMMAND:raise ConnectionError('lost retention commit reply')
        return value
    with monkeypatch.context() as patch:
        patch.setattr(delivery[3],'_mutate',lost)
        with pytest.raises(ConnectionError):owner.acquire('lost-acquire',kind='producer')
    lease=owner.acquire('lost-acquire',kind='producer')
    with pytest.raises(RegistryError,match='different payload'):owner.acquire('lost-acquire',kind='reader')
    with pytest.raises(RetentionError):owner.quiesce('live-producer')
    owner.release('release-lost',lease)
    with pytest.raises(RetentionError,match='no longer active'):owner.acquire('lost-acquire',kind='producer')


def test_actual_thread_reader_excludes_quiescence_and_close_until_consumption_finishes(managed):
    delivery,owner=managed;cid=stage(managed)
    entered=threading.Event();finish=threading.Event();completed=threading.Event();failures=[]
    def reader():
        try:
            with owner.read(cid,operation='thread-reader'):
                entered.set();assert finish.wait(15)
        except BaseException as error:failures.append(error)
    def gate():
        try:owner.quiesce('thread-gate');completed.set()
        except BaseException as error:failures.append(error)
    thread=threading.Thread(target=reader);thread.start();assert entered.wait(15)
    competitor=threading.Thread(target=gate);competitor.start()
    assert not completed.wait(.1)
    finish.set();thread.join(15);competitor.join(15)
    assert not failures and completed.is_set()
    with pytest.raises(RetentionError):owner.stage(delivery[1],delivery[2]['record_cid'],operation='while-quiescent')


@pytest.mark.parametrize('damage',['symlink','hardlink','bytes','oversize','directory'])
def test_unsafe_candidate_bytes_or_aliases_never_deleted(managed,damage):
    delivery,owner=managed;cid=stage(managed);path=owner.cas.path_for(cid)
    if damage=='symlink':
        real=delivery[5]/'alias-target';path.rename(real);path.symlink_to(real)
    elif damage=='hardlink':os.link(path,delivery[5]/'other-hardlink')
    elif damage=='bytes':path.write_text('{}')
    elif damage=='oversize':path.write_bytes(b'x'*(24*1024+1))
    else:path.unlink();path.mkdir()
    gate=owner.quiesce('unsafe-gate')
    with pytest.raises((ValueError,OSError)):owner.collect(operation='unsafe-collect',gate_id=gate,candidate_cids=[cid])
    assert path.exists() or path.is_symlink()
    assert owner.state()['collection'] is None


def test_missing_candidate_without_prior_intent_cannot_be_claimed_as_collected(managed):
    _,owner=managed;cid=stage(managed);owner.cas.path_for(cid).unlink();gate=owner.quiesce('missing-gate')
    with pytest.raises(FileNotFoundError):owner.collect(operation='missing',gate_id=gate,candidate_cids=[cid])
    assert not owner.state()['candidates'][cid]['deleted']


def test_prepared_plan_fences_replacement_and_pending_gate_release(managed,monkeypatch):
    _,owner=managed;cid=stage(managed);gate=owner.quiesce('replace-gate')
    def fail(target):raise ConnectionError('before unlink')
    with monkeypatch.context() as patch:
        patch.setattr(owner,'_unlink_prepared',fail)
        with pytest.raises(ConnectionError):owner.collect(operation='replace',gate_id=gate,candidate_cids=[cid])
    with pytest.raises(RetentionError,match='pending'):owner.unquiesce('release-pending',gate)
    path=owner.cas.path_for(cid);data=path.read_bytes();replacement=path.with_suffix('.new');replacement.write_bytes(data);replacement.replace(path)
    with pytest.raises(RetentionError,match='replaced'):owner.collect(operation='replace',gate_id=gate,candidate_cids=[cid])
    assert path.exists()


def test_native_profile_control_log_tamper_and_size_preflight_refuse(managed):
    delivery,owner=managed
    with delivery[3]._transaction() as cx:
        cx.execute('UPDATE autoencoder_control.events SET event_data=? WHERE kind=?',[json.dumps({'invented':'state'}),KIND])
    with pytest.raises(RetentionError):owner.state()
    with delivery[3]._transaction() as cx:
        cx.execute("UPDATE autoencoder_control.events SET event_data=repeat('x',49153) WHERE kind=?",[KIND])
    with pytest.raises(RetentionError,match='bounded'):owner.state()


def test_actual_process_crash_after_unlink_recovers_intent_and_preserves_retained_pin(managed):
    delivery,owner=managed;retained=stage(managed,'retained');obsolete=stage(managed,'obsolete')
    owner.deliver_and_pin(delivery[1],retained,operation='retained-pin',source_id='managed-fixture',output_directory=delivery[5]/'pin-journal')
    gate=owner.quiesce('crash-gate');root=delivery[5]
    (root/'gc-input.json').write_text(json.dumps(dict(retained=retained,obsolete=obsolete,gate=gate)))
    delivery[3].close();delivery[4].close()
    script='''
import json,os,sys
from pathlib import Path
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.ducklake.autoencoder_history import IsolatedNativeDuckLakeHistory
from ipfs_datasets_py.duckdb_control.codebase_history_retention import ManagedCodebaseHistory
root=Path(sys.argv[1]);mode=sys.argv[2];data=json.loads((root/'gc-input.json').read_text())
with AutoencoderRegistry(root/'delivery.duckdb',root/'delivery-artifacts') as registry, IsolatedNativeDuckLakeHistory(root/'history') as sink:
    owner=ManagedCodebaseHistory(registry,sink,root/'managed-candidates')
    if mode=='crash':
        original=owner._unlink_prepared
        def crash(target):original(target);os._exit(92)
        owner._unlink_prepared=crash
    result=owner.collect(operation='crash-collection',gate_id=data['gate'],candidate_cids=[data['obsolete']])
    print(json.dumps(dict(result=result,pins=owner.inspect_pins(),state=owner.state(),retained=owner.cas.path_for(data['retained']).exists(),obsolete=owner.cas.path_for(data['obsolete']).exists()),sort_keys=True))
'''
    def run(mode):return subprocess.run([sys.executable,'-c',script,str(root),mode],capture_output=True,text=True,timeout=45,env=dict(os.environ))
    crashed=run('crash');assert crashed.returncode==92,crashed.stderr
    recovered=run('recover');assert recovered.returncode==0,recovered.stderr
    value=json.loads(recovered.stdout.splitlines()[-1])
    assert value['retained'] is True and value['obsolete'] is False
    assert value['state']['collection'] is None and value['state']['gate']==gate
    assert value['pins']['pins'][0]['candidate_cid']==retained
    repeated=run('recover');assert repeated.returncode==0,repeated.stderr
    repeat=json.loads(repeated.stdout.splitlines()[-1]);assert repeat['result']['historical_replay'] is True
    assert repeat['state']==value['state'] and repeat['pins']==value['pins']


def test_native_reopen_stale_owner_lease_requires_explicit_reconciliation(managed):
    delivery,owner=managed;lease=owner.acquire('abandoned-producer',kind='producer');delivery[3].close()
    with AutoencoderRegistry(delivery[5]/'delivery.duckdb',delivery[5]/'delivery-artifacts') as registry:
        reopened=ManagedCodebaseHistory(registry,delivery[4],delivery[5]/'managed-candidates')
        with pytest.raises(RetentionError):reopened.quiesce('before-recovery')
        with pytest.raises(RetentionError,match='stale'):reopened.release('stale-release',lease)
        assert reopened.recover_abandoned_leases('explicit-native-recovery')['recovered_leases']==['abandoned-producer']
        assert reopened.quiesce('after-recovery')=='after-recovery'
        with pytest.raises(RegistryError):owner.acquire('closed-owner',kind='reader')


def test_deleted_latest_event_cannot_roll_back_live_pin_or_lease_state(managed):
    delivery,owner=managed
    lease=owner.acquire('newest-live-reader',kind='reader')
    with delivery[3]._transaction() as cx:
        events=cx.execute('SELECT event_id,event_data FROM autoencoder_control.events WHERE kind=?',[KIND]).fetchall()
        newest=max(events,key=lambda row:json.loads(row[1])['sequence'])[0]
        cx.execute('DELETE FROM autoencoder_control.events WHERE event_id=?',[newest])
    with pytest.raises(RetentionError,match='completeness'):owner.quiesce('silently-rolled-back-gate')


def test_operation_payload_or_receipt_drift_refuses_gc_before_deletion(managed):
    delivery,owner=managed;cid=stage(managed);gate=owner.quiesce('receipt-gate')
    with delivery[3]._transaction() as cx:
        cx.execute("UPDATE autoencoder_control.operations SET payload_digest=repeat('0',64) WHERE operation_id='receipt-gate'")
    with pytest.raises(RetentionError,match='binding'):owner.collect(operation='bad-receipt',gate_id=gate,candidate_cids=[cid])
    assert owner.cas.path_for(cid).exists()


def test_durable_collection_completion_response_loss_does_not_repeat_physical_delete(managed,monkeypatch):
    delivery,owner=managed;cid=stage(managed);gate=owner.quiesce('completion-gate')
    original=delivery[3]._mutate
    def lose_complete(*args,**kwargs):
        result=original(*args,**kwargs)
        if args[1]==COMMAND and args[2]['action']=='complete_collection':raise ConnectionError('lost completion reply')
        return result
    with monkeypatch.context() as patch:
        patch.setattr(delivery[3],'_mutate',lose_complete)
        with pytest.raises(ConnectionError):owner.collect(operation='lost-completion',gate_id=gate,candidate_cids=[cid])
    def unexpected(target):raise AssertionError('physical delete repeated')
    monkeypatch.setattr(owner,'_unlink_prepared',unexpected)
    assert owner.collect(operation='lost-completion',gate_id=gate,candidate_cids=[cid])['historical_replay'] is True
    with pytest.raises(RetentionError):owner.collect(operation='lost-completion',gate_id='other-gate',candidate_cids=[cid])
    assert owner.stage(delivery[1],delivery[2]['record_cid'],operation='stage-source')['candidate_deleted'] is True


def test_managed_namespace_replacement_and_reopen_refuse(managed):
    delivery,owner=managed;cid=stage(managed)
    directory=owner.cas.structured_root;directory.rename(owner.root/'structured-original');directory.mkdir()
    with pytest.raises(RetentionError,match='namespace'):owner.state()
    with pytest.raises(RetentionError,match='foreign'):ManagedCodebaseHistory(delivery[3],delivery[4],owner.root)
    assert (owner.root/'structured-original'/cid[:4]/cid).exists()


def test_native_operation_and_event_capacity_bounds_fail_closed(managed,monkeypatch):
    from ipfs_datasets_py.duckdb_control import codebase_history_retention as module
    delivery,owner=managed
    with monkeypatch.context() as patch:
        patch.setattr(module,'MAX_EVENTS',1)
        with pytest.raises(RetentionError,match='capacity'):owner.acquire('beyond-event-cap',kind='reader')
    with monkeypatch.context() as patch:
        patch.setattr(module,'MAX_NATIVE_OPERATIONS',0)
        with pytest.raises(RetentionError,match='operation audit bound'):owner.state()
    assert not owner.state()['leases']


def test_failed_producer_io_releases_durable_lease_and_never_registers_dummy_blob(managed,monkeypatch):
    delivery,owner=managed
    def fail(value):raise OSError('injected candidate disk error')
    monkeypatch.setattr(owner.cas,'put',fail)
    with pytest.raises(OSError):stage(managed)
    assert owner.state()['leases']=={} and owner.state()['candidates']=={}
    assert owner.quiesce('after-producer-failure')=='after-producer-failure'


def test_pin_tampered_acknowledgement_does_not_claim_retained_snapshot(managed):
    delivery,owner=managed;cid=stage(managed)
    result=owner.deliver_and_pin(delivery[1],cid,operation='snapshot-pin',source_id='managed-fixture',output_directory=delivery[5]/'snapshot-journal')
    event_id=result['inspection']['records'][0]['event_id']
    with delivery[3]._transaction() as cx:
        receipt=json.loads(cx.execute("SELECT receipt FROM autoencoder_control.outbox WHERE event_id=? AND consumer='ducklake'",[event_id]).fetchone()[0]);receipt['snapshot_id']+=999
        cx.execute("UPDATE autoencoder_control.outbox SET receipt=? WHERE event_id=? AND consumer='ducklake'",[json.dumps(receipt),event_id])
    with pytest.raises(ValueError,match='acknowledgement'):owner.inspect_pins()
    assert owner.cas.path_for(cid).exists()


def test_reserve_native_control_capacity_before_unlink_then_complete_at_exact_bound(managed,monkeypatch):
    from ipfs_datasets_py.duckdb_control import codebase_history_retention as module
    delivery,owner=managed;cid=stage(managed);gate=owner.quiesce('capacity-gate')
    with delivery[3]._transaction() as cx:
        events=cx.execute('SELECT count(*) FROM autoencoder_control.events WHERE kind=?',[KIND]).fetchone()[0]
    monkeypatch.setattr(module,'MAX_EVENTS',events+2)
    with pytest.raises(RetentionError,match='reserve'):owner.collect(operation='capacity-collect',gate_id=gate,candidate_cids=[cid])
    assert owner.cas.path_for(cid).exists() and owner.state()['collection'] is None
    monkeypatch.setattr(module,'MAX_EVENTS',events+3)
    assert owner.collect(operation='capacity-collect',gate_id=gate,candidate_cids=[cid])['deleted_candidate_cids']==[cid]
    owner.unquiesce('capacity-release',gate)
    assert owner.state()['gate'] is None and not owner.cas.path_for(cid).exists()


def test_second_profile_foreign_registry_and_namespace_adoption_refuse(managed):
    delivery,owner=managed
    with pytest.raises(RetentionError,match='foreign'):ManagedCodebaseHistory(delivery[3],delivery[4],delivery[5]/'second-managed',create=True)
    assert owner.state()['descriptor']==owner.descriptor
    with AutoencoderRegistry(delivery[5]/'foreign.duckdb',delivery[5]/'foreign-artifacts') as other:
        with pytest.raises(RetentionError,match='missing durable'):ManagedCodebaseHistory(other,delivery[4],owner.root)
    with pytest.raises(RetentionError,match='new dedicated'):ManagedCodebaseHistory(delivery[3],delivery[4],owner.root,create=True)
