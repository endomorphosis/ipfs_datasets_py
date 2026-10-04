"""Conclusions require complete model/version lifecycles and timely finalization.

Every executor is synthetic. The real bounded runner still materializes model
inputs, gathers declared output files, and cleans its private workspace.
"""
from dataclasses import replace
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.backends import process
from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.backends.tla import runners
from ipfs_datasets_py.logic.backends.tla.compiler import GeneratedTLAArtifacts, TLACompileBounds, TLASourceMapEntry
from ipfs_datasets_py.logic.ir_core.protocols import BackendRequest, ExecutionBounds, QueryKind

SUCCESS = 'Model checking completed. No error has been found.\nChecker reports no error\n'
TRACE = ('Error: Invariant Safety is violated.\n'
         'The following behavior constitutes a counter-example:\n'
         'State 1: <Initial predicate>\n/\\ n = 0\n'
         'State 2: <Next>\n/\\ n = 4\n')
HELP = ('TLC - provides model checking and simulation of TLA+ specifications - Version 2026.07.31\n'
        'SYNOPSIS\nDESCRIPTION\n')
UNSAFE = [
    pytest.param({'output_truncated': True}, id='truncated'),
    pytest.param({'resource_exhausted': True}, id='resource-exhausted'),
    pytest.param({'workspace_limit_exceeded': True}, id='workspace-limit'),
    pytest.param({'workspace_cleaned': False}, id='cleanup-incomplete'),
    pytest.param({'process_tree_terminated': True}, id='tree-terminated'),
    pytest.param({'error': 'cleanup failed after output'}, id='error-with-output'),
    pytest.param({'returncode': None}, id='no-return-code'),
    pytest.param({'returncode': -9}, id='signal-exit'),
    pytest.param({'timed_out': True}, id='timeout'),
    pytest.param({'cancelled': True}, id='cancelled'),
    pytest.param({'unavailable': True}, id='unavailable'),
]


def artifacts():
    return GeneratedTLAArtifacts(module_name='OutcomeCounter',
        model_text=("---- MODULE OutcomeCounter ----\nEXTENDS Integers\nVARIABLE n\n"
            "Init == n = 0\nNext == n < 4 /\\ n' = n + 1\n"
            "Spec == Init /\\ [][Next]_n\nSafety == n \\in 0..3\n====\n"),
        tlc_config_text='SPECIFICATION Spec\nINVARIANT Safety\nCHECK_DEADLOCK FALSE\n',
        apalache_config_text='INIT Init\nNEXT Next\nINVARIANT Safety\n',
        source_map=(TLASourceMapEntry('state:n', 'state_variable', 'n', 'variable'),),
        losses=(), bounds=TLACompileBounds(max_steps=4), source_document_id='test:outcome-integrity',
        source_kind='state_transition', safety_properties=('Safety',), liveness_properties=(),
        fairness_limitations=('Only the declared finite bounds were explored.',))


def request(timeout_ms=1000, max_output_bytes=1024*1024, **payload):
    return BackendRequest(request_id='request:tla:outcome', claim_id='claim:counter',
        declaration_id='declaration:counter', claim_digest='1'*64, obligation_id='obligation:counter',
        obligation_digest='2'*64, assumption_ids=('assumption:finite-counter',),
        logic_family='state_transition', query_kind=QueryKind.SATISFIABILITY,
        bounds=ExecutionBounds(timeout_ms=timeout_ms,max_memory_bytes=128*1024**2,max_steps=4,
                               max_output_bytes=max_output_bytes),
        payload=payload)


