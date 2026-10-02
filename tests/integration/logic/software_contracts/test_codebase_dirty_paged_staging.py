"""Dirty extraction pages: complete native source/AST/graph publication."""
from pathlib import Path
import json
import os
import site
import subprocess
import sys
import threading
import time

import pytest
import duckdb

from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog, CodebaseCatalogLimits
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex, CodebaseScanLimits
from ipfs_datasets_py.logic.software_contracts import codebase_dirty_paged_staging as staged
from ipfs_datasets_py.logic.software_contracts import codebase_dirty_semantics as semantics
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import GlobalResourceScheduler, ResourceSchedulerConfig


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


def open_owner(path):
    path.mkdir(exist_ok=True)
    cx = duckdb.connect(str(path/'source.duckdb'), config={'threads':1, 'memory_limit':'128MB'})
    store = DuckDBASTStore(connection=cx); cas = ImmutableCAS(path/'cas')
    index = RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store), artifacts=cas,
        catalog=CodebaseCatalog(store, cas, limits=CodebaseCatalogLimits(max_entries=512)))
    return cx, index, staged.CodebaseDirtyPagedStager(index)


def scheduler(path):
    if os.environ.get('RPI029_ACTUAL_HOST') == '1':
        return None
    return GlobalResourceScheduler(ResourceSchedulerConfig.for_proof_host(state_path=path/'resources.json',
        proof_resource_sampler=lambda:ProofHostResources(8,8192,8192), lane_reservations={}, auto_renew_leases=False))


@pytest.fixture
def fixture(tmp_path):
    root=tmp_path/'repository';root.mkdir()
    git(root,'init','-q');git(root,'config','user.name','Dirty fixture');git(root,'config','user.email','fixture@example.invalid')
    contents={
        'a.py':'from b import increment\ndef use(n):\n    return increment(n)\n',
        'b.py':'def increment(n: int) -> int:\n    return n + 1\n',
        'conftest.py':'import pytest\n@pytest.fixture\ndef value():\n    return 4\n',
        'test_a.py':'from a import use\ndef test_use(value):\n    assert use(value) == 5\n',
        'pytest.ini':'[pytest]\naddopts = -q\n', 'requirements.txt':'pytest\n',
        'broken.py':'def broken(:\n', 'delete.py':'x=3\n',
        'large.txt':'x'*2048, '.gitignore':'.runtime/\n',
    }
    for name, body in contents.items():(root/name).write_text(body)
    (root/'link').symlink_to('b.py')
    git(root,'add','.');git(root,'commit','-qm','baseline')
    (root/'b.py').write_text('def increment(n: int) -> int:\n    return n + 2\n')
    (root/'new.py').write_bytes('def größe(n):\r\n    return n\r\n'.encode())
    (root/'delete.py').unlink()
    cx,index,stager=open_owner(tmp_path/'owner');resource=scheduler(tmp_path)
    yield dict(root=root,cx=cx,index=index,stager=stager,scheduler=resource,tmp=tmp_path)
    if resource is not None:assert resource.snapshot()['active_lease_count']==0
    cx.close()


def prepare(f, **kw):
    return f['stager'].prepare(f['root'],repository_id='dirty:fixture',scheduler=f['scheduler'],
        limits=staged.DirtyStagingLimits(max_entries=512,max_file_bytes=512,max_batch_entries=2),**kw)


def advance(f, state, **kw):
    return f['stager'].advance(f['root'],generation_cid=state['generation_cid'],expected_cursor=state['cursor'],
                               scheduler=f['scheduler'],**kw)


def complete(f):
    state=prepare(f)
    while not state['complete_inventory_staged']:state=advance(f,state)
    return state


def finalize(f,state,**kw):
    return f['stager'].finalize(f['root'],generation_cid=state['generation_cid'],operation_id='dirty-publish',
                               expected_head=None,scheduler=f['scheduler'],**kw)


