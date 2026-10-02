"""Real source/AST/SQL/CAS controls under the foundation's injected host sampler.

These controls do not claim live host admission or model inference acceptance.
"""
from copy import deepcopy
import json
from pathlib import Path
import site
import subprocess
import sys

import pytest

from tests.integration.logic.software_contracts.test_codebase_scan_policy import current,git
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
from ipfs_datasets_py.logic.software_contracts import codebase_repository_shards as module


@pytest.fixture
def sharded(current):
    root,index,prepare,scheduler,connection=current
    (root/'a.py').write_text('from z import target\ndef entry(n: int) -> int:\n    return target(n)\n')
    (root/'z.py').write_text('def target(n: int) -> int:\n    return n + 1\n')
    receipt=prepare()
    result=module.prepare_repository_shards(index,root,expected_head=CodebaseHead.from_dict(receipt['head']),
        policy_receipt_cid=receipt['receipt_cid'],profile=module.RepositoryShardProfile(page_entries=2),scheduler=scheduler)
    return current,receipt,result


def pages(sharded):
    current,_,result=sharded
    cursor=result['cursor'];rows=[]
    while True:
        value=module.read_repository_shard(current[1],result['root_cid'],cursor)
        if value['page'] is not None:rows.extend(value['page']['rows'])
        cursor=value['next_cursor']
        if value['at_end']:break
    return rows,cursor


def test_complete_dirty_inventory_and_global_cross_shard_edges_are_native(sharded):
    current,receipt,result=sharded
    value=module.load_repository_shards(current[1],result['root_cid'])
    rows,cursor=pages(sharded)
    assert value['source_mode']=='git-working' and len(rows)==9
    assert [r['ordinal'] for r in rows]==list(range(9))
    assert {r['path'] for r in rows}=={'a.py','z.py','main.py','broken.py','README.txt','binary.dat','large.py','link.py','do_not_execute.py'}
    assert not value['proof_authority'] and not value['inference_executed'] and not value['current_head_published']
    assert cursor['authority']=='position_only_not_consumption_or_completion'
    dependencies=current[1].artifacts.get(value['global_dependencies_cid'])
    assert any(e['disposition']=='resolved_cross_shard' for e in dependencies['edges'])
    by_path={r['path']:r for r in rows}
    assert by_path['large.py']['source_disposition']=='deferred_large_file'
    assert by_path['link.py']['source_disposition']=='opaque'
    assert by_path['broken.py']['inference_disposition']=='unsupported_ast_disposition'
    assert value['source_policy']['effective_exclusions']


def test_source_head_and_existing_sql_schema_are_not_modified_by_projection(sharded):
    current,receipt,result=sharded
    before=current[1].current('scan:fixture')
    tables=current[4].execute('SELECT table_schema,table_name FROM information_schema.tables ORDER BY 1,2').fetchall()
    again=module.prepare_repository_shards(current[1],current[0],expected_head=before,
        policy_receipt_cid=receipt['receipt_cid'],profile=module.RepositoryShardProfile(page_entries=2),scheduler=current[3])
    assert again['root_cid']==result['root_cid'] and current[1].current('scan:fixture')==before
    assert current[4].execute('SELECT table_schema,table_name FROM information_schema.tables ORDER BY 1,2').fetchall()==tables


def test_resume_root_remains_historical_and_cannot_be_substituted_for_new_snapshot(sharded):
    current,receipt,result=sharded
    first=module.read_repository_shard(current[1],result['root_cid'],result['cursor'])
    (current[0]/'z.py').write_text('def target(n: int) -> int:\n    return n + 7\n')
    successor=current[2]('changed',CodebaseHead.from_dict(receipt['head']))
    newer=module.prepare_repository_shards(current[1],current[0],expected_head=CodebaseHead.from_dict(successor['head']),
        policy_receipt_cid=successor['receipt_cid'],profile=module.RepositoryShardProfile(page_entries=2),scheduler=current[3])
    assert newer['root_cid']!=result['root_cid']
    resumed=module.read_repository_shard(current[1],result['root_cid'],first['next_cursor'])
    assert resumed['page']['start_ordinal']==2
    with pytest.raises(module.RepositoryShardsError,match='another'):
        module.read_repository_shard(current[1],newer['root_cid'],first['next_cursor'])


def test_entry_cap_rejects_whole_generation_without_truncation(sharded):
    current,receipt,_=sharded
    before=current[1].current('scan:fixture')
    with pytest.raises(module.RepositoryShardsError,match='entry cap'):
        module.prepare_repository_shards(current[1],current[0],expected_head=before,policy_receipt_cid=receipt['receipt_cid'],
            profile=module.RepositoryShardProfile(max_entries=8),scheduler=current[3])
    assert current[1].current('scan:fixture')==before


