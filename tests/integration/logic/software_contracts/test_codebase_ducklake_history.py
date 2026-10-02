"""Actual pinned native DuckLake codebase history, no training or publication."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.integration.logic.software_contracts.test_intent_codebase_catalog import case,current
from ipfs_datasets_py.duckdb_control import codebase_ducklake_history as module
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry,RegistryError
from ipfs_datasets_py.duckdb_control.intent_codebase_catalog import IntentCodebaseCatalog
from ipfs_datasets_py.ducklake.autoencoder_history import IsolatedNativeDuckLakeHistory,HistoryError


@pytest.fixture
def delivery(case,tmp_path):
    discovery=IntentCodebaseCatalog(case[0][1]);record=case[6](discovery)
    request=module.prepare_codebase_history_request(discovery,record['record_cid'])
    registry=AutoencoderRegistry(tmp_path/'delivery.duckdb',tmp_path/'delivery-artifacts')
    sink=IsolatedNativeDuckLakeHistory(tmp_path/'history',create=True)
    yield case,discovery,request,registry,sink,tmp_path
    registry.close();sink.close()


def register(delivery,operation='source-history'):
    return module.register_codebase_history_request(delivery[3],delivery[1],operation,delivery[2])


def deliver(delivery,directory='delivery-journal'):
    return module.deliver_codebase_history(delivery[3],delivery[4],source_id='codebase-fixture',output_directory=delivery[5]/directory)


def inspect(delivery,operation='source-history'):
    return module.inspect_codebase_history(delivery[3],delivery[4],source_id='codebase-fixture',registrations=[dict(operation_id=operation,request=delivery[2])])


def test_actual_source_metadata_delivery_uses_existing_registry_and_native_snapshot(delivery):
    receipt=register(delivery)
    assert inspect(delivery)['pending_acknowledgements']==1
    result=deliver(delivery)
    assert result['status']=='acknowledged' and result['event_count']==1
    report=inspect(delivery)
    assert report['pending_acknowledgements']==0 and report['retained_snapshot_records']==1
    assert report['records'][0]['immutable_snapshot_payload_verified'] is True
    assert report['durable_reader_pin'] is report['garbage_collection_authority'] is False
    assert list((delivery[5]/'history/data').rglob('*.parquet'))
    assert register(delivery)==receipt
    assert deliver(delivery)==result
    assert delivery[4]._connection.execute('SELECT count(*) FROM history.events').fetchone()==(1,)
    with delivery[3]._transaction() as cx:
        assert cx.execute('SELECT count(*) FROM autoencoder_control.versions').fetchone()==(0,)
        assert cx.execute('SELECT count(*) FROM autoencoder_control.variants').fetchone()==(0,)
        assert cx.execute('SELECT count(*) FROM autoencoder_control.runs').fetchone()==(0,)
    assert delivery[0][0][1].current(delivery[0][2].repository_id)==delivery[0][2]


@pytest.mark.parametrize('damage',['head','origin','manifest','model','authority','extra'])
def test_forged_source_or_authority_requests_refuse_before_outbox_mutation(delivery,damage):
    value=deepcopy(delivery[2])
    if damage=='head':value['source_head']['generation']+=1
    elif damage=='origin':value['source_owner']['database_path']=str(delivery[5]/'foreign.duckdb')
    elif damage=='manifest':value['semantic_manifest_cid']=value['record_cid']
    elif damage=='model':value['model_version_id']='unverified-model'
    elif damage=='authority':value['authority']['proof_authority']=True
    else:value['untrusted_field']='pretend checked'
    with pytest.raises(ValueError):module.register_codebase_history_request(delivery[3],delivery[1],'forged',value)
    with delivery[3]._transaction() as cx:assert cx.execute('SELECT count(*) FROM autoencoder_control.events').fetchone()==(0,)


def test_exact_operation_command_payload_survives_committed_response_loss(delivery,monkeypatch):
    original=delivery[3]._mutate
    def lost(*args,**kwargs):original(*args,**kwargs);raise ConnectionError('lost committed response')
    with monkeypatch.context() as patch:
        patch.setattr(delivery[3],'_mutate',lost)
        with pytest.raises(ConnectionError,match='lost committed'):register(delivery)
    receipt=module.resolve_codebase_history_request(delivery[3],'source-history',delivery[2])
    assert receipt is not None and register(delivery)==receipt
    with pytest.raises(RegistryError,match='different payload'):
        delivery[3].resolve_operation('source-history',module.COMMAND+'changed',{'request':delivery[2]})
    changed=deepcopy(delivery[2]);changed['model_version_id']='other-model'
    with pytest.raises(RegistryError):module.resolve_codebase_history_request(delivery[3],'source-history',changed)
    with delivery[3]._transaction() as cx:assert cx.execute('SELECT count(*) FROM autoencoder_control.events').fetchone()==(1,)


def test_historical_registration_replay_does_not_require_live_captured_artifacts(delivery):
    receipt=register(delivery)
    delivery[0][0][1].artifacts.path_for(delivery[2]['record_cid']).unlink()
    assert register(delivery)==receipt
    assert receipt['current_artifact_availability_verified'] is False
    with pytest.raises(FileNotFoundError):register(delivery,'new-registration')
    assert deliver(delivery)['status']=='acknowledged'
    assert inspect(delivery)['source_observed_live'] is False


def test_earlier_native_snapshot_remains_queryable_after_later_batch(delivery):
    register(delivery);first=deliver(delivery);original_snapshot=first['commit']['snapshot_id']
    register(delivery,'another-history-operation');second=deliver(delivery,'second-journal')
    assert second['commit']['snapshot_id']>original_snapshot
    report=inspect(delivery)
    assert report['records'][0]['snapshot_id']==original_snapshot
    assert report['records'][0]['immutable_snapshot_payload_verified'] is True
    assert delivery[4]._connection.execute('SELECT count(*) FROM history.events').fetchone()==(2,)


def test_source_changes_do_not_relabel_historical_event_as_current(delivery):
    register(delivery);deliver(delivery)
    (delivery[0][0][0]/'main.py').write_text('def increment(n: int) -> int:\n    return n+99\n')
    report=inspect(delivery)
    assert report['retained_snapshot_records']==1 and report['source_observed_live'] is False
    event=delivery[3].get_outbox_event('ducklake',register(delivery)['event_id'])
    assert event['payload']['source_head']==delivery[0][2].to_dict()


def test_native_ack_snapshot_tamper_and_oversized_event_refuse(delivery):
    receipt=register(delivery);result=deliver(delivery)
    wrong=deepcopy(result['commit']);wrong['snapshot_id']+=10
    with delivery[3]._transaction() as cx:
        cx.execute('UPDATE autoencoder_control.outbox SET receipt=?',[json.dumps(wrong)])
    with pytest.raises(module.CodebaseHistoryError,match='acknowledgement'):inspect(delivery)
    with delivery[3]._transaction() as cx:
        cx.execute("UPDATE autoencoder_control.events SET event_data=repeat('x',131073)")
    with pytest.raises(module.CodebaseHistoryError,match='oversized'):inspect(delivery)


def test_bounded_explicit_history_registration_selection(delivery):
    register(delivery)
    selection=dict(operation_id='source-history',request=delivery[2])
    for rows in ([selection]*11,[selection]*2,[dict(operation_id='unknown',request=delivery[2])]):
        with pytest.raises(module.CodebaseHistoryError):
            module.inspect_codebase_history(delivery[3],delivery[4],source_id='codebase-fixture',registrations=rows)
    result=module.inspect_codebase_history(delivery[3],delivery[4],source_id='codebase-fixture',registrations=[])
    assert result['registrations']==result['pending_acknowledgements']==0


def test_actual_crash_after_native_lake_commit_recovers_same_frozen_batch_in_fresh_process(delivery):
    registration=register(delivery);root=delivery[5]
    selector=dict(operation_id='source-history',request=delivery[2])
    (root/'selector.json').write_text(json.dumps(selector))
    delivery[3].close();delivery[4].close()
    script='''
import json,os,sys
from pathlib import Path
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.ducklake.autoencoder_history import IsolatedNativeDuckLakeHistory
from ipfs_datasets_py.duckdb_control.codebase_ducklake_history import deliver_codebase_history,inspect_codebase_history
root=Path(sys.argv[1]);mode=sys.argv[2]
with AutoencoderRegistry(root/'delivery.duckdb',root/'delivery-artifacts') as registry, IsolatedNativeDuckLakeHistory(root/'history') as sink:
    if mode=='crash':
        original=sink.append
        def crash(batch):original(batch);os._exit(91)
        sink.append=crash
    result=deliver_codebase_history(registry,sink,source_id='codebase-fixture',output_directory=root/'crash-journal')
    report=inspect_codebase_history(registry,sink,source_id='codebase-fixture',registrations=[json.loads((root/'selector.json').read_text())])
    print(json.dumps(dict(result=result,inspection=report,events=sink._connection.execute('SELECT count(*) FROM history.events').fetchone()[0]),sort_keys=True))
'''
    crashed=subprocess.run([sys.executable,'-c',script,str(root),'crash'],capture_output=True,text=True,timeout=30,env=dict(os.environ))
    assert crashed.returncode==91,crashed.stderr
    recovered=subprocess.run([sys.executable,'-c',script,str(root),'recover'],capture_output=True,text=True,timeout=30,env=dict(os.environ))
    assert recovered.returncode==0,recovered.stderr
    value=json.loads(recovered.stdout.splitlines()[-1])
    assert value['events']==1 and value['result']['status']=='acknowledged'
    assert value['inspection']['pending_acknowledgements']==0
    again=subprocess.run([sys.executable,'-c',script,str(root),'recover'],capture_output=True,text=True,timeout=30,env=dict(os.environ))
    assert again.returncode==0,again.stderr
    assert json.loads(again.stdout.splitlines()[-1])==value
    journal=json.loads((root/'crash-journal/delivery.json').read_text())
    assert journal['batch']['batch_id']==value['result']['commit']['batch_id']
    assert journal['commit']==value['result']['commit']


def test_stale_registry_owner_generation_cannot_acknowledge_old_delivery_lease(delivery):
    registration=register(delivery);registry=delivery[3]
    claim=registry.claim_outbox('claim-before-restart','ducklake','old-worker',limit=1)
    lease=claim['deliveries'][0]['lease'];registry.close()
    with AutoencoderRegistry(delivery[5]/'delivery.duckdb',delivery[5]/'delivery-artifacts') as reopened:
        with pytest.raises(RegistryError):
            reopened.ack_outbox('stale-ack',registration['event_id'],'ducklake',{'unverified':'receipt'},lease)
        result=module.deliver_codebase_history(reopened,delivery[4],source_id='codebase-fixture',output_directory=delivery[5]/'new-owner-journal')
        assert result['status']=='acknowledged'
