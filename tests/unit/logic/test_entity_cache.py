"""Offline v2 entity source/progress integrity, never model or Lean admission."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.autoformal import entity_cache as module


def _row(eid='doc:1', kind='legal_document', label='A section', properties='{}'):
    return dict(id=eid, type=kind, label=label, properties_json=properties)


def _manifest(count, relationships=0):
    return dict(schema_version=module.INPUT_SCHEMA, dataset_id=module.DATASET_ID,
                entity_identity_schema=module.SCHEMA,
                entities=dict(sha256='a'*64, bytes=100, row_count=count),
                relationships=dict(sha256='b'*64, bytes=100, row_count=relationships))


def _bound(tmp_path, rows, relationships=(), name='cache'):
    cache=module.EntityCache(tmp_path/(name+'.duckdb'))
    cache.bind_inputs(_manifest(len(rows),len(relationships)),resume=False)
    if rows:
        cache.enqueue_source_batch(list(rows),0,len(rows),verify_inputs=lambda:None)
    return cache


def _ready(tmp_path, rows=None, relationships=(), name='cache'):
    rows=list(rows if rows is not None else [_row()])
    cache=_bound(tmp_path,rows,relationships,name)
    batches=[list(relationships)] if relationships else []
    cache.prepare_containment_batches(batches,verify_inputs=lambda:None)
    return cache


def _state(cache):
    return {table:cache._db.execute('SELECT * FROM '+table+' ORDER BY 1').fetchall()
            for table in ('entity_queue','agent_lease','task_board','cache_meta')}


def _snapshot(cache,path):
    result=cache.write_resume_parquet(path)
    assert result['admitted'] is result['formalized'] is False
    return result


def _mutate_snapshot(path, mutate):
    table=pq.read_table(path,use_threads=False)
    rows=table.to_pylist()
    mutate(rows)
    pq.write_table(pa.Table.from_pylist(rows,schema=table.schema),path,row_group_size=64)


def test_existing_v1_database_rejected_without_mutation(tmp_path):
    path=tmp_path/'legacy.duckdb'
    db=duckdb.connect(str(path),config={'threads':1})
    db.execute('CREATE TABLE entity_queue(entity_id VARCHAR)')
    db.execute("INSERT INTO entity_queue VALUES ('legacy')")
    db.close()
    before={p.name:p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises(module.EntityCacheError,match='v2|migration'):
        module.EntityCache(path)
    assert {p.name:p.read_bytes() for p in tmp_path.iterdir()}==before


def test_new_schema_reopens_and_uses_one_duckdb_thread(tmp_path):
    path=tmp_path/'new.duckdb'
    cache=module.EntityCache(path)
    assert cache._db.execute("SELECT current_setting('threads')").fetchone()==(1,)
    cache.close()
    reopened=module.EntityCache(path)
    assert reopened.stats()==dict(pending=0,claimed=0,prepared=0)
    reopened.close()


@pytest.mark.parametrize('mutation', ['digest','size','count','dataset','schema','extra','bool_count'])
def test_manifest_binding_is_exact_and_failed_rebind_does_not_mutate(tmp_path,mutation):
    cache=_bound(tmp_path,[_row()])
    original=_state(cache)
    value=_manifest(1)
    if mutation=='digest': value['relationships']['sha256']='c'*64
    elif mutation=='size': value['entities']['bytes']+=1
    elif mutation=='count': value['entities']['row_count']+=1
    elif mutation=='dataset': value['dataset_id']='foreign'
    elif mutation=='schema': value['entity_identity_schema']='v1'
    elif mutation=='extra': value['path']='/same/location'
    else: value['entities']['row_count']=True
    with pytest.raises(module.EntityCacheError): cache.bind_inputs(value,resume=True)
    assert _state(cache)==original
    cache.close()


def test_resume_requires_exact_binding_and_explicit_existing_progress(tmp_path):
    cache=_bound(tmp_path,[_row()])
    expected=cache.checkpoint()
    with pytest.raises(module.EntityCacheError): cache.bind_inputs(_manifest(1),resume=False)
    path=cache.path
    cache.close()
    reopened=module.EntityCache(path)
    binding=reopened.bind_inputs(_manifest(1),resume=True)
    assert binding['next_ordinal']==1
    assert reopened.checkpoint()==expected
    reopened.close()


def test_unbound_rows_or_path_only_checkpoint_cannot_gain_source_authority(tmp_path):
    cache=module.EntityCache(tmp_path/'cache.duckdb')
    cache.enqueue([_row()])
    with pytest.raises(module.EntityCacheError): cache.bind_inputs(_manifest(1),resume=True)
    with pytest.raises(module.EntityCacheError): cache.save_checkpoint(entities=1,source='/same/path.parquet')
    cache.close()


def test_bound_plain_enqueue_cannot_bypass_cursor(tmp_path):
    cache=_bound(tmp_path,[_row()])
    before=_state(cache)
    with pytest.raises(module.EntityCacheError): cache.enqueue([_row('foreign')])
    assert _state(cache)==before
    cache.close()


def test_source_batch_and_physical_cursor_rollback_then_resume(tmp_path):
    cache=module.EntityCache(tmp_path/'cache.duckdb')
    cache.bind_inputs(_manifest(3),resume=False)
    assert cache.enqueue_source_batch([_row()],0,1,verify_inputs=lambda:None)==1
    before=_state(cache)
    def fail(): raise RuntimeError('source changed')
    with pytest.raises(RuntimeError,match='source changed'):
        cache.enqueue_source_batch([_row('doc:2'),_row('doc:3')],1,3,verify_inputs=fail)
    assert _state(cache)==before
    path=cache.path
    cache.close()
    reopened=module.EntityCache(path)
    reopened.bind_inputs(_manifest(3),resume=True)
    assert reopened.enqueue_source_batch([_row('doc:2'),_row('doc:3')],1,3,verify_inputs=lambda:None)==2
    assert reopened.checkpoint()['next_ordinal']==3
    reopened.close()


@pytest.mark.parametrize('start,end',[(0,1),(1,3),(True,2),(2,3)])
def test_physical_source_cursor_cannot_skip_replay_or_miscount(tmp_path,start,end):
    cache=module.EntityCache(tmp_path/'cache.duckdb')
    cache.bind_inputs(_manifest(3),resume=False)
    cache.enqueue_source_batch([_row()],0,1,verify_inputs=lambda:None)
    before=_state(cache)
    with pytest.raises(module.EntityCacheError):
        cache.enqueue_source_batch([_row('doc:2')],start,end,verify_inputs=lambda:None)
    assert _state(cache)==before
    cache.close()


def test_exact_duplicates_advance_physical_cursor_but_not_distinct_count(tmp_path):
    cache=module.EntityCache(tmp_path/'cache.duckdb')
    cache.bind_inputs(_manifest(2),resume=False)
    assert cache.enqueue_source_batch([_row(),_row()],0,2,verify_inputs=lambda:None)==1
    assert cache.checkpoint()['entities']==2
    assert sum(cache.stats().values())==1
    cache.close()


@pytest.mark.parametrize('field,value',[('label','Changed'),('properties_json','{"x":1}'),('type','section')])
def test_conflicting_entity_source_rolls_back_entire_physical_batch(tmp_path,field,value):
    cache=module.EntityCache(tmp_path/'cache.duckdb')
    cache.bind_inputs(_manifest(3),resume=False)
    cache.enqueue_source_batch([_row()],0,1,verify_inputs=lambda:None)
    conflict=_row(); conflict[field]=value
    before=_state(cache)
    with pytest.raises(module.EntityCacheError):
        cache.enqueue_source_batch([_row('new'),conflict],1,3,verify_inputs=lambda:None)
    assert _state(cache)==before
    cache.close()


def test_containment_requires_complete_source_and_exact_relationship_count(tmp_path):
    cache=module.EntityCache(tmp_path/'cache.duckdb')
    cache.bind_inputs(_manifest(2,1),resume=False)
    cache.enqueue_source_batch([_row()],0,1,verify_inputs=lambda:None)
    with pytest.raises(module.EntityCacheError,match='incomplete'):
        cache.prepare_containment_batches([],verify_inputs=lambda:None)
    cache.enqueue_source_batch([_row('doc:2')],1,2,verify_inputs=lambda:None)
    before=_state(cache)
    with pytest.raises(module.EntityCacheError,match='incomplete'):
        cache.prepare_containment_batches([],verify_inputs=lambda:None)
    assert _state(cache)==before
    cache.close()


def test_complete_relationship_pass_is_order_independent_across_batches(tmp_path):
    rows=[_row('doc:1'),_row('doc:2'),_row('section:1','section'),_row('section:2','section'),
          _row('title:1','usc_title'),_row('title:2','usc_title')]
    edges=[dict(type='IN_TITLE',source='doc:1',target='title:1'),
           dict(type='HAS_SECTION',source='doc:1',target='section:1'),
           dict(type='IN_TITLE',source='doc:2',target='title:2'),
           dict(type='HAS_SECTION',source='doc:2',target='section:2')]
    first=_bound(tmp_path,rows,edges,name='first')
    second=_bound(tmp_path,rows,edges,name='second')
    result=first.prepare_containment_batches([edges[:1],edges[1:]],verify_inputs=lambda:None)
    assert second.prepare_containment_batches([list(reversed(edges))],verify_inputs=lambda:None)==result
    query='SELECT entity_id,context_json FROM entity_queue ORDER BY entity_id'
    assert first._db.execute(query).fetchall()==second._db.execute(query).fetchall()
    contexts={eid:json.loads(raw) for eid,raw in first._db.execute(query).fetchall()}
    assert contexts['doc:1']['contained_entity_ids']==['doc:1','section:1']
    assert contexts['section:2']['contained_entity_ids']==['section:2','doc:2']
    assert contexts['section:2']['span_legal_id']=='usc:us:2:2'
    assert contexts['title:2']['scope_only_entity_ids']==['section:2']
    assert result['prepared']==6 and result['admitted'] is result['formalized'] is False
    first.close(); second.close()


@pytest.mark.parametrize('kind,first,second',[
    ('IN_TITLE',('doc:1','title:1'),('doc:1','title:2')),
    ('HAS_SECTION',('doc:1','section:1'),('doc:1','section:2')),
    ('HAS_SECTION',('doc:1','section:1'),('doc:2','section:1')),
])
def test_conflicting_relationships_roll_back_before_context_mutation(tmp_path,kind,first,second):
    edges=[dict(type=kind,source=s,target=t) for s,t in (first,second)]
    cache=_bound(tmp_path,[_row()],edges)
    before=_state(cache)
    with pytest.raises(module.EntityCacheError,match='conflicting relationship'):
        cache.prepare_containment_batches([[edges[0]],[edges[1]]],verify_inputs=lambda:None)
    assert _state(cache)==before
    cache.close()


def test_current_claim_prevents_unsealed_context_replacement(tmp_path):
    cache=_bound(tmp_path,[_row()])
    claim={'claim_token':'1'*32}
    cache._db.execute("UPDATE entity_queue SET status='claimed',claim_worker='worker',claim_token=?",[claim['claim_token']])
    before=_state(cache)
    with pytest.raises(module.EntityCacheError,match='current claims'):
        cache.prepare_containment_batches([],verify_inputs=lambda:None)
    assert _state(cache)==before
    assert cache._db.execute('SELECT claim_token FROM entity_queue').fetchone()==(claim['claim_token'],)
    cache.close()



def test_relationship_callback_failure_rolls_back_context_and_preparation(tmp_path):
    rows=[_row(),_row('section:1','section')]
    edges=[dict(type='HAS_SECTION',source='doc:1',target='section:1')]
    cache=_bound(tmp_path,rows,edges)
    before=_state(cache)
    def fail(): raise RuntimeError('relationship changed')
    with pytest.raises(RuntimeError): cache.prepare_containment_batches([edges],verify_inputs=fail)
    assert _state(cache)==before
    result=cache.prepare_containment_batches([edges],verify_inputs=lambda:None)
    assert result['prepared']==2
    cache.close()


def test_sealed_containment_repeat_checks_inputs_and_preserves_enrichment(tmp_path):
    cache=_ready(tmp_path)
    receipt=json.loads(cache._meta('containment_receipt'))['result']
    context={'definition_targets':['usc:us:1:2'],'contained_span_ids':['span-a'],'reasons':['custom']}
    cache._db.execute('UPDATE entity_queue SET context_json=?',[module._json(context)])
    before=_state(cache)
    def forbidden():
        raise AssertionError('sealed relationships must not be reread')
        yield
    checks=[]
    assert cache.prepare_containment_batches(forbidden(),verify_inputs=lambda:checks.append(True))==receipt
    assert checks==[True] and _state(cache)==before
    cache.close()


def test_resume_stream_schema_full_closure_and_exact_false(tmp_path):
    cache=_ready(tmp_path,[_row(),_row('section:1','section')])
    cache.register_agent('agent-a')
    path=tmp_path/'resume.parquet'
    result=_snapshot(cache,path)
    assert result['physical_rows']==6
    assert result['task_count']==2
    summary=cache.resume_summary(path)
    assert summary['kinds']==dict(meta=1,agent=1,entity=2,board=2)
    rows=pq.read_table(path,use_threads=False).to_pylist()
    assert all(row['admitted'] is row['formalized'] is False for row in rows)
    assert all(row['input_id']==cache.checkpoint()['input_id'] for row in rows)
    assert module.MAX_ENTITIES>=180257
    assert module.MAX_RESUME_ROWS==2*module.MAX_ENTITIES+module.MAX_AGENTS+1
    cache.close()


def test_remote_prepared_progress_is_atomic_and_does_not_import_agents(tmp_path):
    local=_ready(tmp_path,name='local')
    remote=_ready(tmp_path,name='remote')
    remote.register_agent('remote-agent')
    local._db.execute("UPDATE entity_queue SET status='pending'")
    path=tmp_path/'remote.parquet'; _snapshot(remote,path)
    before=local._db.execute('SELECT * FROM agent_lease').fetchall()
    result=local.upsert_remote_resume(path,agent_id='local-agent')
    assert result==dict(admitted=False,formalized=False,claimed=0,prepared=1)
    assert local._db.execute('SELECT * FROM agent_lease').fetchall()==before
    assert local.checkpoint()['next_ordinal']==1
    local.close(); remote.close()


def test_remote_claims_never_become_local_ownership(tmp_path):
    local=_ready(tmp_path,name='local'); remote=_ready(tmp_path,name='remote')
    local._db.execute("UPDATE entity_queue SET status='pending'")
    remote._db.execute("UPDATE entity_queue SET status='pending'")
    remote.claim_batch('foreign-agent',limit=1)
    path=tmp_path/'remote.parquet'; _snapshot(remote,path)
    before=_state(local)
    result=local.upsert_remote_resume(path,agent_id='local-agent')
    assert result['claimed']==result['prepared']==0
    assert local.stats()['pending']==1
    assert local._db.execute('SELECT count(*) FROM agent_lease').fetchone()==(0,)
    assert local._db.execute('SELECT claim_worker,claim_token FROM entity_queue').fetchone()==('','')
    assert local.checkpoint()['next_ordinal']==1
    local.close(); remote.close()


def test_remote_prepared_observation_cannot_complete_existing_local_claim(tmp_path):
    local=_ready(tmp_path,name='local'); remote=_ready(tmp_path,name='remote')
    local._db.execute("UPDATE entity_queue SET status='pending'")
    claim=local.claim_batch('local-agent',limit=1)[0]
    path=tmp_path/'remote.parquet'; _snapshot(remote,path)
    assert local.upsert_remote_resume(path,agent_id='local-agent')['prepared']==0
    assert local._db.execute('SELECT status,claim_token FROM entity_queue').fetchone()==('claimed',claim['claim_token'])
    local.close(); remote.close()


def test_remote_prepared_progress_requires_locally_sealed_context(tmp_path):
    local=_bound(tmp_path,[_row()],name='local'); remote=_ready(tmp_path,name='remote')
    path=tmp_path/'remote.parquet'; _snapshot(remote,path)
    with pytest.raises(module.EntityCacheError,match='containment'):
        local.upsert_remote_resume(path,agent_id='local-agent')
    assert local.stats()['pending']==1
    local.close(); remote.close()


@pytest.mark.parametrize('mutation',['authority','binding','properties','context','missing_board','duplicate_entity','agent_count','meta_cursor'])
def test_remote_snapshot_validation_rejects_before_committing(tmp_path,mutation):
    local=_ready(tmp_path,name='local'); remote=_ready(tmp_path,name='remote')
    local._db.execute("UPDATE entity_queue SET status='pending'")
    remote.register_agent('agent')
    path=tmp_path/'remote.parquet'; _snapshot(remote,path)
    def alter(rows):
        entity=next(row for row in rows if row['record_kind']=='entity')
        if mutation=='authority': entity['admitted']=True
        elif mutation=='binding': entity['input_id']='sha256:'+'c'*64
        elif mutation=='properties':
            entity['properties_json']='{"different":true}'
            entity['source_sha256']=module._entity_record(entity)[4]
        elif mutation=='context': entity['context_json']='{"injected":true}'
        elif mutation=='missing_board': rows[:]=[row for row in rows if row['record_kind']!='board']
        elif mutation=='duplicate_entity': rows.append(copy.deepcopy(entity))
        elif mutation=='agent_count': next(row for row in rows if row['record_kind']=='agent')['entities']=1
        else: next(row for row in rows if row['record_kind']=='meta')['entities']=0
    _mutate_snapshot(path,alter)
    before=_state(local)
    with pytest.raises(module.EntityCacheError): local.upsert_remote_resume(path,agent_id='local-agent')
    assert _state(local)==before
    local.close(); remote.close()


def test_remote_final_file_guard_failure_rolls_back_updates(tmp_path,monkeypatch):
    local=_ready(tmp_path,name='local'); remote=_ready(tmp_path,name='remote')
    local._db.execute("UPDATE entity_queue SET status='pending'")
    path=tmp_path/'remote.parquet'; _snapshot(remote,path)
    before=_state(local)
    def fail(*args): raise module.EntityCacheError('late source drift')
    monkeypatch.setattr(module,'_resume_current',fail)
    with pytest.raises(module.EntityCacheError,match='late source drift'):
        local.upsert_remote_resume(path,agent_id='local-agent')
    assert _state(local)==before
    local.close(); remote.close()


def test_export_and_import_use_bounded_arrow_batches(tmp_path,monkeypatch):
    rows=[_row('doc:'+str(index)) for index in range(130)]
    cache=_ready(tmp_path,rows)
    path=tmp_path/'resume.parquet'; _snapshot(cache,path)
    seen=[]
    original=module._validate_resume_row
    def observe(row,binding):
        seen.append(row['record_kind'])
        return original(row,binding)
    monkeypatch.setattr(module,'_validate_resume_row',observe)
    summary=cache.resume_summary(path)
    assert len(seen)==261 and summary['kinds']==dict(meta=1,entity=130,board=130)
    parquet=pq.ParquetFile(path)
    assert max(parquet.metadata.row_group(i).num_rows for i in range(parquet.metadata.num_row_groups))<=64
    cache.close()


@pytest.mark.parametrize('bound,value',[('MAX_ENTITIES',1),('MAX_RESUME_DECODED_BYTES',100),('MAX_RESUME_FILE_BYTES',100)])
def test_snapshot_limits_fail_without_publishing_partial_output(tmp_path,monkeypatch,bound,value):
    cache=_ready(tmp_path,[_row(),_row('doc:2')])
    before=_state(cache)
    monkeypatch.setattr(module,bound,value)
    path=tmp_path/'resume.parquet'
    with pytest.raises(module.EntityCacheError): cache.write_resume_parquet(path)
    assert not path.exists()
    assert not list(tmp_path.glob('.*.tmp'))
    assert _state(cache)==before
    cache.close()


@pytest.mark.parametrize('target',['db','wal','hardlink','symlink'])
def test_resume_output_cannot_overlap_cache_or_alias(tmp_path,target):
    cache=_ready(tmp_path)
    if target=='db': path=cache.path
    elif target=='wal': path=Path(str(cache.path)+'.wal')
    elif target=='hardlink':
        path=tmp_path/'linked.parquet'; os.link(cache.path,path)
    else:
        path=tmp_path/'linked.parquet'; path.symlink_to(cache.path)
    before=_state(cache)
    with pytest.raises(module.EntityCacheError): cache.write_resume_parquet(path)
    assert _state(cache)==before
    cache.close()


def test_existing_snapshot_survives_failed_replacement(tmp_path,monkeypatch):
    cache=_ready(tmp_path)
    path=tmp_path/'resume.parquet'; _snapshot(cache,path)
    before=path.read_bytes()
    def fail(*args): raise module.EntityCacheError('failed validation')
    monkeypatch.setattr(module,'_stage_resume',fail)
    with pytest.raises(module.EntityCacheError): cache.write_resume_parquet(path)
    assert path.read_bytes()==before
    cache.close()


def test_claim_token_fences_exact_batch_and_counts_only_current_matches(tmp_path):
    cache=module.EntityCache(tmp_path/'cache.duckdb')
    cache.enqueue([_row('a'),_row('b')])
    first=cache.claim_batch('agent',limit=1)[0]
    second=cache.claim_batch('other',limit=1)[0]
    before=_state(cache)
    with pytest.raises(module.EntityCacheError):
        cache.prepare_claimed(['a','b'],agent_id='agent',claim_token=first['claim_token'])
    assert _state(cache)==before
    assert cache.prepare_claimed(['a','missing'],agent_id='agent',claim_token=first['claim_token'])==1
    assert cache.prepare_claimed(['a'],agent_id='agent',claim_token=first['claim_token'])==0
    with pytest.raises(TypeError): cache.prepare_claimed(['b'],agent_id='other')
    assert cache.prepare_claimed(['b'],agent_id='other',claim_token=second['claim_token'])==1
    cache.close()


def test_task_board_ids_bind_full_entity_identity_not_shared_prefix(tmp_path):
    prefix='bafk'+'x'*70
    cache=_ready(tmp_path,[_row(prefix+'a'),_row(prefix+'b')])
    cache.refresh_task_board()
    actual=cache._db.execute('SELECT task_id,entity_id FROM task_board ORDER BY entity_id').fetchall()
    assert actual==[('AFTD-E-'+hashlib.sha256(eid.encode()).hexdigest(),eid) for eid in (prefix+'a',prefix+'b')]
    assert len({row[0] for row in actual})==2
    cache.close()


def test_definition_closure_is_two_edges_with_all_direct_targets_and_false_flags(tmp_path):
    rows=[_row('doc:1'),_row('section:1','section'),_row('title:1','usc_title')]
    edges=[dict(type='HAS_SECTION',source='doc:1',target='section:1'),dict(type='IN_TITLE',source='doc:1',target='title:1')]
    cache=_ready(tmp_path,rows,edges)
    cites=[dict(source_legal_id='usc:us:1:1',target_legal_id=target) for target in ('a','b','c','d')]
    cites += [dict(source_legal_id='a',target_legal_id='e'),dict(source_legal_id='e',target_legal_id='third'),
              dict(source_legal_id='b',target_legal_id='',unresolved=True)]
    result=cache.assign_definition_closure(cites)
    context=json.loads(cache._db.execute("SELECT context_json FROM entity_queue WHERE entity_type='section'").fetchone()[0])
    assert context['definition_targets']==['a','b','c','d','e']
    assert context['definition_hops']==2 and 'unresolved_citation' in context['reasons']
    assert result['admitted'] is False
    proof=module.proof_sources_for_section(context,[])
    assert proof['admitted'] is proof['formalized'] is False
    cache.close()


@pytest.mark.parametrize('operation',['claim','prepare_all','prepare_claimed'])
def test_bound_preparation_cannot_bypass_containment_seal(tmp_path,operation):
    cache=_bound(tmp_path,[_row()])
    before=_state(cache)
    with pytest.raises(module.EntityCacheError,match='sealed containment'):
        if operation=='claim': cache.claim_batch('worker',limit=1)
        elif operation=='prepare_all': cache.prepare_all()
        else: cache.prepare_claimed(['doc:1'],agent_id='worker',claim_token='1'*32)
    assert _state(cache)==before
    cache.close()


@pytest.mark.parametrize('operation',['spans','definitions','reopen'])
def test_context_mutators_cannot_change_active_claimed_section(tmp_path,operation):
    rows=[_row('section:1','section')]
    cache=_ready(tmp_path,rows)
    context={'span_legal_id':'usc:us:1:1','definition_targets':['target']}
    cache._db.execute("UPDATE entity_queue SET status='pending',context_json=?",[module._json(context)])
    claim=cache.claim_batch('worker',limit=1)[0]
    before=_state(cache)
    with pytest.raises(module.EntityCacheError,match='claim'):
        if operation=='spans': cache.assign_span_context([dict(legal_id='usc:us:1:1',id='span')])
        elif operation=='definitions': cache.assign_definition_closure([dict(source_legal_id='usc:us:1:1',target_legal_id='other')])
        else: cache.reopen_definition_targets(['target'])
    assert _state(cache)==before
    assert cache._db.execute('SELECT claim_token FROM entity_queue').fetchone()==(claim['claim_token'],)
    cache.close()


@pytest.mark.parametrize('operation',['spans','definitions','inconsistencies','reopen'])
def test_malformed_stored_context_is_never_replaced_by_empty_object(tmp_path,operation):
    cache=_ready(tmp_path,[_row('section:1','section')])
    cache._db.execute("UPDATE entity_queue SET context_json='{broken'")
    before=_state(cache)
    with pytest.raises(module.EntityCacheError,match='context'):
        if operation=='spans': cache.assign_span_context([])
        elif operation=='definitions': cache.assign_definition_closure([])
        elif operation=='inconsistencies': cache.record_inconsistencies([])
        else: cache.reopen_definition_targets(['target'])
    assert _state(cache)==before
    cache.close()


def test_remote_preparation_rejects_stale_local_containment_seal(tmp_path):
    local=_ready(tmp_path,name='local'); remote=_ready(tmp_path,name='remote')
    local._db.execute("UPDATE entity_queue SET status='pending'")
    seal=json.loads(local._meta('containment_receipt'));seal['input_id']='sha256:'+'c'*64
    local._set_meta('containment_receipt',module._json(seal))
    path=tmp_path/'remote.parquet';_snapshot(remote,path)
    before=_state(local)
    with pytest.raises(module.EntityCacheError,match='seal binding'):
        local.upsert_remote_resume(path,agent_id='local')
    assert _state(local)==before
    local.close();remote.close()


def test_snapshot_commit_failure_preserves_old_complete_file(tmp_path):
    cache=_ready(tmp_path)
    path=tmp_path/'resume.parquet';_snapshot(cache,path)
    before=path.read_bytes();before_state=_state(cache)
    original=cache._db
    class CommitFailure:
        def __getattr__(self,name): return getattr(original,name)
        def execute(self,sql,*args,**kwargs):
            if sql=='COMMIT': raise RuntimeError('injected commit failure')
            return original.execute(sql,*args,**kwargs)
    cache._db=CommitFailure()
    with pytest.raises(RuntimeError,match='commit failure'): cache.write_resume_parquet(path)
    cache._db=original
    assert path.read_bytes()==before and _state(cache)==before_state
    assert not list(tmp_path.glob('.*.tmp'))
    cache.close()


def test_public_methods_reject_foreign_owner_before_database_access(tmp_path,monkeypatch):
    cache=_ready(tmp_path)
    before=_state(cache)
    monkeypatch.setattr(module.os,'getpid',lambda:cache._owner[0]+1)
    with pytest.raises(module.EntityCacheError,match='owner'): cache.refresh_task_board()
    with pytest.raises(module.EntityCacheError,match='owner'): cache.assign_span_context([])
    with pytest.raises(module.EntityCacheError,match='owner'): cache.record_inconsistencies([])
    monkeypatch.undo()
    assert _state(cache)==before
    cache.close()


def test_changed_live_constraints_rejected_despite_exact_columns_and_marker(tmp_path):
    path=tmp_path/'cache.duckdb'
    cache=module.EntityCache(path)
    original_columns=cache._schema_columns(cache._db)
    cache.close()
    db=duckdb.connect(str(path),config={'threads':1})
    db.execute('DROP TABLE agent_lease')
    db.execute('CREATE TABLE agent_lease (agent_id VARCHAR NOT NULL,dataset_id VARCHAR NOT NULL,'
               'role VARCHAR NOT NULL,heartbeat VARCHAR NOT NULL,claimed_count INTEGER NOT NULL,'
               'admitted BOOLEAN NOT NULL,formalized BOOLEAN NOT NULL)')
    assert module.EntityCache._schema_columns(db)==original_columns
    db.close()
    before={p.name:p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises(module.EntityCacheError,match='schema differs'):
        module.EntityCache(path)
    assert {p.name:p.read_bytes() for p in tmp_path.iterdir()}==before
