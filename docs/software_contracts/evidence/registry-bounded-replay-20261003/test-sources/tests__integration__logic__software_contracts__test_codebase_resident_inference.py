"""Actual CPU model page work uses the real default datasets resource owner.

Source fixture capture uses the explicitly injected foundation sampler. This is
component evidence, not admission of a complete new supervisor envelope.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import site
import subprocess
import sys

import pytest

from tests.integration.logic.software_contracts.test_codebase_repository_shards import current,sharded
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
from ipfs_datasets_py.logic.software_contracts import codebase_source_384 as source384
from ipfs_datasets_py.logic.software_contracts import codebase_prior_384 as prior
from ipfs_datasets_py.logic.software_contracts import codebase_resident_inference as module


@pytest.fixture
def ready(sharded,tmp_path):
    checkpoint=os.environ.get('CODEBASE384_CHECKPOINT')
    snapshot=os.environ.get('CODEBASE384_EMBEDDING_SNAPSHOT')
    if not checkpoint or not snapshot:pytest.skip('explicit real checkpoint and cached embedding snapshot required')
    current,receipt,source=sharded
    registry=AutoencoderRegistry(tmp_path/'models.duckdb',tmp_path/'models')
    path=Path(checkpoint)
    shared=source384.register_shared_parent(registry,checkpoint_path=path,expected_sha256=module.sha(path.read_bytes()))
    version=prior.register_parent(current[1],registry,source_parent_version_id=shared)
    request=dict(expected_head=CodebaseHead.from_dict(receipt['head']),root_cid=source['root_cid'],registry=registry,
        version_id=version,embedding_snapshot=snapshot,timeout_seconds=180,memory_mb=4096)
    yield current,source,registry,request,tmp_path
    registry.close()


def run(ready,**options):
    current,_,_,request,_=ready
    return module.run_resident_inference_pages(current[1],current[0],**{**request,**options})


def load(ready,result,**options):
    current,source,registry,request,_=ready
    return module.load_resident_cursor(current[1],registry,result['cursor_cid'],root_cid=source['root_cid'],
        version_id=request['version_id'],embedding_snapshot=request['embedding_snapshot'],**options)


def test_explicit_cuda_refusal_occurs_before_source_model_or_host_access(monkeypatch):
    def forbidden(*a,**k):pytest.fail('unqualified CUDA accessed an owner')
    monkeypatch.setattr(module,'_context',forbidden)
    with pytest.raises(module.shards.RepositoryShardsError,match='CUDA'):
        module.run_resident_inference_pages(None,None,expected_head=None,root_cid=None,registry=None,version_id=None,
            embedding_snapshot=None,device='cuda')


def test_actual_resident_pages_keep_complete_inventory_and_replay_without_model_calls(ready,monkeypatch):
    first=run(ready,max_pages=2)
    cursor,records=load(ready,first)
    assert cursor['next_page']==2 and len(records)==1 and not first['inventory_complete']
    native=records[0]['worker_output']
    assert native['model_loads']==1 and native['device']=='cpu' and native['peak_rss_bytes']>0
    assert sum(p['decoded_rows'] for p in native['pages'])>0 and first['inference_executed']
    assert not first['proof_authority'] and not native['targets_used_for_inference']
    def forbidden(*args,**kwargs):pytest.fail('exact durable model replay launched inference')
    with monkeypatch.context() as patch:
        patch.setattr(module,'_worker',forbidden)
        again=run(ready,max_pages=2)
        assert again['cursor_cid']==first['cursor_cid'] and not again['native_worker_executed']
    final=run(ready,cursor_cid=first['cursor_cid'],max_pages=16)
    cursor,records=load(ready,final)
    assert final['inventory_complete'] and cursor['next_page']==5
    inventory=[row for record in records for row in record['inventory']]
    assert len(inventory)==len({r['ordinal'] for r in inventory})==9
    assert len([r for r in inventory if r['inference_disposition']!='pending_source_conditioned_inference'])>0
    ready[4].joinpath('resident-result.json').write_bytes(module.raw(dict(first=first,final=final,records=records)))


def test_actual_cold_and_resident_models_preserve_predictions_and_measure_load_reuse(ready):
    resident=run(ready,max_pages=16,mode='resident',batch_size=2)
    cold=run(ready,max_pages=16,mode='cold_per_page',batch_size=2)
    r=load(ready,resident,batch_size=2)[1][0]['worker_output']
    c=load(ready,cold,mode='cold_per_page',batch_size=2)[1][0]['worker_output']
    assert r['model_loads']==1 and c['model_loads']>1
    assert [p['rows'] for p in r['pages']]==[p['rows'] for p in c['pages']]
    assert r['elapsed_seconds']>0 and c['elapsed_seconds']>0
    ready[4].joinpath('residency-comparison.json').write_bytes(module.raw(dict(resident=r,cold=c,
        timing_scope='single local observations under uncontrolled concurrent host load; no speedup distribution claim')))


def test_actual_model_batch_sizes_measure_same_closed_decoded_choices(ready):
    from ipfs_datasets_py.logic.software_contracts import codebase_repository_shards as shards
    current,source,registry,request,_=ready
    policy=shards.load_repository_shards(current[1],source['root_cid'])['policy_receipt_cid']
    source=shards.prepare_repository_shards(current[1],current[0],expected_head=request['expected_head'],
        policy_receipt_cid=policy,profile=shards.RepositoryShardProfile(page_entries=16),scheduler=current[3])
    measurements={}
    for batch in (1,4):
        result=run(ready,root_cid=source['root_cid'],max_pages=16,batch_size=batch)
        _,records=module.load_resident_cursor(current[1],registry,result['cursor_cid'],root_cid=source['root_cid'],
            version_id=request['version_id'],embedding_snapshot=request['embedding_snapshot'],batch_size=batch)
        measurements[str(batch)]=records[0]['worker_output']
    def choices(output):
        return [(r['ordinal'],r['status'],r['candidate']['predicted_classes'],r['candidate']['candidate_ir'])
            for p in output['pages'] for r in p['rows'] if r['candidate'] is not None]
    assert choices(measurements['1'])==choices(measurements['4'])
    assert len(choices(measurements['1']))>1
    ready[4].joinpath('model-batching-comparison.json').write_bytes(module.raw(dict(measurements=measurements,
        claim='same closed decoded choices; floating-point embeddings are separately content-addressed per batch profile',
        timing_scope='single local observations under uncontrolled concurrent host load; no speedup distribution claim')))


def test_actual_executed_prefix_cannot_skip_repeat_reorder_or_claim_another_model(ready):
    result=run(ready,max_pages=2);cursor,_=load(ready,result)
    for damage in ('position','repeat','omit','model'):
        value=deepcopy(cursor)
        if damage=='position':value['next_page']+=1
        elif damage=='repeat':value['runs']*=2
        elif damage=='omit':value['runs']=[]
        else:value['context']['model_version_id']='forged'
        cid=ready[0][1].artifacts.put(value)
        with pytest.raises(module.shards.RepositoryShardsError):load(ready,dict(cursor_cid=cid))


def test_actual_source_change_refuses_continuation_before_worker(ready,monkeypatch):
    result=run(ready,max_pages=1)
    (ready[0][0]/'z.py').write_text('def changed(n: int) -> int:\n    return n + 6\n')
    monkeypatch.setattr(module,'_worker',lambda *a,**k:pytest.fail('stale source invoked inference'))
    with pytest.raises(Exception,match='(source|snapshot|changed|current|differ)'):
        run(ready,cursor_cid=result['cursor_cid'],max_pages=1)


def test_actual_global_parent_memory_budget_refuses_before_source_or_model_access(ready,monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
        get_global_resource_scheduler,ResourceLane,ResourceUnavailableError)
    monkeypatch.setattr(module,'_context',lambda *a,**k:pytest.fail('unadmitted inference accessed source/model'))
    with get_global_resource_scheduler().acquire(lane=ResourceLane.ORCHESTRATION,cpu_slots=1,memory_mb=512,
            child_process_slots=1,timeout=30,request_id='resident-inference-parent-cap-control') as parent:
        with pytest.raises(ResourceUnavailableError,match='memory|parent'):
            run(ready,parent_lease=parent,memory_mb=4096)


def test_actual_gte_and_character_limits_defer_complete_sources_without_truncation(ready):
    from ipfs_datasets_py.logic.software_contracts import codebase_scan_policy as policy
    from ipfs_datasets_py.logic.software_contracts import codebase_repository_shards as shards
    current,_,registry,request,_=ready
    root,index,_,scheduler,_=current
    (root/'token_long.py').write_text('# '+'word '*700+'\n')
    (root/'character_long.py').write_text('#'+'x'*33000+'\n')
    receipt=policy.prepare_policy_current(index,root,repository_id='scan:fixture',operation_id='long-sources',
        expected_head=request['expected_head'],policy=policy.CodebaseScanPolicy(max_file_bytes=65536,exclusions=('scratch',)),
        scheduler=scheduler)
    head=CodebaseHead.from_dict(receipt['head'])
    source=shards.prepare_repository_shards(index,root,expected_head=head,policy_receipt_cid=receipt['receipt_cid'],
        profile=shards.RepositoryShardProfile(page_entries=2),scheduler=scheduler)
    result=run(ready,expected_head=head,root_cid=source['root_cid'],max_pages=16)
    _,records=module.load_resident_cursor(index,registry,result['cursor_cid'],root_cid=source['root_cid'],
        version_id=request['version_id'],embedding_snapshot=request['embedding_snapshot'])
    rows={row['path']:row for record in records for page in record['worker_output']['pages'] for row in page['rows']}
    assert rows['token_long.py']['status']=='deferred_gte_token_limit' and rows['token_long.py']['tokens']>512
    assert rows['character_long.py']['status']=='deferred_source_character_limit'
    assert rows['token_long.py']['candidate'] is rows['character_long.py']['candidate'] is None
    assert result['inventory_complete'] and len([r for v in records for r in v['inventory']])==11


def test_actual_model_cursor_replays_after_fresh_file_backed_native_owner_restart(ready):
    result=run(ready,max_pages=2)
    current,source,registry,request,tmp=ready
    database=current[4].execute('SELECT path FROM duckdb_databases() WHERE database_name=current_database()').fetchone()[0]
    registry.close();current[4].close()
    data=dict(source_database=database,source_cas=str(current[1].artifacts.root),model_database=str(tmp/'models.duckdb'),
        model_cas=str(tmp/'models'),cursor=result['cursor_cid'],root=source['root_cid'],version=request['version_id'],snapshot=request['embedding_snapshot'])
    script='''import json,sys
sys.path[:0]=json.loads(sys.argv[1])
import duckdb
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts import codebase_resident_inference as m
r=json.loads(sys.argv[2]);cx=duckdb.connect(r['source_database'],config={'threads':1,'memory_limit':'64MB'})
s=DuckDBASTStore(connection=cx);cas=ImmutableCAS(r['source_cas']);index=RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=s),artifacts=cas,catalog=CodebaseCatalog(s,cas))
registry=AutoencoderRegistry(r['model_database'],r['model_cas'])
def forbidden(*a,**k):raise AssertionError('cold cursor replay invoked model')
m._worker=forbidden
cursor,records=m.load_resident_cursor(index,registry,r['cursor'],root_cid=r['root'],version_id=r['version'],embedding_snapshot=r['snapshot'])
print('REPLAY_RESULT='+json.dumps({'next_page':cursor['next_page'],'runs':len(records)}));registry.close();cx.close()
'''
    roots=[str(Path(module.__file__).parents[3]),site.getusersitepackages()]
    process=subprocess.run([sys.executable,'-I','-c',script,json.dumps(roots),json.dumps(data)],text=True,capture_output=True,timeout=45)
    assert process.returncode==0,process.stderr
    value=json.loads(next(line.split('=',1)[1] for line in process.stdout.splitlines() if line.startswith('REPLAY_RESULT=')))
    assert value=={'next_page':2,'runs':1}
