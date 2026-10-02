"""Derived bounded source/AST pages over the existing complete native owner.

Dirty capture, policy and globally resolved static edges remain owned by the
existing source index. This module publishes immutable projections and positional
cursors only; it owns no SQL table, source head, learned ranking or proof state.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import time

from .codebase_ir import RepositoryCodebaseIndex
from .codebase_resources import acquire_codebase_resources
from .codebase_scan_policy import load_policy_receipt
from .codebase_scan_policy_live import verify_policy_current
from .content import canonical_dag_json_bytes, cid_for_bytes, cid_for_structured, validate_cid
from ...duckdb_control.codebase_catalog import CodebaseHead
from ...optimizers.logic_theorem_optimizer.resource_scheduler import LeaseCancelledError, LeaseTimeoutError

SCHEMA='codebase-repository-shards@1'
PAGE_SCHEMA='codebase-repository-source-ast-page@1'
EDGE_SCHEMA='codebase-repository-global-dependency-pages@1'
CURSOR_SCHEMA='codebase-repository-page-position@1'
MAX_BODY=16*1024**2
FALSE=dict(proof_authority=False,source_runtime_semantics_verified=False,
    current_head_published=False,training_executed=False,inference_executed=False,
    execution_authority=False,completion_authority=False)


class RepositoryShardsError(ValueError):
    pass


def require(value,message):
    if not value:raise RepositoryShardsError(message)


@dataclass(frozen=True)
class RepositoryShardProfile:
    max_entries:int=256
    page_entries:int=16
    max_dependency_edges:int=16384
    max_page_bytes:int=1024*1024

    def __post_init__(self):
        for name,maximum in (('max_entries',256),('page_entries',16),('max_dependency_edges',16384),('max_page_bytes',1024*1024)):
            value=getattr(self,name)
            require(type(value) is int and 1<=value<=maximum,'bounded exact shard profile required: '+name)


def pins():
    from . import codebase_ir,codebase_scan_policy,codebase_scan_policy_live,ast_ir,content
    from .semantic_index import scanner,symbol_graph,models
    return {**{m.__name__:hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()
               for m in (codebase_ir,codebase_scan_policy,codebase_scan_policy_live,ast_ir,content,scanner,symbol_graph,models)},
            __name__:hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def _read(index,cid,bound=MAX_BODY):
    validate_cid(cid,codecs={'dag-json'})
    path=index.artifacts.path_for(cid)
    require(path.is_file() and path.stat().st_size<=bound,'bounded immutable shard artifact required')
    with path.open('rb') as stream:raw=stream.read(bound+1)
    require(len(raw)<=bound,'shard artifact grew beyond bound')
    value=json.loads(raw)
    require(canonical_dag_json_bytes(value)==raw and cid_for_structured(value)==cid,'exact immutable shard bytes differ')
    return value


def _body(value,bound=MAX_BODY):
    raw=canonical_dag_json_bytes(value)
    require(len(raw)<=bound,'shard metadata byte limit exceeded without truncation')
    return raw


def _derive(index,receipt_cid,profile,*,publish):
    require(type(index) is RepositoryCodebaseIndex and index.catalog is not None,'native source/catalog owner required')
    require(type(profile) is RepositoryShardProfile,'exact typed shard profile required')
    _read(index,receipt_cid)
    policy=load_policy_receipt(index,receipt_cid)
    head=CodebaseHead.from_dict(policy['head']);_read(index,head.manifest_cid)
    structural=index.load(head.manifest_cid)
    require(structural.snapshot.snapshot_cid==head.snapshot_cid and structural.ast_revision_id==head.ast_revision_id,
            'exact complete source head required')
    entries=sorted(structural.snapshot.entries,key=lambda e:e.source_key)
    require(len(entries)<=profile.max_entries,'complete inventory exceeds shard entry cap')
    units={u.source_key:u for u in structural.units}
    require(len(units)==len(entries),'whole source/AST inventory differs')
    page_rows=[]
    for ordinal,entry in enumerate(entries):
        unit=units[entry.source_key]
        if entry.is_opaque:
            disposition='deferred_large_file' if entry.opaque_reason in ('analysis_budget_exceeded','oversized') else 'opaque'
            inference='unsupported_source_disposition'
        elif not entry.path.endswith('.py'):disposition='captured_unindexed';inference='unsupported_language'
        elif unit.parse_status!='ok':disposition='captured_'+unit.parse_status;inference='unsupported_ast_disposition'
        else:disposition='captured_source_ast';inference='pending_source_conditioned_inference'
        page_rows.append(dict(ordinal=ordinal,path=entry.path,source_key=entry.source_key,entry_cid=entry.entry_cid,
            source_cid=entry.source_cid,ast_cid=unit.ast_cid,parse_status=unit.parse_status,
            source_disposition=disposition,source_reason=entry.opaque_reason,bytes=entry.size_bytes,
            inference_disposition=inference,proof_authority=False))
    pages=[]
    for start in range(0,len(page_rows),profile.page_entries):
        value=dict(schema=PAGE_SCHEMA,start_ordinal=start,stop_ordinal=min(start+profile.page_entries,len(page_rows)),
            rows=page_rows[start:start+profile.page_entries],**FALSE)
        _body(value,profile.max_page_bytes);cid=cid_for_structured(value)
        if publish:require(index.artifacts.put(value)==cid,'source/AST page identity changed')
        else:require(_read(index,cid,profile.max_page_bytes)==value,'source/AST page does not reconstruct')
        pages.append(cid)
    path_pages={row['path']:row['ordinal']//profile.page_entries for row in page_rows}
    state=structural.semantic_state
    owners={s.stable_id:path_pages.get(s.module_path) for s in state.symbols}
    owners.update({a.artifact_id:path_pages.get(a.path) for a in state.artifacts})
    require(len(state.edges)<=profile.max_dependency_edges,'whole global dependency edge cap exceeded')
    edges=[]
    for edge in state.edges:
        a,b=owners.get(edge.source_id),owners.get(edge.target_id)
        known=edge.source_id in owners and edge.target_id in owners
        disposition=('unresolved_or_external' if not known else 'repository_global' if a is None or b is None
                     else 'resolved_cross_shard' if a!=b else 'resolved_within_shard')
        edges.append(dict(edge=edge.to_dict(),source_page=a,target_page=b,disposition=disposition))
    dependencies=dict(schema=EDGE_SCHEMA,semantic_state_cid=state.state_cid,edges=edges,
        resolution_owner='existing_complete_RepositoryScanner_symbol_graph',
        global_resolution_scope='all_admitted_static_symbols_and_artifacts_with_explicit_external_frontiers',
        whole_program_semantics_verified=False,proof_authority=False)
    _body(dependencies);dependency_cid=cid_for_structured(dependencies)
    if publish:require(index.artifacts.put(dependencies)==dependency_cid,'dependency projection changed')
    else:require(_read(index,dependency_cid)==dependencies,'global dependency projection does not reconstruct')
    coverage=dict(structural.coverage)
    coverage.update(pages=len(pages),pending_inference=sum(r['inference_disposition']=='pending_source_conditioned_inference' for r in page_rows),
        dependency_edges=len(edges),cross_shard_edges=sum(e['disposition']=='resolved_cross_shard' for e in edges),
        unresolved_edges=sum(e['disposition']=='unresolved_or_external' for e in edges))
    result=dict(schema=SCHEMA,producer=pins(),profile=asdict(profile),source_head=head.to_dict(),policy_receipt_cid=receipt_cid,
        structural_manifest_cid=structural.cid,snapshot_cid=structural.snapshot.snapshot_cid,source_mode=structural.snapshot.mode,
        source_policy=policy['policy'],pages=pages,global_dependencies_cid=dependency_cid,
        coverage=coverage,ordering='native_raw_source_key',selection='complete_inventory_no_learned_rank_filter',
        source_observed_live=False,**FALSE)
    _body(result)
    return result


def prepare_repository_shards(index,repository,*,expected_head,policy_receipt_cid,profile=RepositoryShardProfile(),
        scheduler=None,parent_lease=None,cancel_event=None,timeout_seconds=120,memory_mb=512):
    """Publish only immutable derived pages after before/after native live fences."""
    require(type(expected_head) is CodebaseHead,'exact source head required')
    require(type(timeout_seconds) in (int,float) and math.isfinite(timeout_seconds) and 0<timeout_seconds<=300,
            'bounded shard preparation deadline required')
    deadline=time.monotonic()+timeout_seconds
    with acquire_codebase_resources(scheduler=scheduler,parent_lease=parent_lease,cancel_event=cancel_event,
            timeout_seconds=timeout_seconds,memory_mb=memory_mb) as lease:
        signal=lease.combined_cancellation_signal(cancel_event)
        def remaining():
            if signal.is_set():raise LeaseCancelledError('source shard request cancelled')
            duration=deadline-time.monotonic()
            if duration<=0:raise LeaseTimeoutError('source shard request expired')
            return duration
        def observe():
            verify_policy_current(index,repository,expected_head=expected_head,receipt_cid=policy_receipt_cid,
                parent_lease=lease,cancel_event=signal,timeout_seconds=remaining(),memory_mb=memory_mb)
        observe();producer=pins()
        value=_derive(index,policy_receipt_cid,profile,publish=True)
        require(value['source_head']==expected_head.to_dict(),'source policy binds another generation')
        observe();remaining();require(producer==pins(),'source shard producer changed during publication')
        cid=index.artifacts.put(value)
        return dict(root_cid=cid,coverage=value['coverage'],cursor=page_cursor(cid,0),source_observed_live=True,**FALSE)


def load_repository_shards(index,root_cid):
    """Cold owner/CAS reconstruction; no live-source claim or positive cache flag."""
    value=_read(index,root_cid)
    require(value.get('schema')==SCHEMA and value.get('producer')==pins(),'shard profile or producer differs')
    expected=_derive(index,value['policy_receipt_cid'],RepositoryShardProfile(**value['profile']),publish=False)
    require(_body(value)==_body(expected),'complete source shard root does not reconstruct')
    return expected


def page_cursor(root_cid,next_page):
    validate_cid(root_cid,codecs={'dag-json'})
    require(type(next_page) is int and 0<=next_page<=256,'bounded exact page position required')
    body=dict(schema=CURSOR_SCHEMA,root_cid=root_cid,next_page=next_page,
        authority='position_only_not_consumption_or_completion')
    return dict(**body,cursor_cid=cid_for_structured(body))


def read_repository_shard(index,root_cid,cursor):
    require(type(cursor) is dict and set(cursor)=={'schema','root_cid','next_page','authority','cursor_cid'},
            'closed root-bound page position required')
    require(cursor==page_cursor(root_cid,cursor['next_page']),'cursor belongs to another immutable inventory')
    value=load_repository_shards(index,root_cid);position=cursor['next_page']
    require(position<=len(value['pages']),'page position is outside complete inventory')
    if position==len(value['pages']):return dict(page=None,next_cursor=cursor,at_end=True,**FALSE)
    result=_read(index,value['pages'][position],value['profile']['max_page_bytes'])
    return dict(page=result,page_cid=value['pages'][position],next_cursor=page_cursor(root_cid,position+1),
        at_end=position+1==len(value['pages']),**FALSE)


__all__=['RepositoryShardProfile','prepare_repository_shards','load_repository_shards','read_repository_shard','page_cursor']