def test_seal_without_parsing_then_bounded_pages_and_complete_global_equivalence(fixture,monkeypatch):
    f=fixture
    with monkeypatch.context() as m:
        m.setattr(semantics,'extract',lambda *a,**k:pytest.fail('initial capture parsed semantic facts'))
        m.setattr(staged.PythonASTExtractor,'extract_from_source',lambda *a,**k:pytest.fail('initial capture parsed AST'))
        state=prepare(f)
    assert state['entry_count']==12 and state['cursor']==0
    with pytest.raises(ValueError,match='partial'):finalize(f,state)
    observed=[];actual=semantics.extract
    def tracked(snapshot,entry,raw):observed.append(entry.path);return actual(snapshot,entry,raw)
    monkeypatch.setattr(semantics,'extract',tracked)
    while not state['complete_inventory_staged']:
        before=len(observed);state=advance(f,state)
        assert len(observed)-before<=2
        assert f['index'].current('dirty:fixture') is None
        assert f['index'].ingestor.store.stats()['size']==0
    assert state['deferred_entries']==1 and state['disposition_counts']['opaque_unanalyzed']==2
    assert state['disposition_counts']['captured_ast_failed']==1
    with monkeypatch.context() as m:
        m.setattr(semantics,'extract',lambda *a,**k:pytest.fail('finalization re-extracted facts'))
        m.setattr(staged.PythonASTExtractor,'extract_from_source',lambda *a,**k:pytest.fail('finalization parsed AST'))
        m.setattr(semantics.PytestAnalyzer,'analyze',lambda *a,**k:pytest.fail('finalization reparsed pytest'))
        result=finalize(f,state)
    manifest=f['index'].load(result.head.manifest_cid)
    assert len(manifest.units)==12 and f['index'].current('dirty:fixture')==result.head
    assert any(e.relation=='uses_fixture' for e in manifest.semantic_state.edges)
    assert any(e.relation=='calls' and not e.target_id.startswith('lexical:') for e in manifest.semantic_state.edges)
    cx,cold,_=open_owner(f['tmp']/'cold')
    try:
        expected=cold.prepare_current(f['root'],repository_id='dirty:fixture',operation_id='cold',expected_head=None,
            limits=CodebaseScanLimits(max_entries=512,max_file_bytes=512),scheduler=f['scheduler'])
        assert expected.head.manifest_cid==result.head.manifest_cid
    finally:cx.close()
    assert finalize(f,state)==result


def test_fresh_process_resume_reconstructs_exact_dirty_generation(fixture):
    f=fixture;state=advance(f,prepare(f));f['cx'].close()
    script='''import json,sys
sys.path[:0]=json.loads(sys.argv[1])
from pathlib import Path
from tests.integration.logic.software_contracts.test_codebase_dirty_paged_staging import open_owner,scheduler
p=Path(sys.argv[2]);cx,index,stager=open_owner(p/'owner');s=stager.status(sys.argv[3]);assert s['cursor']==2
s=stager.advance(p/'repository',generation_cid=sys.argv[3],expected_cursor=2,scheduler=scheduler(p))
assert index.current('dirty:fixture') is None
print('STAGING='+json.dumps(s));cx.close()
'''
    roots=[str(Path(staged.__file__).parents[3]),site.getusersitepackages()]
    child=subprocess.run([sys.executable,'-I','-c',script,json.dumps(roots),str(f['tmp']),state['generation_cid']],
        capture_output=True,text=True,timeout=90)
    assert child.returncode==0,child.stderr
    result=json.loads(next(line.split('=',1)[1] for line in child.stdout.splitlines() if line.startswith('STAGING=')))
    assert result['cursor']==4 and result['generation_cid']==state['generation_cid']


@pytest.mark.parametrize('mutation',['edit','untracked','staged','rename','ignore','external_ignore'])
def test_changed_dirty_scope_refuses_resume_and_new_capture_has_new_identity(fixture,mutation):
    f=fixture;state=advance(f,prepare(f));root=f['root']
    if mutation=='edit':(root/'b.py').write_text('x=9\n')
    elif mutation=='untracked':(root/'added.py').write_text('x=9\n')
    elif mutation=='staged':git(root,'add','b.py')
    elif mutation=='rename':(root/'new.py').rename(root/'renamed.py')
    elif mutation=='ignore':(root/'.gitignore').write_text('new.py\n')
    else:(root/'.git/info/exclude').write_text('new.py\n')
    with pytest.raises(ValueError):advance(f,state)
    assert f['stager'].status(state['generation_cid'])['cursor']==2
    assert f['index'].current('dirty:fixture') is None
    if mutation=='external_ignore':
        with pytest.raises(ValueError,match='external ignore'):prepare(f)
    else:assert prepare(f)['generation_cid']!=state['generation_cid']