class ObservedRunner(process.BoundedToolRunner):
    def __init__(self, directory, *, backend_type, verdict, mutate_phase=None, changes=None,
                 executor_action=None, result_action=None, output_file=False):
        self.invocations=[]
        self.run_calls=[]
        self.workspaces=[]
        self.thread_workspaces={}
        self.native_results=[]
        self.backend_type=backend_type
        self.verdict=verdict
        self.mutate_phase=mutate_phase
        self.changes=changes or {}
        self.executor_action=executor_action
        self.result_action=result_action
        self.output_file=output_file
        super().__init__(executor=self.execute_fixture,workspace_root=directory)

    @staticmethod
    def phase(argv):
        return 'version' if argv[-1] in ('-help','version') else 'model'

    def execute_fixture(self, invocation, cancellation):
        phase=self.phase(invocation.argv)
        self.invocations.append((phase,invocation,cancellation))
        self.workspaces.append(invocation.cwd)
        self.thread_workspaces[threading.get_ident()]=invocation.cwd
        assert invocation.cwd.is_dir()
        if self.executor_action:
            self.executor_action(phase,invocation,cancellation)
        if phase=='version':
            return process.RawProcessResult(returncode=1 if self.backend_type is runners.TLCBackend else 0,
                stdout=HELP if self.backend_type is runners.TLCBackend else '0.58.3')
        if self.output_file:
            (invocation.cwd/'counterexample.tla').write_text(TRACE)
        return process.RawProcessResult(returncode=12 if self.verdict=='counterexample' else 0,
            stdout=TRACE if self.verdict=='counterexample' else SUCCESS)

    def run(self, value, **kwargs):
        phase=self.phase(value.argv)
        self.run_calls.append((phase,value,kwargs.get('cancellation')))
        result=super().run(value,**kwargs)
        workspace=self.thread_workspaces.pop(threading.get_ident(),None)
        assert workspace is None or not workspace.exists()
        if phase==self.mutate_phase:
            result=replace(result,**self.changes)
        if self.result_action:
            result=self.result_action(phase,result)
        self.native_results.append((phase,result))
        return result


@pytest.fixture
def make_backend(tmp_path):
    owners=[]
    def make(backend_type=runners.TLCBackend,verdict='pass',**kwargs):
        owner=ObservedRunner(tmp_path/('runs-'+str(len(owners))),backend_type=backend_type,
            verdict=verdict,**kwargs)
        selected=backend_type(runner=owner,executable='/fixture/checker',jvm_probe=lambda:True,lazy_install=False)
        owners.append(owner)
        return selected,owner
    yield make
    for owner in owners:
        assert all(not path.exists() for path in owner.workspaces)


def assert_inconclusive(outcome):
    assert outcome.result.is_conclusive is False
    assert outcome.result.status not in {ResultStatus.SATISFIED,ResultStatus.VIOLATED}
    assert outcome.receipt.status not in {runners.ModelCheckOutcomeStatus.PASSED,
                                          runners.ModelCheckOutcomeStatus.COUNTEREXAMPLE}
    assert outcome.receipt.counterexample is None
    assert 'counterexample' not in outcome.result.witness.to_dict()
    assert outcome.result.witness.to_dict()['receipt_id']==outcome.receipt.receipt_id
    assert outcome.result.authority is ResultAuthority.MODEL_CHECK
    assert outcome.receipt.bounded and not outcome.receipt.unbounded_proof


@pytest.mark.parametrize('backend_type',[runners.TLCBackend,runners.ApalacheBackend])
@pytest.mark.parametrize('verdict',['pass','counterexample'])
def test_clean_complete_model_and_version_preserve_conclusions_and_token_identity(make_backend,backend_type,verdict):
    token=threading.Event()
    backend,owner=make_backend(backend_type,verdict)
    outcome=backend.check(artifacts(),request=request(),cancellation=token)
    assert outcome.result.is_conclusive
    assert outcome.result.status is (ResultStatus.SATISFIED if verdict=='pass' else ResultStatus.VIOLATED)
    assert [row[0] for row in owner.invocations]==['model','version']
    assert all(row[2] is token for row in owner.invocations)
    assert outcome.receipt.returncode==(0 if verdict=='pass' else 12)
    if verdict=='counterexample':
        assert len(outcome.receipt.counterexample.states)==2
        assert outcome.receipt.counterexample.replayed
        assert any('replayed mapped symbols: n' in note for note in outcome.receipt.counterexample.replay_notes)
        assert 'counterexample' in outcome.result.witness.to_dict()
    assert ('Version' in outcome.receipt.tool_version) if backend_type is runners.TLCBackend else outcome.receipt.tool_version=='0.58.3'


