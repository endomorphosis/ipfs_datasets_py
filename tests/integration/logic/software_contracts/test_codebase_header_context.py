"""Captured header models, exact native replay and explicit currentness boundaries.

Admission tests use an isolated authored scheduler with injected host telemetry.
They are mechanism controls, not a live host-pressure qualification.
"""
from copy import deepcopy
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import subprocess
import threading
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.software_contracts import codebase_header_context as owner
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex, CodebaseScanLimits, StaleCodebaseError
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS, CacheIntegrityError
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as resources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
from tests.unit.logic.security_ir.test_code_header_derivation import PROGRAM, PROTOCOL


def git(repo, *args):
    subprocess.run(['git','-C',str(repo),*args],check=True,capture_output=True)


def open_index(root):
    import duckdb
    cx=duckdb.connect(str(root/'source.duckdb'),config={'threads':1,'memory_limit':'64MB'})
    store=DuckDBASTStore(connection=cx);cas=ImmutableCAS(root/'cas')
    index=RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store),artifacts=cas,
                                 catalog=CodebaseCatalog(store,cas))
    return index,cx


@pytest.fixture
def captured(tmp_path):
    root=tmp_path;repo=root/'repo';repo.mkdir()
    (repo/'headers.py').write_text(PROGRAM)
    (repo/'broken.py').write_text('def broken(:\n')
    (repo/'notes.txt').write_text('captured documentation\n')
    for args in (('init','-q'),('config','user.name','Fixture'),('config','user.email','fixture@example.invalid'),
                 ('add','.'),('commit','-qm','authored captured header module')):git(repo,*args)
    telemetry=[ProofHostResources(8,8192,8192)]
    config=resources.ResourceSchedulerConfig.for_proof_host(state_path=root/'resources.json',
        proof_resource_sampler=lambda:telemetry[0],lane_reservations={},auto_renew_leases=False,
        poll_interval_seconds=.005,proof_backoff_seconds=.01)
    scheduler=resources.GlobalResourceScheduler(config)
    index,cx=open_index(root)
    head=index.prepare_current(repo,repository_id='header-fixture',operation_id='capture',expected_head=None,
        limits=CodebaseScanLimits(max_entries=8,max_file_bytes=2_000_000),scheduler=scheduler,memory_mb=512).head
    value=SimpleNamespace(root=root,repo=repo,index=index,cx=cx,head=head,scheduler=scheduler,telemetry=telemetry)
    try:yield value
    finally:value.cx.close()


def options(c):
    return dict(expected_head=c.head,paths=['notes.txt','headers.py','broken.py'],protocol=PROTOCOL,scheduler=c.scheduler)


def idle(c):
    snapshot=c.scheduler.snapshot()
    assert snapshot['active_lease_count']==snapshot['waiting_request_count']==0


def test_exact_native_derivation_full_inventory_and_cold_reopen(captured,monkeypatch):
    c=captured
    monkeypatch.setattr(owner.header,'check_header_semantics',lambda *a,**k:pytest.fail('solver called'))
    receipt=owner.prepare_captured_header_context(c.index,**options(c))
    assert receipt['summary']==dict(selected_paths=3,modeled_modules=1,unsupported_paths=2,
        modeled_helpers=2,deterministic_formula_count=12,smt_obligation_count=6)
    assert receipt['learned_formula_count']==receipt['model_loads']==receipt['provider_calls']==receipt['solver_calls']==0
    assert all(receipt[k] is False for k in owner.FALSE)
    report=c.index.artifacts.get(receipt['artifact_cid'],expected_schema=owner.SCHEMA)
    modules={row['path']:row for row in report['modules']}
    assert modules['notes.txt']['disposition']=='unsupported_language'
    assert modules['broken.py']['disposition']=='unsupported'
    assert modules['headers.py']['derivation']==owner.header.derive_header_semantics(
        source_bytes=PROGRAM.encode(),source_path='headers.py',protocol=PROTOCOL)
    for modeled in modules['headers.py']['derivation']['modeled_symbols']:
        span=modeled['source_span']
        assert hashlib.sha256(PROGRAM.encode()[span['start_byte']:span['end_byte']]).hexdigest()==span['sha256']
    c.cx.close();c.index,c.cx=open_index(c.root)
    assert owner.validate_captured_header_context(c.index,receipt=receipt,**options(c))==receipt
    current=owner.validate_current_header_context(c.index,c.repo,receipt=receipt,**options(c))
    assert current['native_observer_calls']==2 and current['captured_receipt']==receipt
    assert not current['proof_authority'] and not current['source_semantics_verified']
    assert current['current_source_verified'] is False
    idle(c)