def test_lost_page_reply_replays_without_extraction_and_future_cursor_refuses(fixture,monkeypatch):
    f=fixture;initial=prepare(f);state=advance(f,initial)
    monkeypatch.setattr(semantics,'extract',lambda *a,**k:pytest.fail('sealed page was parsed again'))
    replay=advance(f,initial)
    assert replay['replayed'] and replay['last_receipt_cid']==state['last_receipt_cid']
    with pytest.raises(ValueError,match='future'):advance(f,{**state,'cursor':state['cursor']+1})


def test_partial_page_transaction_rolls_back_without_head(fixture,monkeypatch):
    f=fixture;state=prepare(f);actual=f['stager']._write_shard
    def failed(*args):actual(*args);raise RuntimeError('after shard SQL')
    with monkeypatch.context() as m:
        m.setattr(f['stager'],'_write_shard',failed)
        with pytest.raises(RuntimeError,match='shard SQL'):advance(f,state)
    assert f['stager'].status(state['generation_cid'])['cursor']==0
    assert f['index'].current('dirty:fixture') is None
    assert advance(f,state)['cursor']==2


def test_final_source_fence_refuses_edit_after_global_resolution(fixture,monkeypatch):
    f=fixture;state=complete(f);actual=semantics.assemble
    def changed(*args):
        value=actual(*args);(f['root']/'b.py').write_text('x=999\n');return value
    monkeypatch.setattr(semantics,'assemble',changed)
    with pytest.raises(ValueError,match='dirty source'):finalize(f,state)
    assert f['index'].current('dirty:fixture') is None


def test_edit_during_native_ast_sql_rolls_back_head_and_complete_projection(fixture,monkeypatch):
    f=fixture;state=complete(f);store=f['index'].ingestor.store;actual=store._persist_projection
    def changed(projection):
        actual(projection)
        (f['root']/'b.py').write_text('changed_while_applying = True\n')
    monkeypatch.setattr(store,'_persist_projection',changed)
    with pytest.raises(ValueError,match='dirty source'):finalize(f,state)
    assert f['index'].current('dirty:fixture') is None
    assert store.stats()['size']==0
    assert f['cx'].execute('SELECT count(*) FROM codebase_control.operations').fetchone()[0]==0


def test_successor_dirty_generation_matches_cold_and_keeps_old_staging_historical(fixture):
    f=fixture;old_state=complete(f);old=finalize(f,old_state)
    (f['root']/'b.py').write_text('def increment(n: int) -> int:\n    return n + 7\n')
    (f['root']/'new.py').unlink()
    state=complete(f)
    assert state['generation_cid']!=old_state['generation_cid']
    successor=f['stager'].finalize(f['root'],generation_cid=state['generation_cid'],operation_id='successor',
        expected_head=old.head,scheduler=f['scheduler'])
    assert successor.head.generation==2
    assert not f['stager'].status(old_state['generation_cid'])['source_observed_live']
    with pytest.raises(ValueError,match='dirty source'):advance(f,old_state)
    cx,cold,_=open_owner(f['tmp']/'cold-successor')
    try:
        expected=cold.prepare_current(f['root'],repository_id='dirty:fixture',operation_id='cold',expected_head=None,
            limits=CodebaseScanLimits(max_entries=512,max_file_bytes=512),scheduler=f['scheduler'])
        assert successor.head.manifest_cid==expected.head.manifest_cid
    finally:cx.close()


@pytest.mark.parametrize('artifact',['source','ast','semantic'])
def test_cached_page_artifact_corruption_refuses(fixture,artifact):
    f=fixture;state=advance(f,prepare(f));receipt=f['index'].artifacts.get(state['last_receipt_cid'])
    unit=next(u for u in receipt['units'] if u['ast_cid'])
    cid=unit[{'source':'source_cid','ast':'ast_cid','semantic':'semantic_cid'}[artifact]]
    path=f['index'].artifacts.path_for(cid,source=artifact=='source');raw=path.read_bytes()
    path.chmod(0o600);path.write_bytes(raw[:-1]+b'!')
    with pytest.raises(ValueError):f['stager'].status(state['generation_cid'])


def test_entry_cap_rejects_complete_population_without_truncation(fixture):
    f=fixture
    with pytest.raises(ValueError,match='max_entries'):
        f['stager'].prepare(f['root'],repository_id='dirty:fixture',limits=staged.DirtyStagingLimits(max_entries=3),
                            scheduler=f['scheduler'])
    assert f['cx'].execute('SELECT count(*) FROM codebase_staging_control.generations').fetchone()[0]==0