@pytest.mark.parametrize('backend_type',[runners.TLCBackend,runners.ApalacheBackend])
@pytest.mark.parametrize('verdict',['pass','counterexample'])
@pytest.mark.parametrize('changes',UNSAFE)
def test_incomplete_model_never_publishes_either_conclusion_or_starts_version(make_backend,backend_type,verdict,changes):
    backend,owner=make_backend(backend_type,verdict,mutate_phase='model',changes=changes,output_file=True)
    outcome=backend.check(artifacts(),request=request())
    assert_inconclusive(outcome)
    assert [row[0] for row in owner.run_calls]==['model']
    assert outcome.receipt.tool_version in ('','unavailable')


@pytest.mark.parametrize('backend_type',[runners.TLCBackend,runners.ApalacheBackend])
@pytest.mark.parametrize('verdict',['pass','counterexample'])
@pytest.mark.parametrize('changes',UNSAFE)
def test_incomplete_version_revokes_already_observed_model_conclusion(make_backend,backend_type,verdict,changes):
    backend,owner=make_backend(backend_type,verdict,mutate_phase='version',changes=changes,output_file=True)
    outcome=backend.check(artifacts(),request=request())
    assert_inconclusive(outcome)
    assert [row[0] for row in owner.run_calls]==['model','version']
    assert outcome.receipt.tool_version in ('','unavailable') or outcome.receipt.tool_version.startswith('unavailable:')


@pytest.mark.parametrize('backend_type',[runners.TLCBackend,runners.ApalacheBackend])
@pytest.mark.parametrize('verdict',['pass','counterexample'])
def test_clean_unexpected_version_exit_is_unavailable_metadata_not_a_lost_model(make_backend,backend_type,verdict):
    backend,owner=make_backend(backend_type,verdict,mutate_phase='version',changes={'returncode':7})
    outcome=backend.check(artifacts(),request=request())
    assert outcome.result.is_conclusive
    assert outcome.receipt.tool_version.startswith('unavailable')
    assert outcome.result.status is (ResultStatus.SATISFIED if verdict=='pass' else ResultStatus.VIOLATED)


@pytest.fixture
def clock(monkeypatch):
    now=[100.0]
    monkeypatch.setattr(runners,'time',SimpleNamespace(monotonic=lambda:now[0]))
    return now


def stop_action(stop,clock,event):
    if stop=='deadline':
        clock[0]+=1.1
    else:
        event.set()


@pytest.mark.parametrize('stop',['deadline','cancel'])
@pytest.mark.parametrize('phase',['supplemental','parse','replay','receipt','result','outcome'])
def test_finalization_stop_clears_counterexample_from_receipt_and_witness(make_backend,clock,monkeypatch,phase,stop):
    event=threading.Event();backend,owner=make_backend(verdict='counterexample',output_file=True)
    fired=[]
    def changed():
        if not fired:
            fired.append(True);stop_action(stop,clock,event)
    if phase in ('supplemental','parse','replay'):
        container,name=(runners.TLAModelCheckerBackend,'_counterexample_from_outputs') if phase=='supplemental' else (
            runners,'parse_counterexample_trace' if phase=='parse' else 'replay_counterexample')
        original=getattr(container,name)
        def late(*args,**kwargs):
            value=original(*args,**kwargs);changed();return value
        monkeypatch.setattr(container,name,staticmethod(late) if phase=='supplemental' else late)
    elif phase in ('receipt','outcome'):
        selected=runners.ModelCheckReceipt if phase=='receipt' else runners.ModelCheckOutcome
        original=selected.__post_init__
        def late(self):
            original(self)
            if ((self.status is runners.ModelCheckOutcomeStatus.COUNTEREXAMPLE) if phase=='receipt' else self.result.is_conclusive):
                changed()
        monkeypatch.setattr(selected,'__post_init__',late)
    else:
        original=backend._result_from_receipt
        def late(*args,**kwargs):
            value=original(*args,**kwargs)
            if value.is_conclusive:changed()
            return value
        monkeypatch.setattr(backend,'_result_from_receipt',late)
    outcome=backend.check(artifacts(),request=request(),cancellation=event)
    assert fired and len(owner.invocations)==2
    assert_inconclusive(outcome)
    assert outcome.result.status is (ResultStatus.TIMEOUT if stop=='deadline' else ResultStatus.ERROR)


