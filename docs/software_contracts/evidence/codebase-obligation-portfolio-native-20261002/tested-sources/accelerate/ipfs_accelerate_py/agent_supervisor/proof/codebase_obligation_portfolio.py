"""Execute a bounded typed AND/OR portfolio for captured integer source models.

This opt-in profile does not publish a proof head or decide task completion.
Canonical kernels reconstruct a mathematical integer model; TLC checks only
the explicitly bridged finite stuttering model. All reports retain that scope.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import threading

from ..runtime.repository_resource_bridge import RepositoryHostReservation, RepositoryPhaseDemand
from ipfs_datasets_py.duckdb_control.contracts import canonical_json_bytes
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
from ipfs_datasets_py.logic.software_contracts.codebase_family_execution import (
    execute_family, implementation_identity, validate_family_tools, MEMORY_MB, RESULT_SCHEMA,
)
from ipfs_datasets_py.logic.software_contracts.codebase_family_lowering import (
    CodebaseFamilyBundle, CodebaseFamilyError, BRIDGE_SCOPE, _require, _inputs,
)
from ipfs_datasets_py.logic.software_contracts.codebase_integer_profile import compile_integer_offset, IntegerOffsetContract
from ipfs_datasets_py.logic.software_contracts.codebase_obligation_graph import build_codebase_obligation_plans
from ipfs_datasets_py.logic.software_contracts.codebase_semantic_manifest import load_codebase_semantic_manifest
from ipfs_datasets_py.logic.software_contracts.codebase_scan_policy_live import verify_policy_current
from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.backends.portfolio import (
    VerificationPortfolio, PortfolioObligation, PropertyPortfolioPolicy, PortfolioAttemptSpec,
    PortfolioAttemptOutcome, PortfolioResourcePolicy, PortfolioRole, AttemptFamily,
)
from ipfs_datasets_py.logic.backends.results import ResultStatus, ResultAuthority
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds
from ipfs_datasets_py.logic.software_verification.properties import PropertyKind
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import LeaseCancelledError, LeaseTimeoutError

SCHEMA = 'codebase-obligation-portfolio@1'
PROFILE = 'captured-integer-offset-and-finite-bridge@1'
KERNELS = ('lean', 'rocq', 'isabelle')


def _identity(value):
    return cid_for_bytes(canonical_json_bytes(value))


def _producer():
    from ipfs_accelerate_py.agent_supervisor.runtime import repository_resource_bridge
    return {**implementation_identity(), __name__:cid_for_bytes(Path(__file__).read_bytes()),
        repository_resource_bridge.__name__:cid_for_bytes(Path(repository_resource_bridge.__file__).read_bytes())}


class _Combined:
    def __init__(self,*events):self.events=events
    def is_set(self):return any(e is not None and e.is_set() for e in self.events)


def _select_math(bundle, kernel, results, *, timeout_ms):
    """Canonical authority selection; raw SMT disagreement additionally quarantines."""
    chosen = [results[k] for k in ('z3','cvc5',kernel)]
    for backend,result in zip(('z3','cvc5',kernel),chosen):
        _require(result['schema']==RESULT_SCHEMA and result['backend']==backend
                 and result['bundle_cid']==bundle.cid and result['source_cid']==bundle.compiled.source_cid
                 and result['contract_cid']==bundle.compiled.contract.cid
                 and result['operation']==bundle.to_dict()['operation'], 'portfolio attempt belongs to another exact obligation')
    specs=tuple(PortfolioAttemptSpec(backend,backend,AttemptFamily.KERNEL if backend==kernel else AttemptFamily.SOLVER,
        PortfolioRole.RECONSTRUCTION if backend==kernel else PortfolioRole.CANDIDATE,
        result_authority=ResultAuthority.RECONSTRUCTION if backend==kernel else ResultAuthority.SATISFIABILITY,
        requires_candidate=False,authority_capability='exact_native_kernel' if backend==kernel else '')
        for backend in ('z3','cvc5',kernel))
    policy=PropertyPortfolioPolicy(PropertyKind.CONTRACT,specs,policy_id=PROFILE+':'+kernel,
        resource_policy=PortfolioResourcePolicy(bounds=ExecutionBounds(timeout_ms=timeout_ms,max_steps=2,
            max_memory_bytes=1536*1024**2,max_output_bytes=256*1024),max_parallel=2,max_attempts=3,
            cancel_on_counterexample=False),minimum_assurance=EvidenceAuthority.INDEPENDENTLY_CHECKABLE)
    owner=VerificationPortfolio({PropertyKind.CONTRACT:policy})
    obligation=PortfolioObligation(bundle.cid,PropertyKind.CONTRACT,bundle.to_dict()['operation'],
        required_assurance=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,required_authority=ResultAuthority.RECONSTRUCTION,
        assumption_ids=tuple('assumption:'+hashlib.sha256(a.encode()).hexdigest() for a in bundle.to_dict()['assumptions']),
        metadata=FrozenMap(dict(bundle_cid=bundle.cid,domain='mathematical_integer',runtime_proof=False)))
    plan=owner.plan(obligation)
    outcomes=[]
    for spec,result in zip(specs,chosen):
        raw=result['status'];is_kernel=spec.backend_id==kernel
        if raw=='proved':status=ResultStatus.RECONSTRUCTED if is_kernel else ResultStatus.UNSATISFIABLE
        elif raw=='refuted':status=ResultStatus.DISPROVED if is_kernel else ResultStatus.SATISFIABLE
        else:status={'timeout':ResultStatus.TIMEOUT,'unavailable':ResultStatus.UNAVAILABLE,'unsupported':ResultStatus.UNSUPPORTED,
                     'error':ResultStatus.ERROR}.get(raw,ResultStatus.UNKNOWN)
        outcomes.append(PortfolioAttemptOutcome(spec.attempt_id,spec.backend_id,status,spec.result_authority,spec.role,
            conclusive_counterexample=is_kernel and raw=='refuted',
            achieved_assurance=EvidenceAuthority.INDEPENDENTLY_CHECKABLE if is_kernel and raw in ('proved','refuted') else EvidenceAuthority.NONE,
            detail='Exact closed mathematical source model; native record '+_identity(result),
            witness=FrozenMap(dict(native_record_cid=_identity(result),bundle_cid=bundle.cid))))
    selection=owner.select(plan,outcomes)
    dispositions={r['status'] for r in chosen if r['status'] in ('proved','refuted')}
    return dict(plan=plan.to_dict(),selection=selection.to_dict(),
        status='quarantined' if len(dispositions)>1 else selection.verdict.value,
        disagreement=len(dispositions)>1,attempt_record_cids=[_identity(r) for r in chosen])


class _RunFlights:
    """Run-local bounded deduplication, never persistent verdict reuse."""
    def __init__(self,executor,run_binding,invoke):
        self.executor,self.binding,self.invoke=executor,run_binding,invoke
        self.entries={};self.requests=0;self.lock=threading.Lock()

    def submit(self,bundle,backend,bridge=False):
        key=_identity(dict(run=self.binding,bundle=bundle.to_dict(),backend=backend,bridge=bridge))
        with self.lock:
            self.requests+=1
            if key not in self.entries:
                _require(len(self.entries)<16,'bounded native flight count exceeded')
                self.entries[key]=self.executor.submit(self.invoke,bundle,backend,bridge)
            return self.entries[key]


def execute_codebase_obligation_portfolio(index,repository,*,expected_head,manifest_cid,paths,inputs,tools,
        parent,max_parallel=2,attempt_timeout_seconds=90,optional_cancel_event=None):
    """Fresh exact captured-model attempts plus mandatory final live validation.

    Optional cancellation applies only to redundant Rocq/Isabelle branches.
    Parent cancellation cancels the entire request; it never creates success.
    """
    _require(type(parent) is RepositoryHostReservation,'actual joined repository host reservation required')
    _require(type(expected_head) is CodebaseHead and parent.repository_id==expected_head.repository_id,
             'repository reservation and native source head must identify the same repository')
    _require(type(paths) in (tuple,list) and 1<=len(paths)<=2 and len(set(paths))==len(paths)
             and all(type(p) is str for p in paths),'one or two distinct selected source paths required')
    _require(type(max_parallel) is int and 1<=max_parallel<=2,'bounded concurrency at most two required')
    _require(type(attempt_timeout_seconds) is int and 1<=attempt_timeout_seconds<=120,'bounded exact integer attempt timeout required')
    inputs=tuple(_inputs(inputs))
    _require(optional_cancel_event is None or callable(getattr(optional_cancel_event,'is_set',None)), 'typed optional cancellation signal required')
    _require(parent.budget.memory_mb>=1536,'complete family profile requires 1536 MiB admitted parent capacity')
    with parent.phase(RepositoryPhaseDemand('validation',memory_mb=512)) as phase:
        tools=validate_family_tools(tools,checkpoint=parent.remaining)
        manifest=load_codebase_semantic_manifest(index,manifest_cid)
        _require(manifest['source_head']==expected_head.to_dict(),'semantic manifest binds another source head')
        verify_policy_current(index,repository,expected_head=expected_head,receipt_cid=manifest['policy_receipt_cid'],**phase.native_options())
    units={u['path']:u for u in manifest['units']}
    _require(all(p in units for p in paths),'selected path is outside the whole captured inventory')
    unsupported=[dict(path=p,status=units[p]['model_status'],reason=units[p]['unsupported_reason']) for p in paths
                 if units[p]['model_status']!='source_bound_model']
    producer=_producer()
    binding=dict(schema=SCHEMA,profile=PROFILE,source_head=expected_head.to_dict(),manifest_cid=manifest_cid,
        policy_receipt_cid=manifest['policy_receipt_cid'],selected_paths=list(paths),finite_inputs=list(inputs),
        producer=producer,tools=tools,maximum_parallel=max_parallel,attempt_timeout_seconds=attempt_timeout_seconds)
    report=dict(**binding,status='unsupported' if unsupported else 'unknown',unsupported=unsupported,
        source_runtime_semantics_verified=False,task_completion_authority=False,bridge_scope=BRIDGE_SCOPE,
        plans=None,units=[],final_source_validation=False,inventory_coverage=manifest['coverage'],
        single_flight=None)
    if unsupported:return report
    bundles=[]
    with parent.phase(RepositoryPhaseDemand('semantic_index',memory_mb=512)):
        for path in paths:
            row=units[path]
            compiled=compile_integer_offset(index.artifacts.get_bytes(row['source_cid']),
                IntegerOffsetContract.from_dict(row['declared_contract']),revision='snapshot:'+expected_head.snapshot_cid)
            bundles.append(CodebaseFamilyBundle(compiled,tuple(inputs)))
    report['plans']=build_codebase_obligation_plans(bundles)
    def invoke(bundle,backend,bridge):
        optional=backend in ('rocq','isabelle')
        signal=_Combined(parent.cancellation,optional_cancel_event if optional else None)
        try:
            if signal.is_set():raise LeaseCancelledError('optional or parent cancellation')
            with parent.phase(RepositoryPhaseDemand('proof',memory_mb=MEMORY_MB[backend])) as phase:
                options=phase.native_options();options.pop('memory_mb')
                options['timeout_seconds']=min(attempt_timeout_seconds,options['timeout_seconds'])
                options['cancel_event']=_Combined(options['cancel_event'],signal)
                return execute_family(bundle,tools,backend=backend,bridge=bridge,**options)
        except (LeaseCancelledError,LeaseTimeoutError) as error:
            return dict(schema=RESULT_SCHEMA,backend=backend,bundle_cid=bundle.cid,source_cid=bundle.compiled.source_cid,
                contract_cid=bundle.compiled.contract.cid,operation='finite_restriction_bridge' if bridge else bundle.to_dict()['operation'],
                status='cancelled' if isinstance(error,LeaseCancelledError) else 'timeout',detail=str(error),
                native_observations=[],tools=tools,producer=implementation_identity(),
                source_runtime_semantics_verified=False,mathematical_model_only=True)
    with ThreadPoolExecutor(max_workers=max_parallel,thread_name_prefix='codebase-proof') as pool:
        flights=_RunFlights(pool,binding,invoke)
        scheduled=[]
        for bundle in bundles:
            branches={kernel:{b:flights.submit(bundle,b) for b in ('z3','cvc5',kernel)} for kernel in KERNELS}
            scheduled.append((bundle,branches,flights.submit(bundle,'tlc')))
        for bundle,branches,finite in scheduled:
            native={backend:future.result() for branch in branches.values() for backend,future in branch.items()}
            selections={kernel:_select_math(bundle,kernel,native,timeout_ms=attempt_timeout_seconds*1000) for kernel in KERNELS}
            dispositions={r['status'] for r in native.values() if r['status'] in ('proved','refuted')}
            math_status=('quarantined' if len(dispositions)>1 else 'proved' if any(v['status']=='proved' for v in selections.values())
                         else 'refuted' if any(v['status']=='disproved' for v in selections.values()) else 'unknown')
            bridge=flights.submit(bundle,'lean',True).result() if math_status=='proved' else dict(status='blocked',reason='mathematical premise not established')
            finite_result=finite.result()
            status=('quarantined' if math_status=='quarantined' or (math_status=='proved' and finite_result['status']=='refuted')
                    else 'proved' if math_status==finite_result['status']==bridge['status']=='proved'
                    else 'refuted' if math_status=='refuted' or finite_result['status']=='refuted' else 'unknown')
            report['units'].append(dict(path=bundle.compiled.contract.path,bundle=bundle.to_dict(),bundle_cid=bundle.cid,
                native_attempts=native,mathematical_selections=selections,mathematical_status=math_status,
                finite_attempt=finite_result,bridge_attempt=bridge,status=status))
        report['single_flight']=dict(scope='this invocation only',requests=flights.requests,
            native_attempts=len(flights.entries),deduplicated=flights.requests-len(flights.entries),maximum_parallel=max_parallel)
    # This required phase is deliberately outside optional branch cancellation.
    try:
        with parent.phase(RepositoryPhaseDemand('validation',memory_mb=512)) as phase:
            verify_policy_current(index,repository,expected_head=expected_head,receipt_cid=manifest['policy_receipt_cid'],**phase.native_options())
            _require(producer==_producer(),'portfolio implementation changed during execution')
            _require(load_codebase_semantic_manifest(index,manifest_cid)==manifest,'semantic owner replay changed during execution')
        report['final_source_validation']=True
    except (LeaseCancelledError,LeaseTimeoutError):
        report['status']='cancelled' if parent.cancellation.is_set() else 'timeout'
    except Exception as error:
        report['status']='invalidated';report['source_validation_error']=type(error).__name__+': '+str(error)
        for row in report['units']:row['dependent_status']='invalidated_by_required_source_or_producer_validation'
    if report['final_source_validation']:
        statuses={r['status'] for r in report['units']}
        report['status']='quarantined' if 'quarantined' in statuses else 'refuted' if 'refuted' in statuses else 'proved' if statuses=={'proved'} else 'unknown'
    report['resource_receipt']=parent.receipt()
    _require(len(canonical_json_bytes(report))<=16*1024**2,'bounded portfolio report exceeded')
    return json.loads(canonical_json_bytes(report))


__all__=['execute_codebase_obligation_portfolio']