def test_cancelled_page_has_no_cursor_or_head_mutation(fixture):
    f=fixture;state=prepare(f);signal=threading.Event();signal.set()
    with pytest.raises(Exception,match='cancel'):advance(f,state,cancel_event=signal)
    assert f['stager'].status(state['generation_cid'])['cursor']==0
    assert f['index'].current('dirty:fixture') is None


def test_producer_drift_refuses_retained_pages(fixture,monkeypatch):
    f=fixture;state=advance(f,prepare(f));actual=staged._implementation()
    monkeypatch.setattr(staged,'_implementation',lambda:{**actual,'changed':'0'*64})
    with pytest.raises(ValueError,match='producer changed'):f['stager'].status(state['generation_cid'])


def test_parser_runtime_and_direct_schema_producers_are_bound(fixture,monkeypatch):
    f=fixture;state=advance(f,prepare(f));pins=staged._implementation()
    prefix='ipfs_datasets_py.logic.software_contracts.'
    for name in ['schema_versions','semantic_index.scanner','semantic_index.python_analysis',
                 'semantic_index.pytest_analysis','semantic_index.symbol_graph','semantic_index.identity',
                 'semantic_index.models','python_frontend','duckdb_ast_store']:
        assert prefix+name in pins
    monkeypatch.setattr(staged,'_runtime',lambda:{'python_version':'changed'})
    with pytest.raises(ValueError,match='parser runtime'):f['stager'].status(state['generation_cid'])


def test_320_dirty_entries_resume_before_complete_native_publication(tmp_path):
    """Actual 320-file Git/AST/DuckDB path; sampler mode is explicit in reports."""
    root=tmp_path/'repository';root.mkdir()
    git(root,'init','-q');git(root,'config','user.name','Dirty scale fixture');git(root,'config','user.email','fixture@example.invalid')
    for i in range(320):(root/f'file_{i:03}.py').write_text(f'def value_{i}(n: int) -> int:\n    return n + {i}\n')
    git(root,'add','.');git(root,'commit','-qm','complete inventory')
    for i in range(0,320,2):(root/f'file_{i:03}.py').write_text(f'def value_{i}(n: int) -> int:\n    return n + {i+1}\n')
    resource=scheduler(tmp_path);cx,index,stager=open_owner(tmp_path/'owner');started=time.monotonic()
    timings={name:dict(calls=0,seconds=0.) for name in ('_fence','_replay')}
    def instrument(owner):
        for name in timings:
            actual=getattr(owner,name)
            def measured(*args,_actual=actual,_name=name,**kwargs):
                before=time.monotonic()
                try:return _actual(*args,**kwargs)
                finally:
                    timings[_name]['calls']+=1
                    timings[_name]['seconds']+=time.monotonic()-before
            setattr(owner,name,measured)
    instrument(stager)
    try:
        state=stager.prepare(root,repository_id='dirty:scale',scheduler=resource)
        generation=state['generation_cid'];cursors=[]
        while not state['complete_inventory_staged']:
            if state['cursor']==128:
                cx.close();cx,index,stager=open_owner(tmp_path/'owner');instrument(stager)
                assert stager.status(generation)['cursor']==128
            state=stager.advance(root,generation_cid=generation,expected_cursor=state['cursor'],scheduler=resource)
            cursors.append(state['cursor']);assert index.current('dirty:scale') is None
        staged_seconds=time.monotonic()-started
        publication=stager.finalize(root,generation_cid=generation,operation_id='scale',expected_head=None,
                                   scheduler=resource,timeout_seconds=300)
        manifest=index.load(publication.head.manifest_cid)
        assert len(manifest.units)==320 and manifest.coverage['ast_ok']==320
        assert cursors==list(range(16,321,16)) and manifest.snapshot.mode=='git-working'
        report=dict(schema='dirty-paged-scale-measurement@1',entries=320,shards=len(cursors),restart_at=128,
            staged_seconds=staged_seconds,total_seconds=time.monotonic()-started,manifest_cid=manifest.cid,
            generation_cid=generation,head=publication.head.to_dict(),producer=staged._implementation(),
            sampler='actual_default' if resource is None else 'injected_foundation_sampler',
            captures_whole_bounded_source=True,parses_source_only_in_bounded_pages=True,
            phase_measurements=timings,parser_cache=stager.replay_cache_stats())
        (tmp_path/'scale-result.json').write_text(json.dumps(report,indent=2)+'\n')
        print('DIRTY_SCALE='+json.dumps(report))
    finally:cx.close()