@pytest.mark.parametrize('stop',['deadline','cancel'])
@pytest.mark.parametrize('phase',['receipt','result','outcome'])
def test_finalization_stop_also_withholds_positive_model_result(make_backend,clock,monkeypatch,phase,stop):
    event=threading.Event();backend,owner=make_backend();fired=[]
    def changed():
        if not fired:fired.append(True);stop_action(stop,clock,event)
    if phase=='result':
        original=backend._result_from_receipt
        def late(*args,**kwargs):
            value=original(*args,**kwargs)
            if value.is_conclusive:changed()
            return value
        monkeypatch.setattr(backend,'_result_from_receipt',late)
    else:
        selected=runners.ModelCheckReceipt if phase=='receipt' else runners.ModelCheckOutcome
        original=selected.__post_init__
        def late(self):
            original(self)
            if ((self.status is runners.ModelCheckOutcomeStatus.PASSED) if phase=='receipt' else self.result.is_conclusive):changed()
        monkeypatch.setattr(selected,'__post_init__',late)
    outcome=backend.check(artifacts(),request=request(),cancellation=event)
    assert fired
    assert_inconclusive(outcome)


@pytest.mark.parametrize('stop',['deadline','cancel'])
@pytest.mark.parametrize('phase',['model','version'])
def test_signal_and_deadline_rechecked_after_request_construction_before_runner(make_backend,clock,monkeypatch,phase,stop):
    event=threading.Event();backend,owner=make_backend();original=process.ToolRunRequest.__post_init__;fired=[]
    def constructed(self):
        original(self)
        if ObservedRunner.phase(self.argv)==phase and not fired:
            fired.append(True);stop_action(stop,clock,event)
    monkeypatch.setattr(process.ToolRunRequest,'__post_init__',constructed)
    outcome=backend.check(artifacts(),request=request(),cancellation=event)
    assert fired
    assert [row[0] for row in owner.run_calls]==([] if phase=='model' else ['model'])
    assert_inconclusive(outcome)


def test_flagged_version_cancellation_remains_sticky_after_caller_clears_event(make_backend):
    event=threading.Event()
    def completed(phase,value):
        if phase=='version':
            event.set();event.clear()
            return replace(value,cancelled=True)
        return value
    backend,owner=make_backend(verdict='counterexample',result_action=completed)
    outcome=backend.check(artifacts(),request=request(),cancellation=event)
    assert not event.is_set()
    assert_inconclusive(outcome)


def test_reusing_backend_after_interrupted_call_does_not_keep_stop_state(make_backend):
    backend,owner=make_backend(verdict='counterexample',mutate_phase='version',changes={'timed_out':True})
    assert_inconclusive(backend.check(artifacts(),request=request()))
    owner.mutate_phase=None
    outcome=backend.check(artifacts(),request=request())
    assert outcome.result.status is ResultStatus.VIOLATED
    assert len(outcome.receipt.counterexample.states)==2


