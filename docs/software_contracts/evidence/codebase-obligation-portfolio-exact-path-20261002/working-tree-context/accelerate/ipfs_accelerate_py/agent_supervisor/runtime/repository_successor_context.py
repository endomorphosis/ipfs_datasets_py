"""Fresh finite repository context with an independently signed new baseline.

Historical receipts remain immutable. Source-root invalidation is conservative:
every bounded reverse reference to the predecessor snapshot is rechecked. This
module grants neither task omission nor automatic dispatch of satisfied tasks.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import hashlib
import importlib
import fcntl
import os
import stat
import tempfile
import uuid
import math
import json
from pathlib import Path
import time

from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead, CodebaseCatalog
from ipfs_datasets_py.duckdb_control.intent_codebase_catalog import IntentCodebaseCatalog
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts.codebase_integer_profile import IntegerOffsetContract
from ipfs_datasets_py.logic.software_contracts.codebase_scan_policy import prepare_policy_current
from ipfs_datasets_py.logic.software_contracts.codebase_semantic_manifest import build_codebase_semantic_manifest
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.logic.software_contracts.content import cid_for_structured
from ..entrypoints.facade import Supervisor
from ..planning.behavioral_codebase_match import match_behavioral_intent
from ..proof.finite_checked_cache import FiniteCheckedCache
from ..proof.formal_verification_cache import FormalVerificationCache
from ..proof.formal_verification_contracts import content_identity
from ..prompt.prompt_workflow import PromptGoalGraph
from ..task_sources.intent_repository import IntentRepository
from . import local_planning_admission as local
from . import repository_behavioral_admission as predecessor
from . import repository_finite_handoff as finite
from . import repository_finite_public_context as public

SCHEMA = "repository-finite-successor-context@1"
FALSE = dict(execution_authority=False, completion_authority=False, omission_authority=False,
             source_equivalence_proved=False, model_inference_used=False)


def _require(value, message):
    if not value:
        raise ValueError(message)


def _pins():
    names={__name__,Supervisor.__module__,PromptGoalGraph.__module__,IntentRepository.__module__,
        prepare_policy_current.__module__,build_codebase_semantic_manifest.__module__,
        DuckDBASTStore.__module__,DuckDBASTIngestor.__module__,CodebaseCatalog.__module__}
    return {**predecessor._pins(),**{name:hashlib.sha256(Path(importlib.import_module(name).__file__).read_bytes()).hexdigest()
        for name in sorted(names)}}


def _graph_successor(graph, roots, lineage_cid):
    """Change only declared identity keys/references; preserve every task body."""
    _require(type(graph) is PromptGoalGraph and not graph.evidence and not graph.unresolved_questions
        and not graph.uncertainty_debt and graph.policy_roots == (content_identity(local.LOCAL_POLICY),),
        "closed independent local graph required")
    key = lambda kind, old: "SUCCESSOR-" + hashlib.sha256((kind+old+lineage_cid).encode()).hexdigest()[:24]
    goals, pending, goal_ids = [], list(graph.goals), {}
    while pending:
        ready = [row for row in pending if (not row.parent_goal_cid or row.parent_goal_cid in goal_ids)
            and all(v in goal_ids for v in row.dependency_goal_cids)]
        _require(ready, "successor goal dependency population is cyclic")
        for row in ready:
            new=replace(row,goal_key=key('goal',row.goal_cid),
                parent_goal_cid=goal_ids.get(row.parent_goal_cid,''),
                dependency_goal_cids=tuple(goal_ids[v] for v in row.dependency_goal_cids))
            goals.append(new);goal_ids[row.goal_cid]=new.goal_cid;pending.remove(row)
    tasks, pending, task_ids = [], list(graph.tasks), {}
    while pending:
        ready=[row for row in pending if all(v in task_ids for v in row.dependency_task_cids)]
        _require(ready, "successor task dependency population is cyclic")
        for row in ready:
            new=replace(row,task_key=key('task',row.task_cid),goal_cid=goal_ids[row.goal_cid],
                dependency_task_cids=tuple(task_ids[v] for v in row.dependency_task_cids))
            tasks.append(new);task_ids[row.task_cid]=new.task_cid;pending.remove(row)
    result=replace(graph,**roots,goals=tuple(goals),tasks=tuple(tasks))
    result=PromptGoalGraph.from_dict(result.to_dict())
    _require(len(result.tasks)==len(graph.tasks) and set(task_ids).isdisjoint(task_ids.values()),
        "new native identities must retain every original task")
    return result,dict(goals=goal_ids,tasks=task_ids)


def _specs(graph):
    names={row.task_cid:row.task_key for row in graph.tasks}
    return [dict(task_key=row.task_key,scope_paths=list(row.scope_paths),
        dependencies=sorted(names[v] for v in row.dependency_task_cids),
        outputs=[{k:getattr(v,k) for k in ('path','effect','media_type')} for v in row.outputs],
        validations=[{k:local._plain(getattr(v,k)) for k in ('validation_key','argv','cwd','expected_exit_codes','policy_cid')} for v in row.validations],
        acceptance=[{k:local._plain(getattr(v,k)) for k in ('criterion_key','criterion','evidence_cids','validation_keys')} for v in row.acceptance])
        for row in graph.tasks]


def _semantics(match):
    native=match['fresh_match']
    result={k:native[k] for k in ('status','source_cid','domain_cid','domain_inputs','eligible_clause_ids',
        'residual_clause_ids','finite_counterexamples','query')}
    result['source_snapshot_cid']=native['head']['snapshot_cid']
    result['clause_results']=[{k:v for k,v in row.items() if k!='predicate_id'} for row in native['clause_results']]
    historical={'artifacts','head','lean_certificate','output','python_process','result_cid'}
    result['observation_semantics']={k:v for k,v in native['observation'].items() if k not in historical}
    return result


@contextmanager
def _state_lock(state):
    """The journal is a retry locator, never saved proof authority."""
    try: state.mkdir(mode=0o700)
    except FileExistsError: pass
    info=state.lstat()
    _require(stat.S_ISDIR(info.st_mode) and info.st_uid==os.geteuid()
        and stat.S_IMODE(info.st_mode)==0o700 and state.resolve()==state,
        'private canonical successor state required')
    fd=os.open(state/'lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        info=os.fstat(fd)
        _require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_uid==os.geteuid()
            and stat.S_IMODE(info.st_mode)==0o600,'private successor lock required')
        try: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as error: raise ValueError('successor preparation already running') from error
        yield
    finally: os.close(fd)


def _journal(path,value):
    raw=finite._wire(value)
    _require(len(raw)<=256*1024,'bounded successor retry journal required')
    if not path.exists():
        # A killed writer can leave its immutable temporary, never a partial
        # final journal. Linking and parent fsync precede any source mutation.
        temp=path.with_name(path.name+'.'+uuid.uuid4().hex)
        finite._persist(temp,raw)
        try: os.link(temp,path)
        except FileExistsError: pass
        finally: temp.unlink()
        fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)
    directory=predecessor._directory(path.parent)
    try: actual,info=predecessor._read(directory,path.name)
    finally: os.close(directory)
    _require(info.st_uid==os.geteuid() and stat.S_IMODE(info.st_mode)==0o444 and actual==raw,
        'successor retry request differs from immutable journal')


def _materialize_or_replay(admission,intent):
    """Replay only the exact untouched native population after a lost reply."""
    _require(isinstance(intent,IntentRepository) and not intent.uses_bound_connection,
        'independent native Intent transaction required')
    with intent._connection(write=True) as cx:
        with IntentRepository(bound_connection=cx,owner_id=intent.owner_id,session_id=intent.session_id) as owner:
            return _materialize_or_replay_owned(admission,owner)


def _materialize_or_replay_owned(admission,owner):
    """Use an existing owner transaction to join admission with another native record."""
    _require(isinstance(owner,IntentRepository) and owner.uses_bound_connection,
        'bound native Intent transaction required')
    verified=local.verify_local_benchmark_admission(admission,initial=True)
    manifest,graph,receipt=(verified[k] for k in ('manifest','graph','receipt'))
    objective=content_identity(dict(manifest=receipt['manifest_cid'],objective=graph.root_goal.objective))
    rows=[owner.get_task(task.task_cid) for task in graph.tasks]
    if not any(row is not None for row in rows):
        _require(owner.get_objective(objective) is None and owner.get_plan(receipt['plan_id']) is None
            and all(owner.get_goal(goal.goal_cid) is None for goal in graph.goals),
            'partial successor native parents cannot be overwritten')
        result=local._materialize_local_benchmark_plan(admission=admission,intent=owner)
    else:
        _require(all(row is not None for row in rows),'partial successor task population cannot replay')
        for task,row in zip(graph.tasks,rows):
            contract=local._pending_contract_payload(admission=admission,verified=verified,task=task,intent_owner_id=owner.owner_id)
            signed=local._signed(contract,manifest);spec=contract['task_spec']
            expected=dict(task_cid=task.task_cid,task_alias=task.task_key,goal_cid=task.goal_cid,
                plan_cid=receipt['plan_id'],objective_id=objective,status='ready',revision=1,ordinal=0,priority='P2',
                body={'title':task.objective,local.CONTRACT_KEY:signed},
                identity=dict(local_contract_cid=content_identity(signed),repository_tree_id=receipt['source_tree_id'],
                    task_cid=task.task_cid,task_alias=task.task_key),
                dependencies=sorted(contract['dependencies']),
                outputs=[dict(ordinal=i,path=v['path'],effect=v) for i,v in enumerate(spec['outputs'])],
                acceptance=[dict(ordinal=i,criterion=v['criterion'],evidence_policy=v) for i,v in enumerate(spec['acceptance'])],
                validations=[dict(ordinal=i,argv=v['argv'],policy={k:x for k,x in v.items() if k!='argv'}) for i,v in enumerate(spec['validations'])])
            _require(all(local._plain(row[k])==local._plain(v) for k,v in expected.items()),
                'materialized successor native task changed before retry')
            local._contract(row['body'],task.task_cid)
        result=dict(schema='supervisor-local-materialization@1',plan_id=receipt['plan_id'],
            task_cids=sorted(task.task_cid for task in graph.tasks),pending_cid=receipt['pending_cid'],
            manifest_cid=receipt['manifest_cid'],completion_authority=False)
    expected_objective=dict(objective_id=objective,objective_alias='LOCAL-OBJECTIVE-'+objective[-12:],
        parent_objective_id='',title=graph.root_goal.objective,status='open',priority='P2',revision=1,body={})
    def exact(row,expected):
        return row is not None and all(local._plain(row[k])==local._plain(v) for k,v in expected.items())
    _require(exact(owner.get_objective(objective),expected_objective),'successor native objective changed before retry')
    for goal in graph.goals:
        expected_goal=dict(goal_cid=goal.goal_cid,goal_alias=goal.goal_key,objective_id=objective,
            parent_goal_cid=goal.parent_goal_cid,ordinal=0,title=goal.title,status='open',revision=1,
            body={'local_manifest_cid':receipt['manifest_cid']})
        _require(exact(owner.get_goal(goal.goal_cid),expected_goal),'successor native goal changed before retry')
    reference=local._receipt_reference(admission['receipt'],local._receipt_bytes(admission['receipt']))
    expected_plan=dict(plan_cid=receipt['plan_id'],goal_cid=graph.root_goal.goal_cid,
        plan_alias='LOCAL-PLAN-'+receipt['plan_id'][-12:],status='active',revision=1,
        body={'local_planning_receipt_ref':reference})
    _require(exact(owner.get_plan(receipt['plan_id']),expected_plan),'successor native plan changed before retry')
    head=owner.get_plan_head(graph.root_goal.goal_cid)
    _require(head is not None and head.plan_cid==receipt['plan_id'] and head.revision==1
        and head.status=='active' and not head.superseded_by and not head.continuation_of,
        'successor native plan head changed before retry')
    with owner._connection(write=True) as cx:
        active=cx.execute("SELECT plan_cid FROM plans WHERE goal_cid=? AND status='active'",
            [graph.root_goal.goal_cid]).fetchall()
    _require([row[0] for row in active]==[receipt['plan_id']],'successor native plan head population changed before retry')
    _require(local.load_local_planning_receipt(reference,manifest=admission['manifest'])==admission['receipt'],
        'successor native planning receipt changed before retry')
    local._manifest(admission['manifest'],initial=True)
    return result

def prepare_repository_successor_context(*, historical_artifact, historical_sha256,
        task_cid, owner_did, profile_id, catalog, checked_cache, intent, state,
        scheduler=None, parent_lease=None, cancel_event=None, timeout_seconds=300):
    """Prepare or safely retry the same explicitly committed successor.

    Each attempt obtains fresh native proof evidence and an independent cold
    rebuild. A durable source operation can replay; saved evidence cannot.
    """
    state=Path(state).absolute()
    _require(state.resolve()==state,'canonical successor state required')
    old=predecessor._load(artifact=historical_artifact,expected_sha256=historical_sha256,
        task_cid=task_cid,owner_did=owner_did,profile_id=profile_id)
    repository=Path(old['repository'])
    _require(not state.is_relative_to(repository),'successor state must be outside source repository')
    _require(local._git(repository,'rev-parse','HEAD')!=old['legacy_signed_evidence']['payload']['baseline_commit'],
        'committed successor baseline required')
    with _state_lock(state):
        return _prepare_repository_successor_context(historical_artifact=historical_artifact,historical_sha256=historical_sha256,
            task_cid=task_cid,owner_did=owner_did,profile_id=profile_id,catalog=catalog,checked_cache=checked_cache,
            intent=intent,state=state,scheduler=scheduler,parent_lease=parent_lease,cancel_event=cancel_event,
            timeout_seconds=timeout_seconds)


def _prepare_repository_successor_context(*, historical_artifact, historical_sha256,
        task_cid, owner_did, profile_id, catalog, checked_cache, intent, state,
        scheduler=None, parent_lease=None, cancel_event=None, timeout_seconds=300):
    """Capture and check a committed successor; sign full independently admitted tasks.

    The caller owns the existing source/discovery/cache/Intent owners. Source
    publication may already have occurred; exact durable retries also accept
    only the current head published by this same successor operation.
    """
    import duckdb
    _require(type(timeout_seconds) in (int,float) and math.isfinite(timeout_seconds) and 0<timeout_seconds<=300,
        'bounded successor preparation deadline required')
    _require(cancel_event is None or callable(getattr(cancel_event,'is_set',None)),'cooperative successor cancellation required')
    state=Path(state).absolute()
    old=predecessor._load(artifact=historical_artifact,expected_sha256=historical_sha256,
        task_cid=task_cid,owner_did=owner_did,profile_id=profile_id)
    repository=Path(old['repository']);old_head=CodebaseHead.from_dict(old['source_head'])
    _require(not state.is_relative_to(repository) and predecessor._roots(catalog,checked_cache)==old['owner_roots']
        ,'exact predecessor owners required')
    _require(Path(intent.database_path).resolve()!=Path(old['owner_roots']['source_database']['path']),
        'successor source and Intent database owners must be separate')
    public.load_finite_public_context(artifact=old['public_context']['artifact'],expected_sha256=old['public_context']['sha256'],
        owner_did=owner_did,profile_id=profile_id,task_cid=task_cid,handoff_sha256=old['legacy_handoff']['sha256'])
    commit=local._git(repository,'rev-parse','HEAD')
    _require(commit!=old['legacy_signed_evidence']['payload']['baseline_commit'], 'committed successor baseline required')
    source_text=old['source_text'];document=json.loads(old['intent_document'])
    query=old['behavioral_match']['fresh_match']['query'];contract=IntegerOffsetContract.from_dict(query['contract'])
    refs=checked_cache.dependents('snapshot',old_head.snapshot_cid,limit=64)
    historical=old['behavioral_match']['checked_cache']
    _require(any(all(ref[k]==historical[k] for k in ('request_key','record_cid')) for ref in refs),
        'historical admission evidence is missing from predecessor dependencies')
    old_records=[checked_cache.artifacts.get(ref['record_cid']) for ref in refs]
    for record in old_records:
        material=record['correspondence']['materials']
        _require(material['source']['head']==old_head.to_dict()
            and all(material['obligation']['contract'][key]==contract.to_dict()[key]
                for key in ('path','function_name','parameter'))
            and material['policy']['native_tools']==old['tool_policy'],
            'affected cache population exceeds the declared finite successor profile')
    deadline=time.monotonic()+timeout_seconds
    pins=_pins();own_pin=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    request=dict(schema='repository-successor-retry-request@1',historical_sha256=historical_sha256,
        task_cid=task_cid,owner_did=owner_did,profile_id=profile_id,repository=str(repository),
        successor_commit=commit,owner_roots=old['owner_roots'],intent_database=predecessor._entry(Path(intent.database_path)),
        predecessor_head=old_head.to_dict(),affected=refs,producers=pins,
        sources=local._sources(repository,[n for n in local._git(repository,'ls-files','-z').split('\0') if n]))
    _journal(state/'request.json',request)
    operation_id='successor:'+finite._sha(finite._wire(request))
    current_head=catalog.index.current(old_head.repository_id)
    replayed=current_head!=old_head
    if replayed:
        _require(current_head is not None,'successor source head disappeared')
        material=catalog.index.load(current_head.manifest_cid)
        request_cid=catalog.index.catalog.request_identity(material,old_head)
        published=catalog.index.catalog.resolve_operation(operation_id,request_cid)
        _require(published is not None and published.head==current_head and published.previous_head==old_head,
            'current source head is not this exact durable successor operation')
    attempts=state/'attempts';attempts.mkdir(mode=0o700,exist_ok=True)
    _require(not attempts.is_symlink() and attempts.resolve()==attempts and len(list(attempts.iterdir()))<16,
        'successor retry attempt population exceeds bound')
    attempt=Path(tempfile.mkdtemp(prefix='attempt-',dir=attempts))
    def resources():
        _require(cancel_event is None or not cancel_event.is_set(),'successor preparation cancelled')
        left=deadline-time.monotonic();_require(left>0,'successor preparation deadline expired')
        return dict(scheduler=scheduler,parent_lease=parent_lease,cancel_event=cancel_event,timeout_seconds=left)
    def capture(index, expected, label):
        controls=resources()
        observed=prepare_policy_current(index,repository,repository_id=old_head.repository_id,
            operation_id=label,expected_head=expected,training_paths=(),proof_paths=(contract.path,),**controls)
        semantic=build_codebase_semantic_manifest(index,policy_receipt_cid=observed['receipt_cid'],contracts=(contract,))
        return CodebaseHead.from_dict(observed['head']),semantic
    def request_fence():
        _require(checked_cache.dependents('snapshot',old_head.snapshot_cid,limit=64)==refs,
            'affected predecessor evidence population changed during preparation')
        _require(local._git(repository,'rev-parse','HEAD')==commit and
            local._sources(repository,[n for n in local._git(repository,'ls-files','-z').split('\0') if n])==request['sources'],
            'successor source or baseline changed during preparation')
    head,semantic=capture(catalog.index,old_head,operation_id)
    request_fence()
    catalog.publish(repository,expected_head=head,manifest_cid=semantic['manifest_cid'],operation_id='discovery:'+operation_id,**resources())
    def recheck(cache,index,head):
        results=[]
        for ref,record in zip(refs,old_records):
            material=record['correspondence']['materials']
            checked=cache.check_and_store(owner_inputs=dict(index=index,repository=repository,expected_head=head,
                contract=IntegerOffsetContract.from_dict(material['obligation']['contract']),
                inputs=material['obligation']['finite_domain']['inputs'],tool_policy=material['policy']['native_tools'],
                **{k:v for k,v in resources().items() if k!='timeout_seconds'}),timeout_seconds=resources()['timeout_seconds'])
            _require(checked['status'] in ('positive','refuted') and checked['fresh_native_observation'],
                'every affected request requires a fresh complete native checker')
            results.append(dict(predecessor_record=ref,successor_record={k:checked[k] for k in
                ('record_cid','request_key','status','positive_reuse_eligible')},
                semantic_request=material['obligation'],
                observation=cache.artifacts.get(checked['evidence']['bundle_cid'])['observation']))
        return results
    rechecked=recheck(checked_cache,catalog.index,head)
    native_args=dict(repository=repository,expected_head=head,semantic_manifest_cid=semantic['manifest_cid'],
        intent_document=document,source_text=source_text,tool_policy=old['tool_policy'])
    current=match_behavioral_intent(catalog=catalog,checked_cache=checked_cache,output=attempt/'current-observation',**native_args,**resources())
    _require(current['fresh_match']['observation'] is not None and current['fresh_match']['observation']['status']=='observed',
        'fresh complete successor native observation required')
    # Independent cold owner storage; no previous snapshot, parser or proof cache.
    with duckdb.connect(str(attempt/'cold.duckdb'),config={'threads':1,'memory_limit':'64MB'}) as cx:
        store=DuckDBASTStore(connection=cx);cas=ImmutableCAS(attempt/'cold-cas')
        cold_index=RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store),artifacts=cas,catalog=CodebaseCatalog(store,cas))
        cold_head,cold_semantic=capture(cold_index,None,'cold-successor:'+historical_sha256)
        cold_catalog=IntentCodebaseCatalog(cold_index)
        cold_catalog.publish(repository,expected_head=cold_head,manifest_cid=cold_semantic['manifest_cid'],operation_id='cold-successor',**resources())
        cold_cache=FiniteCheckedCache(FormalVerificationCache(attempt/'cold-proof'/'formal_verification_cache.duckdb',exact_path=True),cas)
        cold_rechecked=recheck(cold_cache,cold_index,cold_head)
        for incremental,rebuilt in zip(rechecked,cold_rechecked):
            _require(incremental['semantic_request']==rebuilt['semantic_request']
                and incremental['successor_record']['status']==rebuilt['successor_record']['status']
                and all(incremental['observation'][k]==rebuilt['observation'][k]
                    for k in ('source_cid','domain_cid','observations','trace_cid','compiled_cid','tool_policy_cid',
                        'type_clause_satisfied','offset_clause_satisfied','runtime_observation_coverage_complete','kernel_checked_model_table')),
                'affected incremental and cold evidence disagree')
        cold=match_behavioral_intent(catalog=cold_catalog,checked_cache=cold_cache,
            output=attempt/'cold-observation',**{**native_args,'expected_head':cold_head,'semantic_manifest_cid':cold_semantic['manifest_cid']},**resources())
        _require(_semantics(current)==_semantics(cold),'incremental and independent cold eligible evidence/residuals disagree')
        left=catalog.artifacts.get(semantic['manifest_cid']);right=cas.get(cold_semantic['manifest_cid'])
        _require(all(left[k]==right[k] for k in ('units','declarations','coverage')),
            'incremental and cold semantic inventories disagree')
    lineage=dict(original_artifact_sha256=historical_sha256,original_artifact_cid=old['artifact_cid'],
        original_instruction_sha256=finite._sha(source_text.encode()),intent_document_json=old['intent_document'],
        predecessor_head=old_head.to_dict(),successor_head=head.to_dict(),baseline_commit=commit)
    sources=local._sources(repository,[n for n in local._git(repository,'ls-files','-z').split('\0') if n])
    roots=dict(request_cid=content_identity(lineage),scan_cid=content_identity(dict(sources=sources)),
        program_root=content_identity(dict(baseline_commit=commit,source_root=local._tree(sources))))
    graph=PromptGoalGraph.from_dict(json.loads(old['native_graph']))
    next_graph,identities=_graph_successor(graph,roots,content_identity(lineage))
    Supervisor.init_local(repository=repository,consent=True,profile_dir=state/'profile',lifecycle_dir=state/'lifecycle')
    request_fence()
    manifest=local.author_local_benchmark_manifest(repository=repository,profile_dir=state/'profile',
        lifecycle_dir=state/'lifecycle',task_specs=_specs(next_graph),planning_roots=roots)
    admission=local.admit_local_benchmark_plan(graph=next_graph,manifest=manifest)
    _require(pins==_pins() and own_pin==hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'successor producer changed')
    catalog.index.observe_current(repository,expected_head=head,**resources())
    verified=local.verify_local_benchmark_admission(admission,initial=True)
    payload=dict(schema=SCHEMA,lineage=lineage,source_text=source_text,
        old_native_task_population=old['native_task_population'],new_native_task_population=sorted(identities['tasks'].values()),
        identity_mapping=identities,admission_receipt=local._plain(admission['receipt']),new_graph_json=finite._wire(next_graph.to_dict()).decode(),
        semantic_manifest_cid=semantic['manifest_cid'],current_match=current,cold_match=cold,
        cold_semantics_agree=True,conservative_invalidation=dict(kind='all_exact_predecessor_snapshot_reverse_references',
            affected=refs,rechecked=rechecked,cold_rechecked=cold_rechecked,old_records_retained=True,eligible_under_successor=False,
            replacement_record=current['checked_cache'],all_declared_affected_obligations_rechecked=True),
        full_task_population_preserved=True,all_satisfied_tasks_automatically_dispatched=False,
        retry=dict(request_cid=cid_for_structured(request),source_operation_id=operation_id,source_operation_replayed=replayed,
            attempt_directory=str(attempt),saved_observations_reused=False),
        producers=pins,producer_sha256=own_pin,**FALSE)
    payload['context_cid']=cid_for_structured(payload)
    signed=local._signed(payload,verified['manifest'])
    _require(len(finite._wire(signed))<=2_000_000,'bounded successor context artifact required')
    catalog.index.observe_current(repository,expected_head=head,**resources())
    _require(pins==_pins(),'successor producer changed before native materialization')
    request_fence()
    materialized=_materialize_or_replay(admission,intent)
    path,digest=finite._public_artifact(repository,signed)
    return dict(schema=SCHEMA,status='successor_context_prepared',context_path=str(path),context_sha256=digest,
        signed_context=signed,admission=admission,materialized=materialized,
        semantic_manifest_cid=semantic['manifest_cid'],source_head=head.to_dict(),**FALSE)


__all__=['prepare_repository_successor_context']
