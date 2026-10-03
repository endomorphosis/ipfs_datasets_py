"""Captured modules, real shared checkpoint, bounded CPU worker and replay.

Local source files are declared fixtures. Numerical work uses actual cached
model assets and the native datasets scheduler, never provider calls.
"""
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import subprocess

import pytest

from ipfs_datasets_py.logic.software_contracts import codebase_source_units_384 as owner
from ipfs_datasets_py.logic.software_contracts import codebase_source_384 as shared
from ipfs_datasets_py.logic.software_contracts.codebase_ir import CodebaseScanLimits,StaleCodebaseError


@pytest.fixture(scope='module')
def captured(tmp_path_factory):
    import duckdb
    from types import SimpleNamespace
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
    from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
    from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
    from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
    root=tmp_path_factory.mktemp('source-unit384');repo=root/'repo';repo.mkdir()
    source=(b'#'+b'x'*70000+b'\nraise RuntimeError("source must never execute")\n'
        b'def calculation(capacity: int, threshold: int) -> bool:\n    return capacity >= threshold\n'
        b'class Box:\n    def method(capacity: int, threshold: int) -> int:\n        return capacity + threshold\n'
        b'def outer(n):\n    def inner(x):\n        return x+1\n    return inner(n)\n'
        b'def long_tokens(capacity: int, threshold: int) -> int:\n    """'+b'word '*700+b'"""\n    return capacity + threshold\n')
    (repo/'module.py').write_bytes(source)
    (repo/'broken.py').write_text('def broken(:\n')
    (repo/'notes.txt').write_text('public source documentation\n')
    for args in (('init','-q'),('config','user.name','Fixture'),('config','user.email','fixture@example.invalid'),
                 ('add','.'),('commit','-qm','captured module source')):
        subprocess.run(['git','-C',str(repo),*args],check=True)
    with (repo/'.git/info/exclude').open('a') as stream:stream.write('\n.runtime/\n')
    cx=duckdb.connect(str(root/'source.duckdb'),config={'threads':1,'memory_limit':'64MB'})
    store=DuckDBASTStore(connection=cx);cas=ImmutableCAS(root/'cas')
    index=RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store),artifacts=cas,catalog=CodebaseCatalog(store,cas))
    head=index.prepare_current(repo,repository_id='source-unit-fixture',operation_id='capture',expected_head=None,
        limits=CodebaseScanLimits(max_entries=8,max_file_bytes=1_048_576),exclusions=('.runtime',),memory_mb=512).head
    registry=AutoencoderRegistry(root/'models.duckdb',root/'models')
    value=SimpleNamespace(root=root,repo=repo,index=index,head=head,registry=registry,source=source)
    yield value
    registry.close();cx.close()


def options(current):
    return dict(expected_head=current.head,paths=['module.py','broken.py','notes.txt'])


def test_preparation_keeps_full_inventory_and_bounded_selection(captured):
    result=owner.prepare_source_units(captured.index,**options(captured),max_selected_units=2)
    assert result['counts']==dict(files=3,functions=5,selected_units=2)
    files={f['path']:f for f in result['files']}
    assert files['broken.py']['disposition']=='complete_python_source_required'
    assert files['notes.txt']['disposition']=='unsupported_language'
    units=files['module.py']['extraction']['units']
    assert units[2]['inference_disposition']=='deferred_selection_budget'
    assert all(f['source_sha256']==hashlib.sha256((captured.repo/f['path']).read_bytes()).hexdigest() for f in result['files'])
    assert all(set(r)=={'id','source_text'} for r in result['selected_inputs'])
    assert owner.validate_source_units(captured.index,result)==result
    assert (captured.repo/'module.py').read_bytes()==captured.source


@pytest.mark.parametrize('damage',['target','map','head','omit','selection'])
def test_prepared_source_map_replay_refuses_tampering(captured,damage):
    report=owner.prepare_source_units(captured.index,**options(captured))
    if damage=='target':report['selected_inputs'][0]['target']='invented'
    elif damage=='map':report['files'][1]['extraction']['units'][0]['source_binding']['start_byte']+=1
    elif damage=='head':report['source_head']['ast_revision_id']='forged'
    elif damage=='omit':report['files'].pop()
    else:report['counts']['selected_units']=0
    with pytest.raises(ValueError):owner.validate_source_units(captured.index,report)


def test_actual_pinned_parent_units_defer_long_tokens_and_replay_without_models(captured,monkeypatch):
    checkpoint=os.environ.get('CODEBASE384_CHECKPOINT');snapshot=os.environ.get('CODEBASE384_EMBEDDING_SNAPSHOT')
    if not checkpoint or not snapshot:pytest.skip('explicit actual checkpoint and cached GTE snapshot required')
    path=Path(checkpoint)
    parent=shared.register_shared_parent(captured.registry,checkpoint_path=path,expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    args=dict(**options(captured),registry=captured.registry,version_id=parent,embedding_snapshot=snapshot,timeout_seconds=180,memory_mb=4096)
    result=owner.infer_shared_parent_units(captured.index,captured.repo,**args)
    assert result['native_worker_executed'] and result['inference_executed']
    report=result['report'];rows=report['output']['rows']
    assert len(rows)==5 and sum(r['status']=='deferred_gte_token_limit' for r in rows)==1
    assert sum(r['status']=='decoded_unverified_candidate' for r in rows)==4
    assert report['coverage']['functions']==5 and report['retention']=='unknown_not_evaluated'
    assert all(report[k] is False for k in owner.FALSE)
    assert report['output']['model_loads']==1 and report['worker_receipt']['provider_calls']==0
    assert (captured.repo/'module.py').read_bytes()==captured.source
    def forbidden(*a,**k):pytest.fail('replay invoked numerical worker')
    monkeypatch.setattr(owner,'_worker',forbidden)
    again=owner.infer_shared_parent_units(captured.index,captured.repo,**args)
    assert again['artifact']==result['artifact'] and not again['native_worker_executed'] and not again['inference_executed']
    assert owner.validate_shared_parent_units(captured.index,captured.repo,result,registry=captured.registry,
        embedding_snapshot=snapshot)==result
    for field in ('preparation','output','coverage'):
        bad=deepcopy(result)
        if field=='preparation':bad['report'][field]['selected_inputs'][0]['source_text']='def fixture(): return 1'
        elif field=='output':bad['report'][field]['rows'][0]['candidate']['proof_authority']=True
        else:bad['report'][field]['functions']=99
        with pytest.raises(ValueError):owner.validate_shared_parent_units(captured.index,captured.repo,bad,
            registry=captured.registry,embedding_snapshot=snapshot)
    (captured.root/'actual-source-unit-result.json').write_bytes(owner.raw(result))
    original=(captured.repo/'module.py').read_bytes()
    try:
        (captured.repo/'module.py').write_bytes(original+b'\n# changed\n')
        with pytest.raises(StaleCodebaseError):owner.validate_shared_parent_units(captured.index,captured.repo,result,
            registry=captured.registry,embedding_snapshot=snapshot)
    finally:(captured.repo/'module.py').write_bytes(original)