def test_actual_incremental_and_cold_native_capture_have_equal_source_ast_and_global_pages(sharded):
    from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
    from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
    from ipfs_datasets_py.logic.software_contracts import codebase_scan_policy as policy
    current,receipt,first=sharded
    root,index,prepare,scheduler,_=current
    (root/'z.py').write_text('def target(n: int) -> int:\n    return n + 17\n')
    incremental=prepare('incremental',CodebaseHead.from_dict(receipt['head']))
    incremental_pages=module.prepare_repository_shards(index,root,
        expected_head=CodebaseHead.from_dict(incremental['head']),policy_receipt_cid=incremental['receipt_cid'],
        profile=module.RepositoryShardProfile(page_entries=2),scheduler=scheduler)
    warm=module.load_repository_shards(index,incremental_pages['root_cid'])
    # The new ingestor has neither the prior parser shard cache nor warmed
    # publications; it uses the same durable source/CAS/SQL owners.
    ingestor=DuckDBASTIngestor(store=index.ingestor.store)
    cold_index=RepositoryCodebaseIndex(ingestor=ingestor,artifacts=index.artifacts,catalog=index.catalog)
    cold=policy.prepare_policy_current(cold_index,root,repository_id='scan:fixture',operation_id='cold',
        expected_head=CodebaseHead.from_dict(incremental['head']),
        policy=policy.CodebaseScanPolicy(max_file_bytes=512,exclusions=('scratch',)),scheduler=scheduler)
    cold_pages=module.prepare_repository_shards(cold_index,root,expected_head=CodebaseHead.from_dict(cold['head']),
        policy_receipt_cid=cold['receipt_cid'],profile=module.RepositoryShardProfile(page_entries=2),scheduler=scheduler)
    fresh=module.load_repository_shards(cold_index,cold_pages['root_cid'])
    assert ingestor.stats()['parse_invocations']>0 and ingestor.stats()['reuse_hits']==0
    assert index.ingestor.stats()['reuse_hits']>0
    assert warm['structural_manifest_cid']==fresh['structural_manifest_cid']
    assert warm['pages']==fresh['pages'] and warm['global_dependencies_cid']==fresh['global_dependencies_cid']
    assert warm['snapshot_cid']==fresh['snapshot_cid'] and incremental_pages['root_cid']!=first['root_cid']


@pytest.mark.parametrize('field',['pages','coverage','source_head','global_dependencies_cid','producer','source_policy'])
def test_resealed_omitted_or_rebound_metadata_is_not_an_authority(sharded,field):
    current,_,result=sharded
    value=deepcopy(module.load_repository_shards(current[1],result['root_cid']))
    if field=='pages':value[field].pop()
    elif field=='coverage':value[field]['inventory_entries']=1
    elif field=='source_head':value[field]['generation']+=1
    elif field=='global_dependencies_cid':value[field]=result['root_cid']
    elif field=='source_policy':value[field]['custom_exclusions'].append('a.py')
    else:value[field]={}
    forged=current[1].artifacts.put(value)
    with pytest.raises(module.RepositoryShardsError):module.load_repository_shards(current[1],forged)


def test_deleted_page_is_not_reused_from_a_warm_dictionary(sharded):
    current,_,result=sharded
    value=module.load_repository_shards(current[1],result['root_cid'])
    current[1].artifacts.path_for(value['pages'][0]).unlink()
    with pytest.raises(module.RepositoryShardsError):module.load_repository_shards(current[1],result['root_cid'])


def test_actual_file_backed_fresh_process_reconstructs_and_resumes_cursor(sharded,tmp_path):
    current,_,result=sharded
    first=module.read_repository_shard(current[1],result['root_cid'],result['cursor'])
    connection=current[4]
    database=connection.execute('SELECT path FROM duckdb_databases() WHERE database_name=current_database()').fetchone()[0]
    current[4].close()
    request=dict(root=result['root_cid'],cursor=first['next_cursor'],database=database,cas=str(tmp_path/'cas'))
    request['cas']=str(current[1].artifacts.root) if hasattr(current[1].artifacts,'root') else str(tmp_path/'cas')
    script='''import json,sys
sys.path[:0]=json.loads(sys.argv[1])
import duckdb
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts.codebase_repository_shards import read_repository_shard
r=json.loads(sys.argv[2]);cx=duckdb.connect(r['database'],config={'threads':1,'memory_limit':'64MB'})
s=DuckDBASTStore(connection=cx);cas=ImmutableCAS(r['cas']);index=RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=s),artifacts=cas,catalog=CodebaseCatalog(s,cas))
value=read_repository_shard(index,r['root'],r['cursor']);print(json.dumps(value));cx.close()
'''
    roots=[str(Path(module.__file__).parents[3]),site.getusersitepackages()]
    proc=subprocess.run([sys.executable,'-I','-c',script,json.dumps(roots),json.dumps(request)],capture_output=True,text=True,timeout=30)
    assert proc.returncode==0,proc.stderr
    value=json.loads(proc.stdout)
    assert value['page']['start_ordinal']==2 and value['next_cursor']['root_cid']==result['root_cid']