def test_concurrent_checks_on_same_backend_isolate_local_stop_state(make_backend):
    rendezvous=threading.Barrier(2)
    def completed(phase,value):
        if phase=='version':
            rendezvous.wait(timeout=3)
            if threading.current_thread().name=='interrupted':
                return replace(value,resource_exhausted=True)
        return value
    backend,owner=make_backend(verdict='counterexample',result_action=completed)
    outcomes={};errors=[]
    def call():
        try:outcomes[threading.current_thread().name]=backend.check(artifacts(),request=request(timeout_ms=5000))
        except BaseException as error:errors.append(error)
    threads=[threading.Thread(target=call,name=name) for name in ('healthy','interrupted')]
    for thread in threads:thread.start()
    for thread in threads:thread.join(5)
    assert all(not thread.is_alive() for thread in threads) and not errors
    assert_inconclusive(outcomes['interrupted'])
    assert outcomes['healthy'].result.status is ResultStatus.VIOLATED
    assert outcomes['healthy'].receipt.counterexample is not None


def test_run_payload_dispatch_and_facade_keep_incomplete_results_nonconclusive(make_backend):
    backend,owner=make_backend(verdict='counterexample',mutate_phase='model',changes={'workspace_cleaned':False})
    selected=artifacts()
    payload={'artifacts':selected.to_dict()}
    outcome=backend.run(request(**payload))
    assert_inconclusive(outcome)
    facade=runners.TLABackend(tlc=backend,apalache=backend)
    assert_inconclusive(facade.check(selected))
    assert [row[0] for row in owner.run_calls]==['model','model']


@pytest.mark.parametrize('backend_type',[runners.TLCBackend,runners.ApalacheBackend])
@pytest.mark.parametrize('verdict',['pass','counterexample'])
@pytest.mark.parametrize('phase',['model','version'])
def test_combined_utf8_output_bound_rejects_two_individually_valid_streams(make_backend,backend_type,verdict,phase):
    cap=1024
    observed=[]
    def oversized(which,value):
        if which==phase:
            value=replace(value,stdout=value.stdout+'x'*450,stderr='é'*300)
            assert len(value.stdout.encode())<cap and len(value.stderr.encode())<cap
            assert len(value.stdout.encode())+len(value.stderr.encode())>cap
            assert not value.output_truncated
            observed.append(value)
        return value
    backend,owner=make_backend(backend_type,verdict,result_action=oversized)
    outcome=backend.check(artifacts(),request=request(max_output_bytes=cap))
    assert observed
    assert_inconclusive(outcome)
    assert outcome.receipt.status is runners.ModelCheckOutcomeStatus.UNKNOWN
    assert [row[0] for row in owner.run_calls]==(['model'] if phase=='model' else ['model','version'])


def test_version_uses_its_64k_combined_cap_even_if_model_budget_is_larger(make_backend):
    def oversized(phase,value):
        if phase=='version':
            return replace(value,stdout=HELP+'x'*35000,stderr='é'*20000)
        return value
    backend,owner=make_backend(result_action=oversized)
    outcome=backend.check(artifacts(),request=request(max_output_bytes=1024*1024))
    assert_inconclusive(outcome)
    assert outcome.receipt.status is runners.ModelCheckOutcomeStatus.UNKNOWN
    assert owner.run_calls[1][1].limits.max_output_bytes==65536


def test_version_local_deadline_revokes_model_even_when_whole_request_has_time(make_backend,clock):
    def late(phase,invocation,cancellation):
        if phase=='version':clock[0]+=3.1
    backend,owner=make_backend(verdict='counterexample',executor_action=late)
    outcome=backend.check(artifacts(),request=request(timeout_ms=10000))
    assert_inconclusive(outcome)
    assert outcome.result.status is ResultStatus.TIMEOUT
    assert clock[0]<110
    assert owner.run_calls[1][1].limits.timeout_seconds==3


def test_failure_during_version_runner_cannot_leave_model_conclusive(make_backend,monkeypatch):
    backend,owner=make_backend(verdict='counterexample')
    original=owner.run
    def failed(value,**kwargs):
        if ObservedRunner.phase(value.argv)=='version':raise OSError('version workspace failure')
        return original(value,**kwargs)
    monkeypatch.setattr(owner,'run',failed)
    outcome=backend.check(artifacts(),request=request())
    assert_inconclusive(outcome)
    assert outcome.result.status is ResultStatus.ERROR
