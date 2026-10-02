"""Actual Git object batches, under the foundation's injected host sampler."""
import json

import pytest

from tests.integration.logic.software_contracts.test_codebase_scan_policy import current,git
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
from ipfs_datasets_py.logic.software_contracts import codebase_repository_shards as shards
from ipfs_datasets_py.logic.software_contracts import codebase_git_batch as module


@pytest.fixture
def paged(current):
    root,index,prepare,scheduler,_=current
    (root/'dirty.py').write_text('def dirty(n):\n    return n + 9\n')
    receipt=prepare()
    source=shards.prepare_repository_shards(index,root,expected_head=CodebaseHead.from_dict(receipt['head']),
        policy_receipt_cid=receipt['receipt_cid'],profile=shards.RepositoryShardProfile(page_entries=16),scheduler=scheduler)
    return current,source


def read(paged,**kwargs):
    current,source=paged
    return module.read_repository_source_page(current[1],current[0],root_cid=source['root_cid'],cursor=source['cursor'],
        scheduler=current[3],**kwargs)


def test_native_batch_per_blob_and_cas_are_byte_identical_for_complete_dirty_page(paged,tmp_path):
    results={mode:read(paged,mode=mode) for mode in ('batch','per_blob','cas')}
    projected=lambda result:[{k:v for k,v in r.items() if k!='acquisition'} for r in result['rows']]
    assert projected(results['batch'])==projected(results['per_blob'])==projected(results['cas'])
    assert len(results['batch']['rows'])==8
    assert results['batch']['object_processes']==1 and results['per_blob']['object_processes']==4
    assert results['cas']['object_processes']==0
    by_path={r['path']:r for r in results['batch']['rows']}
    assert by_path['main.py']['source_text'].encode()==(paged[0][0]/'main.py').read_bytes()
    assert '\r\n' in by_path['main.py']['source_text'] and 'größ' in by_path['main.py']['source_text']
    assert by_path['dirty.py']['acquisition']=='captured_source_cas'
    assert all(by_path[p]['acquisition']=='opaque_not_acquired' and by_path[p]['source_text'] is None
        for p in ('large.py','binary.dat','link.py'))
    assert all(not results['batch'][key] for key in shards.FALSE)
    tmp_path.joinpath('git-batch-comparison.json').write_text(json.dumps(results,sort_keys=True))


def test_modified_tracked_source_is_never_replaced_with_head_object(current):
    root,index,prepare,scheduler,_=current
    (root/'main.py').write_text('def changed(n):\n    return n + 101\n')
    receipt=prepare()
    source=shards.prepare_repository_shards(index,root,expected_head=CodebaseHead.from_dict(receipt['head']),
        policy_receipt_cid=receipt['receipt_cid'],scheduler=scheduler)
    result=read((current,source))
    row=next(r for r in result['rows'] if r['path']=='main.py')
    assert row['acquisition']=='captured_source_cas' and row['source_text']==(root/'main.py').read_text()


def test_actual_drift_after_object_acquisition_refuses_whole_page(paged,monkeypatch):
    original=module.process.run_bounded_stdin_tool
    def changed(*args,**kwargs):
        result=original(*args,**kwargs)
        (paged[0][0]/'main.py').write_text('def stale(n): return n + 999\n')
        return result
    monkeypatch.setattr(module.process,'run_bounded_stdin_tool',changed)
    with pytest.raises(Exception,match='changed|stale|differs|source|snapshot'):read(paged)


@pytest.mark.parametrize('mutation',['extra','missing','wrong_type','wrong_size','wrong_body','wrong_oid'])
def test_invalid_native_protocol_cannot_become_captured_source(paged,mutation):
    current,source=paged
    native=current[1].load(shards.load_repository_shards(current[1],source['root_cid'])['structural_manifest_cid'])
    entry=next(e for e in native.snapshot.entries if e.path=='main.py')
    body=current[1].artifacts.get_bytes(entry.source_cid)
    header=f'{entry.git_blob_oid} blob {entry.size_bytes}\n'.encode()
    wire=header+body+b'\n'
    if mutation=='extra':wire+=wire
    elif mutation=='missing':wire=wire[:-1]
    elif mutation=='wrong_type':wire=wire.replace(b' blob ',b' tree ',1)
    elif mutation=='wrong_size':wire=header.replace(str(entry.size_bytes).encode(),b'0')+body+b'\n'
    elif mutation=='wrong_body':wire=header+body.replace(b'+ 1',b'+ 2')+b'\n'
    else:wire=b'0'*len(entry.git_blob_oid)+wire[len(entry.git_blob_oid):]
    with pytest.raises(module.shards.RepositoryShardsError):module._parse_batch(wire.decode(),[entry])


def test_terminal_or_foreign_cursor_is_not_a_page(paged):
    current,source=paged
    with pytest.raises(module.shards.RepositoryShardsError,match='nonterminal'):
        module.read_repository_source_page(current[1],current[0],root_cid=source['root_cid'],
            cursor=shards.page_cursor(source['root_cid'],1),scheduler=current[3])


def test_source_head_and_sql_tables_do_not_change(paged):
    current,source=paged
    before=current[1].current('scan:fixture')
    tables=current[4].execute('SELECT table_schema,table_name FROM information_schema.tables ORDER BY 1,2').fetchall()
    read(paged)
    assert current[1].current('scan:fixture')==before
    assert current[4].execute('SELECT table_schema,table_name FROM information_schema.tables ORDER BY 1,2').fetchall()==tables