def test_historical_core_does_not_claim_or_recheck_live_bytes(captured,monkeypatch):
    c=captured;receipt=owner.prepare_captured_header_context(c.index,**options(c))
    (c.repo/'headers.py').write_text(PROGRAM+'\n# live change\n')
    with monkeypatch.context() as patch:
        patch.setattr(c.index,'observe_current',lambda *a,**k:pytest.fail('historical replay observed live tree'))
        assert owner.validate_captured_header_context(c.index,receipt=receipt,**options(c))==receipt
    with pytest.raises(StaleCodebaseError):
        owner.validate_current_header_context(c.index,c.repo,receipt=receipt,**options(c))
    idle(c)


@pytest.mark.parametrize('field',['source_head','protocol','summary','authority','extra','artifact_formula','artifact_schema'])
def test_forged_receipt_or_native_derivation_refused(captured,field):
    c=captured;receipt=owner.prepare_captured_header_context(c.index,**options(c));bad=deepcopy(receipt)
    if field=='source_head':bad['source_head']['generation']+=1
    elif field=='protocol':bad['protocol']['review_ref']='other-review'
    elif field=='summary':bad['summary']['deterministic_formula_count']+=1
    elif field=='authority':bad['proof_authority']=True
    elif field=='extra':bad['extra']=True
    else:
        report=c.index.artifacts.get(bad['artifact_cid'])
        if field=='artifact_schema':report['schema']='other-schema'
        else:next(r for r in report['modules'] if r['path']=='headers.py')['derivation']['formula_count']+=1
        bad['artifact_cid']=c.index.artifacts.put(report)
    with pytest.raises((ValueError,CacheIntegrityError)):
        owner.validate_captured_header_context(c.index,receipt=bad,**options(c))
    idle(c)


@pytest.mark.parametrize('change',['head','protocol','path','duplicate_path','missing_protocol'])
def test_independent_selection_must_match(captured,change):
    c=captured;receipt=owner.prepare_captured_header_context(c.index,**options(c));args=options(c)
    if change=='head':args['expected_head']=replace(c.head,generation=c.head.generation+1)
    elif change=='protocol':args['protocol']=owner.contracts.WsgiHeaderProtocolContract('other-review','respond')
    elif change=='path':args['paths']=['headers.py']
    elif change=='duplicate_path':args['paths']=['headers.py','headers.py']
    else:args['protocol']=None
    with pytest.raises(ValueError):owner.validate_captured_header_context(c.index,receipt=receipt,**args)
    idle(c)


def test_changed_captured_body_and_oversized_report_fail_closed(captured,monkeypatch):
    c=captured;receipt=owner.prepare_captured_header_context(c.index,**options(c))
    with monkeypatch.context() as patch:
        patch.setattr(owner,'MAX_REPORT_BYTES',32)
        with pytest.raises(CacheIntegrityError):
            owner.validate_captured_header_context(c.index,receipt=receipt,**options(c))
    manifest=c.index.load(c.head.manifest_cid)
    entry=next(e for e in manifest.snapshot.entries if e.path=='headers.py')
    c.index.artifacts.path_for(entry.source_cid,source=True).write_bytes(b'changed captured source')
    with pytest.raises(CacheIntegrityError):
        owner.validate_captured_header_context(c.index,receipt=receipt,**options(c))
    idle(c)


