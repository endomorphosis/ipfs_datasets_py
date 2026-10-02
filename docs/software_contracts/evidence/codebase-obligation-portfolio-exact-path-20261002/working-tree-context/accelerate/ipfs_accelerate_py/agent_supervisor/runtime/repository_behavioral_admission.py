"""Opt-in signed current-repository evidence fence around native task custody.

The independent local task admission remains the execution owner. This module
adds a freshly produced v2 planning snapshot and reopens existing evidence
owners before dispatch. A saved snapshot is not a live proof capability.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import stat
import tempfile
import time

from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog, CodebaseHead
from ipfs_datasets_py.duckdb_control.intent_codebase_catalog import IntentCodebaseCatalog, IntentCodebaseCatalogLimits
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.logic.software_contracts.content import cid_for_structured
from ..planning.behavioral_repository_plan import preview_behavioral_repository_plan, repository_evidence_binding
from ..planning.behavioral_codebase_match import match_behavioral_intent
from ..planning.plan_revision_contracts import plan_revision_cid
from ..proof.finite_checked_cache import FiniteCheckedCache
from ..proof.formal_verification_cache import FormalVerificationCache
from ..proof.formal_verification_contracts import content_identity
from . import local_planning_admission as local
from . import repository_finite_handoff as finite
from . import repository_finite_public_context as public
from .doctor_candidate_runner import _directory, _read, _unique

SCHEMA = "repository-behavioral-admission-fence@1"
FALSE = dict(execution_authority=False, completion_authority=False, omission_authority=False,
    proof_authority=False, model_inference_used=False, source_equivalence_proved=False)
PRODUCERS = (__name__,
    "ipfs_accelerate_py.agent_supervisor.runtime.repository_behavioral_runner",
    "ipfs_accelerate_py.agent_supervisor.runtime.repository_finite_handoff",
    "ipfs_accelerate_py.agent_supervisor.runtime.repository_finite_public_context",
    "ipfs_accelerate_py.agent_supervisor.runtime.repository_finite_runner",
    "ipfs_accelerate_py.agent_supervisor.runtime.local_planning_admission",
    "ipfs_accelerate_py.agent_supervisor.planning.behavioral_repository_plan",
    "ipfs_accelerate_py.agent_supervisor.planning.behavioral_codebase_match",
    "ipfs_datasets_py.duckdb_control.intent_codebase_catalog")
FIELDS = {"schema", "repository", "task_cid", "manifest_cid", "native_task_population",
    "native_graph", "native_planning_receipt", "legacy_signed_evidence",
    "original_request", "behavioral_request", "intent_document", "source_text", "tool_policy",
    "semantic_manifest_cid", "source_head", "proof_snapshot", "match_semantics", "behavioral_match", "behavioral_initial", "legacy_handoff",
    "public_context", "owner_roots", "producers", "artifact_cid", *FALSE}


def _require(value, message):
    if not value:
        raise ValueError(message)


def _pins():
    from ..proof import finite_cache_correspondence, finite_checked_cache
    names = sorted(set(PRODUCERS + finite_cache_correspondence.PRODUCERS + finite_checked_cache.EXECUTION_PRODUCERS))
    return {name: hashlib.sha256(Path(importlib.import_module(name).__file__).read_bytes()).hexdigest()
            for name in names}


def _entry(path, *, directory=False):
    path = Path(path)
    _require(path.is_absolute() and path.resolve(strict=True) == path and not path.is_symlink(),
             "existing canonical native owner path required")
    info = path.stat()
    _require((stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
             and not info.st_mode & 0o022, "native evidence owner path must not be group/world writable")
    return dict(path=str(path), device=info.st_dev, inode=info.st_ino, uid=info.st_uid,
                mode=stat.S_IMODE(info.st_mode), directory=directory)


def _roots(catalog, cache):
    _require(type(catalog) is IntentCodebaseCatalog and type(cache) is FiniteCheckedCache
             and catalog.index.artifacts is cache.artifacts
             and catalog.model_registry is None and catalog.corpus_catalog is None,
             "exact current model-off evidence owners required")
    _require(Path(catalog.catalog._database_path).resolve()!=cache.cache.path.resolve(),
        'source and proof stores must have separate native owners')
    return dict(source_database=_entry(catalog.catalog._database_path),
        artifacts=_entry(catalog.artifacts.root.resolve(), directory=True),
        proof_database=_entry(cache.cache.path.resolve()),
        discovery_limits=asdict(catalog.limits), cache_max_records=cache.max_records)


def _semantics(match):
    """Retain exact meaning; independently issued run/provenance IDs stay separate."""
    fresh = match["fresh_match"]
    return dict(source_head=match["source_head"], semantic_manifest_cid=match["semantic_manifest_cid"],
        query=fresh["query"], structural_context=fresh["structural_context"], model=match["model"],
        complete_inventory=match["complete_inventory"], unsupported_units=match["unsupported_units"],
        discovery=match["discovery"], checked_cache=match["checked_cache"],
        requirements=match["requirement_results"], satisfied=match["satisfied_requirements"],
        residuals=match["residual_requirements"], counterexamples=match["counterexamples"],
        fact_meanings=[{k: row[k] for k in ("predicate", "truth", "authority", "current_root_id", "invalidation_selectors")}
                       for row in fresh["current_facts"]])


def prepare_behavioral_repository_handoff(*, catalog, checked_cache, semantic_manifest_cid,
        owner, request, intent_document, source_text, operation_catalog, tool_policy,
        policy_observer, admission, intent, task_cid, state, instruction_path=None):
    """Invoke the actual v2 planner and native candidate owner before signing."""
    state = Path(state).absolute()
    output = state.with_name(state.name + "-behavioral-preview")
    _require(not state.exists() and not output.exists() and state.resolve()==state
        and not state.is_relative_to(owner.repository), "fresh exact external native evidence preparation outputs required")
    declared = local.verify_local_benchmark_admission(admission, initial=True)
    initial_roots, pins = _roots(catalog, checked_cache), _pins()
    _require(Path(initial_roots['source_database']['path']) != Path(intent.database_path).resolve(),
        'source catalog must be separate from the native Intent database')
    _require(owner.index is catalog.index and declared["manifest"]["repository"] == str(owner.repository),
             "planning and independently admitted repository owners differ")
    deadline = time.monotonic() + min(90, owner.timeout_seconds, request.budget.max_latency_ms/1000)
    def remaining():
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import LeaseCancelledError, LeaseTimeoutError
        if owner.cancel_event is not None and owner.cancel_event.is_set():
            raise LeaseCancelledError("behavioral preparation cancelled")
        value = deadline-time.monotonic()
        if value <= 0:
            raise LeaseTimeoutError("behavioral preparation deadline expired")
        return value
    binding = repository_evidence_binding(owner=owner, semantic_manifest_cid=semantic_manifest_cid,
        tool_policy=tool_policy, operation_catalog=operation_catalog)
    v2_roots = replace(request.roots, configuration_root=plan_revision_cid(binding))
    v2_request = replace(request, roots=v2_roots)
    def observe(value):
        _require(value == v2_request, "behavioral planner changed its complete request")
        original = policy_observer(request)
        original.require_current(request.roots)
        _require(_roots(catalog, checked_cache) == initial_roots and _pins() == pins,
                 "evidence owners or producers changed before planning")
        remaining()
        return replace(original, configuration_root=v2_roots.configuration_root)
    preview = preview_behavioral_repository_plan(catalog=catalog, checked_cache=checked_cache,
        semantic_manifest_cid=semantic_manifest_cid, owner=replace(owner,timeout_seconds=remaining()),
        request=v2_request, intent_document=intent_document, source_text=source_text,
        operation_catalog=operation_catalog, output=output, tool_policy=tool_policy, policy_observer=observe)
    candidate = finite.prepare_finite_repository_handoff(owner=replace(owner,timeout_seconds=remaining()),
        request=request, intent_document=intent_document, source_text=source_text,
        operation_catalog=operation_catalog, tool_policy=tool_policy, policy_observer=policy_observer,
        admission=admission, intent=intent, task_cid=task_cid, state=state, instruction_path=instruction_path)
    _require(candidate["status"] == "candidate_ready", "behavioral profile requires an actual checked residual candidate")
    first, second = preview["match"], candidate["preview"]["match"]
    _require(all(first[k] == second[k] for k in ("head", "query", "clause_results", "eligible_clause_ids", "residual_clause_ids", "finite_counterexamples"))
        and preview["selected_task_ids"] == candidate["preview"]["selected_task_ids"],
        "v2 planning and native candidate owner consumed different meaning")
    public_ref = public.publish_finite_public_context(candidate=candidate, admission=admission, instruction=source_text)
    current = local.verify_local_benchmark_admission(admission, initial=True)
    _require(current["receipt"] == declared["receipt"] and _roots(catalog,checked_cache) == initial_roots
             and _pins() == pins, "native evidence owner changed before signing")
    observe(v2_request)
    population = sorted(row.task_cid for row in current["graph"].tasks)
    _require(task_cid in population and len(population) == len(set(population)), "complete independent task population required")
    payload = dict(schema=SCHEMA, repository=str(owner.repository), task_cid=task_cid,
        manifest_cid=current["receipt"]["manifest_cid"], native_task_population=population,
        # Native prompt graphs contain finite confidence floats; retain their exact
        # canonical JSON as inert data and replay the native graph owner below.
        native_graph=json.dumps(admission['graph'],sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False),
        native_planning_receipt=admission['receipt'],legacy_signed_evidence=candidate['signed_evidence'],
        original_request=request.to_dict(), behavioral_request=v2_request.to_dict(),
        intent_document=json.dumps(intent_document.to_dict(),sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False),
        source_text=source_text, tool_policy=tool_policy,
        semantic_manifest_cid=semantic_manifest_cid, source_head=owner.expected_head.to_dict(),
        proof_snapshot=preview["repository_proof_snapshot"], match_semantics=_semantics(preview["behavioral_match"]),
        behavioral_match=preview["behavioral_match"], behavioral_initial=public._portable(preview["match"]["observation"]),
        legacy_handoff=dict(artifact=candidate["handoff_path"],sha256=candidate["handoff_sha256"]),
        public_context=public_ref, owner_roots=initial_roots, producers=pins, **FALSE)
    payload["artifact_cid"] = content_identity(payload)
    signed = local._signed(payload, current["manifest"])
    artifact, digest = finite._public_artifact(owner.repository, signed)
    remaining()
    result = dict(candidate, schema="repository-behavioral-handoff-preparation@1", behavioral_preview=preview,
        repository_admission_path=str(artifact), repository_admission_sha256=digest,
        public_context=public_ref, behavioral_fence_payload_cid=payload["artifact_cid"])
    result["result_cid"] = cid_for_structured({k:v for k,v in result.items() if k!='result_cid'})
    return result


def _load(*, artifact, expected_sha256, task_cid, owner_did, profile_id):
    path = Path(artifact).absolute()
    handle = _directory(path.parent)
    try:
        raw, info = _read(handle, path.name)
    finally:
        os.close(handle)
    _require(not info.st_mode & 0o222 and finite._sha(raw) == expected_sha256,
             "immutable owner-pinned behavioral fence required")
    envelope = json.loads(raw, object_pairs_hook=_unique)
    _require(type(envelope) is dict and set(envelope) == {"payload","binding"}, "closed signed behavioral fence required")
    value, binding = envelope["payload"], envelope["binding"]
    _require(type(binding) is dict and binding == dict(identity=owner_did,profile_id=profile_id,signature=binding.get("signature")),
             "behavioral fence launch owner differs")
    local.verify_did_key_signature(identity_did=owner_did,payload=value,signature=binding["signature"])
    _require(type(value) is dict and set(value) == FIELDS and value["schema"] == SCHEMA
        and value["task_cid"] == task_cid and value["producers"] == _pins()
        and value["artifact_cid"] == content_identity({k:v for k,v in value.items() if k!='artifact_cid'})
        and all(value[k] is False for k in FALSE), "behavioral fence identity or producer differs")
    root = Path(value["repository"])
    _require(path == root/'.runtime/repository-finite-handoffs'/(expected_sha256+'.json'),
             "behavioral fence is outside its signed repository")
    for location in (root/'.runtime',path.parent):
        _require(_entry(location,directory=True)["uid"] == root.stat().st_uid, "behavioral fence owner differs")
    snapshot = value["proof_snapshot"]
    _require(snapshot["schema"] == "repository-proof-planning-snapshot@2"
        and snapshot["snapshot_cid"] == cid_for_structured({k:v for k,v in snapshot.items() if k!='snapshot_cid'})
        and snapshot["source_head"] == value["source_head"]
        and snapshot["semantic_manifest_cid"] == value["semantic_manifest_cid"]
        and snapshot["model"] == {"enabled":False,"identity":"explicit-model-off@1"}
        and all(snapshot[k] is False for k in ("execution_authority","completion_authority","omission_authority")),
        "complete model-off v2 proof snapshot required")
    _require(type(value["native_task_population"]) is list and 0 < len(value["native_task_population"]) <= 128
        and value["native_task_population"] == sorted(set(value["native_task_population"]))
        and task_cid in value["native_task_population"], "full signed native task population differs")
    from ..prompt.prompt_workflow import PromptGoalGraph
    _require(type(value['native_graph']) is str,'native graph must retain canonical JSON bytes')
    graph_value=json.loads(value['native_graph'],object_pairs_hook=_unique)
    _require(json.dumps(graph_value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)==value['native_graph'],
        'native graph encoding differs')
    graph=PromptGoalGraph.from_dict(graph_value)
    _require(type(value['intent_document']) is str,'native Intent document must retain canonical JSON bytes')
    intent_value=json.loads(value['intent_document'],object_pairs_hook=_unique)
    _require(json.dumps(intent_value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)==value['intent_document'],
        'native Intent encoding differs')
    receipt=value['native_planning_receipt']
    _require(type(receipt) is dict and set(receipt)=={'payload','binding'} and receipt['binding']['identity']==owner_did
        and receipt['binding']['profile_id']==profile_id,'foreign native planning receipt')
    local.verify_did_key_signature(identity_did=owner_did,payload=receipt['payload'],signature=receipt['binding']['signature'])
    _require(receipt['payload']['graph_cid']==graph.content_id and receipt['payload']['manifest_cid']==value['manifest_cid']
        and sorted(row.task_cid for row in graph.tasks)==value['native_task_population'], 'signed task population was reduced or rebound')
    legacy=value['legacy_signed_evidence']
    _require(finite._sha(finite._wire(legacy))==value['legacy_handoff']['sha256']
        and legacy['binding']['identity']==owner_did and legacy['binding']['profile_id']==profile_id
        and legacy['payload']['task_cid']==task_cid and legacy['payload']['manifest_cid']==value['manifest_cid']
        and legacy['payload']['repository']==value['repository'],'native candidate custody belongs to another admission')
    local.verify_did_key_signature(identity_did=owner_did,payload=legacy['payload'],signature=legacy['binding']['signature'])
    return value


def _verify_snapshot(value, matched, catalog):
    """Replay archived fact provenance against fresh meaning and retained bodies."""
    from ..planning.behavioral_repository_plan import _proof_snapshot
    from ..planning.finite_integer_plan_preview import FiniteIntegerOperationCatalog, ReviewedFiniteIntegerOperation
    from ..planning.repository_plan_preview import RepositoryPlanPreviewOwner
    from ..planning.plan_revision_contracts import PlanCreateRequest
    original, _ = public._replay(value['behavioral_initial'])
    fresh = matched['fresh_match']
    _require(all(original[k] == fresh['observation'][k] for k in ('head','source_cid','source_sha256',
        'contract','domain_inputs','domain_cid','observations','trace_cid','compiled_cid','tool_policy_cid',
        'type_clause_satisfied','offset_clause_satisfied','runtime_observation_coverage_complete','kernel_checked_model_table')),
        'retained behavioral observation differs from fresh source outcomes')
    rebuilt = deepcopy(matched)
    oldmatch = rebuilt['fresh_match']
    query = oldmatch['query']
    facts = []
    mapping = oldmatch['typed_intent']['metadata']['requirement_predicate_ids']
    for row in oldmatch['current_facts']:
        fact = deepcopy(row)
        requirement = next(key for key,predicate in mapping.items() if predicate==row['predicate']['predicate_id'])
        fact_key = dict(schema='supervisor-finite-integer-fact-binding@1',requirement_id=requirement,
            predicate_id=row['predicate']['predicate_id'],head=original['head'],source_cid=original['source_cid'],
            domain_cid=query['domain_cid'],observation_cid=original['result_cid'],trace_cid=original['trace_cid'])
        fact['fact_id']='finite-observation:'+cid_for_structured(fact_key)
        fact['provenance_refs']=[query['query_cid'],cid_for_structured(original['head']),original['head']['snapshot_cid'],
            original['source_cid'],query['domain_cid'],original['trace_cid'],original['result_cid'],
            cid_for_structured(original['lean_certificate']),original['compiled_cid'],original['tool_policy_cid']]
        # The native fact's identity also binds its exact reconstructed fields.
        from ..planning.obligation_graph_compiler import ObservedFact
        fact.pop('content_id',None)
        fact.pop('cid',None)
        facts.append(ObservedFact.from_dict(fact).to_dict())
    oldmatch.update(observation=original,observation_cid=original['result_cid'],current_facts=facts)
    oldmatch['match_cid']=cid_for_structured({k:v for k,v in oldmatch.items() if k!='match_cid'})
    rebuilt['current_facts']=facts
    rebuilt['match_cid']=cid_for_structured({k:v for k,v in rebuilt.items() if k!='match_cid'})
    _require(rebuilt==value['behavioral_match'],'retained complete behavioral match does not reconstruct')
    snapshot=value['proof_snapshot']
    operations=FiniteIntegerOperationCatalog(tuple(ReviewedFiniteIntegerOperation(**v) for v in snapshot['operations']['operations']))
    _require(operations.to_dict()==snapshot['operations'],'operation catalog does not reconstruct')
    request=PlanCreateRequest.from_dict(value['behavioral_request'])
    original_request=PlanCreateRequest.from_dict(value['original_request'])
    owner=RepositoryPlanPreviewOwner(index=catalog.index,repository=Path(value['repository']),
        expected_head=CodebaseHead.from_dict(value['source_head']),timeout_seconds=90,memory_mb=1024)
    binding=repository_evidence_binding(owner=owner,semantic_manifest_cid=value['semantic_manifest_cid'],
        tool_policy=value['tool_policy'],operation_catalog=operations)
    _require(request==replace(original_request,roots=replace(original_request.roots,configuration_root=plan_revision_cid(binding)))
        and _proof_snapshot(rebuilt,request,operations,binding)==snapshot,'full planning snapshot or request roots differ')


@contextmanager
def _owners(roots):
    import duckdb
    _require(type(roots) is dict and set(roots) == {"source_database","artifacts","proof_database","discovery_limits","cache_max_records"},
             "closed native evidence owner locations required")
    def verify():
        for name in ("source_database","artifacts","proof_database"):
            entry = roots[name]
            _require(_entry(entry["path"],directory=name=='artifacts') == entry, "native evidence path or inode changed")
    verify()
    # Refuse missing storage before constructing any existing native owner.
    with duckdb.connect(roots['source_database']['path'],read_only=True) as cx:
        schemas = {row[0] for row in cx.execute('SELECT schema_name FROM information_schema.schemata').fetchall()}
        _require({'codebase_control','intent_codebase'} <= schemas, "existing source/discovery storage required")
    with duckdb.connect(roots['proof_database']['path'],read_only=True) as cx:
        tables = {row[0] for row in cx.execute('SHOW TABLES').fetchall()}
        _require({'proof_cache_entries','finite_checked_cache_records'} <= tables, "existing native proof storage required")
    with duckdb.connect(roots['source_database']['path'],config={'threads':1,'memory_limit':'64MB'}) as cx:
        store = DuckDBASTStore(connection=cx)
        cas = ImmutableCAS(roots['artifacts']['path'])
        index = RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store),artifacts=cas,catalog=CodebaseCatalog(store,cas))
        catalog = IntentCodebaseCatalog(index,limits=IntentCodebaseCatalogLimits(**roots['discovery_limits']))
        cache = FiniteCheckedCache(FormalVerificationCache(roots['proof_database']['path'],exact_path=True),cas,max_records=roots['cache_max_records'])
        _require(_roots(catalog,cache) == roots, "reopened native evidence owners differ")
        yield catalog,cache
        verify()


def verify_behavioral_repository_handoff(*, artifact, expected_sha256, task_cid, owner_did, profile_id,
        timeout_seconds=90, scheduler=None, parent_lease=None, cancel_event=None):
    """Fresh source/catalog/cache/matcher fence; no private signing key or Intent DB."""
    _require(type(timeout_seconds) in (int,float) and math.isfinite(timeout_seconds) and 0<timeout_seconds<=300,
        'bounded complete evidence replay deadline required')
    _require(cancel_event is None or callable(getattr(cancel_event,'is_set',None)), 'cooperative cancellation required')
    deadline=time.monotonic()+timeout_seconds
    def remaining():
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import LeaseCancelledError,LeaseTimeoutError
        if cancel_event is not None and cancel_event.is_set():raise LeaseCancelledError('behavioral replay cancelled')
        left=deadline-time.monotonic()
        if left<=0:raise LeaseTimeoutError('behavioral replay deadline expired')
        return left
    remaining()
    value = _load(artifact=artifact,expected_sha256=expected_sha256,task_cid=task_cid,owner_did=owner_did,profile_id=profile_id)
    with _owners(value['owner_roots']) as (catalog,cache), tempfile.TemporaryDirectory(prefix='behavioral-admission-') as temporary:
        matched = match_behavioral_intent(catalog=catalog,checked_cache=cache,repository=Path(value['repository']),
            expected_head=CodebaseHead.from_dict(value['source_head']),semantic_manifest_cid=value['semantic_manifest_cid'],
            intent_document=json.loads(value['intent_document'],object_pairs_hook=_unique),source_text=value['source_text'],output=Path(temporary)/'observation',
            tool_policy=value['tool_policy'],timeout_seconds=remaining(),scheduler=scheduler,parent_lease=parent_lease,cancel_event=cancel_event)
        _require(_semantics(matched) == value['match_semantics'], "current repository evidence no longer matches signed planning meaning")
        _verify_snapshot(value,matched,catalog)
        context = public.load_finite_public_context(artifact=value['public_context']['artifact'],
            expected_sha256=value['public_context']['sha256'],owner_did=owner_did,profile_id=profile_id,
            task_cid=task_cid,handoff_sha256=value['legacy_handoff']['sha256'])
        _require(context['source_head'] == value['source_head'] and context['original_instruction'] == value['source_text']
            and context['query'] == matched['fresh_match']['query'], "public candidate evidence has different source or intent")
        _require(_pins() == value['producers'], "behavioral producers changed during live replay")
        remaining()
    remaining()
    return dict(schema=SCHEMA,status='current_repository_evidence',artifact_cid=value['artifact_cid'],
        source_head=value['source_head'],native_task_population=value['native_task_population'],
        legacy_handoff=value['legacy_handoff'],public_context=value['public_context'],
        fresh_match_cid=matched['match_cid'],fresh_native_checkers=True,private_owner_keys_used=False,**FALSE)


__all__ = ['prepare_behavioral_repository_handoff','verify_behavioral_repository_handoff','SCHEMA']