@pytest.mark.parametrize('fault',['cancel','deadline','producer','live_source'])
def test_during_derivation_faults_release_lease(captured,monkeypatch,fault):
    c=captured;receipt=owner.prepare_captured_header_context(c.index,**options(c))
    native=owner.header.derive_header_semantics;event=threading.Event();clock=[0.]
    if fault=='deadline':monkeypatch.setattr(owner.time,'monotonic',lambda:clock[0])
    def derive(**kwargs):
        result=native(**kwargs)
        if fault=='cancel':event.set()
        elif fault=='deadline':clock[0]=91.
        elif fault=='producer':monkeypatch.setattr(owner,'_pins',lambda:{'changed':True})
        else:(c.repo/'headers.py').write_text(PROGRAM+'\n# changed during replay\n')
        return result
    monkeypatch.setattr(owner.header,'derive_header_semantics',derive)
    expected={'cancel':resources.LeaseCancelledError,'deadline':resources.LeaseTimeoutError,
              'producer':ValueError,'live_source':StaleCodebaseError}[fault]
    method=owner.validate_current_header_context if fault=='live_source' else owner.validate_captured_header_context
    positional=(c.index,c.repo) if fault=='live_source' else (c.index,)
    with pytest.raises(expected):method(*positional,receipt=receipt,cancel_event=event,**options(c))
    idle(c)


def test_native_resource_refusal_is_not_an_abstention(captured):
    c=captured;c.telemetry[0]=ProofHostResources(8,8192,0)
    with pytest.raises(resources.LeaseTimeoutError):
        owner.prepare_captured_header_context(c.index,timeout_seconds=.03,**options(c))
    idle(c)


def test_head_changes_during_artifact_publication_refused(captured,monkeypatch):
    c=captured;native=c.index.artifacts.put;published=[]
    def publish(value):
        artifact=native(value)
        if value.get('schema')!=owner.SCHEMA:
            return artifact
        published.append(artifact)
        (c.repo/'headers.py').write_text(PROGRAM+'\n# publication-boundary change\n')
        # Advance the actual native catalog after the header report was stored.
        c.index.prepare_current(c.repo,repository_id=c.head.repository_id,
            operation_id='publish-boundary-race',expected_head=c.head,
            limits=CodebaseScanLimits(max_entries=8,max_file_bytes=2_000_000),
            scheduler=c.scheduler,memory_mb=512)
        return artifact
    monkeypatch.setattr(c.index.artifacts,'put',publish)
    with pytest.raises(ValueError,match='selected catalog head changed during publication'):
        owner.prepare_captured_header_context(c.index,**options(c))
    assert len(published)==1
    assert c.index.current(c.head.repository_id)!=c.head
    assert c.index.artifacts.get(published[0])['schema']==owner.SCHEMA
    idle(c)


@pytest.mark.skipif(not os.environ.get('IPFS_DATASETS_PUBLIC_BOTTLE_FIXTURE'),reason='explicit permitted public input required')
def test_optional_exact_public_bottle_capture(captured):
    c=captured;body=Path(os.environ['IPFS_DATASETS_PUBLIC_BOTTLE_FIXTURE']).read_bytes()
    assert hashlib.sha256(body).hexdigest()=='761756ce31753e526c48d28ccbca13a5d2493b16fe37aff3e1e4d2efaf3a2bba'
    (c.repo/'bottle.py').write_bytes(body)
    c.head=c.index.prepare_current(c.repo,repository_id=c.head.repository_id,operation_id='public-capture',
        expected_head=c.head,limits=CodebaseScanLimits(max_entries=8,max_file_bytes=2_000_000),
        scheduler=c.scheduler,memory_mb=512).head
    args=dict(expected_head=c.head,paths=['bottle.py'],
        protocol=owner.contracts.WsgiHeaderProtocolContract('explicit-permitted-public-input','start_response'),scheduler=c.scheduler)
    receipt=owner.prepare_captured_header_context(c.index,**args)
    assert receipt['summary']['modeled_helpers']==2
    assert receipt['summary']['deterministic_formula_count']==12
    assert receipt['summary']['smt_obligation_count']==6 and receipt['learned_formula_count']==0
    assert owner.validate_current_header_context(c.index,c.repo,receipt=receipt,**args)['captured_receipt']==receipt
