"""E's satisfiable exit is candidate evidence only after a clean lifecycle.

Native execution is forbidden. Default adapter paths use a private scheduler
and synthetic executor; crafted records exercise independent failure flags.
"""
from dataclasses import replace
import subprocess
import sys
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.backends import process, registry, resource_admission as admission
from ipfs_datasets_py.logic.backends.atp import adapters, execution_v2 as v2
from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.ir_core.protocols import BackendRequest, ExecutionBounds, QueryKind
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources


MIB = 1024**2
SOURCE = 'fof(ax1, axiom, ~p).\nfof(goal, conjecture, p).'
MODEL_STATUSES = ('Satisfiable', 'CounterSatisfiable')
QUERY_KINDS = (QueryKind.THEOREM_PROOF, QueryKind.SATISFIABILITY)


def request(kind=QueryKind.THEOREM_PROOF):
    return BackendRequest(request_id='request:e:exit', claim_id='claim:e:exit',
        declaration_id='declaration:e:exit', claim_digest='1'*64,
        obligation_id='obligation:e:exit', obligation_digest='2'*64,
        assumption_ids=('assumption:fixture',), logic_family='fol', query_kind=kind,
        requested_backend_id='eprover',
        bounds=ExecutionBounds(timeout_ms=2000, max_memory_bytes=64*MIB,
                               max_output_bytes=8192, max_steps=100),
        payload={'encoding': 'tptp', 'source': SOURCE})


def output(status):
    return f'% SZS status {status} for problem\n% fixture model output\n'


def lifecycle(**changes):
    return process.ToolRunResult(**{
        'interface_version': process.BOUNDED_TOOL_RUNNER_VERSION,
        'runtime': process.ToolRuntime.NATIVE, 'command': ('eprover', '--proof-object', 'problem.p'),
        'returncode': 1, 'stdout': output('CounterSatisfiable'), 'stderr': '',
        'elapsed_seconds': .01, 'output_files': {}, 'termination_reason': 'completed',
        **changes})


class FixedRunner(process.BoundedToolRunner):
    def __init__(self, result):
        super().__init__(executor=lambda *a: pytest.fail('fixed lifecycle called an executor'))
        self.result = result
        self.requests = []

    def run(self, tool_request, *, cancellation=None):
        self.requests.append(tool_request)
        return self.result


def forbidden(*args, **kwargs):
    pytest.fail('rejected ATP output reached an evidence callback')


@pytest.fixture(autouse=True)
def no_native_or_shared_pool(monkeypatch):
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(process.SubprocessExecutor, 'execute', forbidden)
    monkeypatch.setattr(admission, 'get_global_resource_scheduler', forbidden)


@pytest.fixture
def parse_calls(monkeypatch):
    calls = []
    parse = adapters.parse_szs_status
    def observed(text):
        calls.append(text)
        return parse(text)
    monkeypatch.setattr(adapters, 'parse_szs_status', observed)
    return calls


@pytest.fixture
def host(tmp_path, monkeypatch):
    resources = ProofHostResources(8, 8192, 8192, pid_task_limit=8192, available_pid_tasks=8192)
    owner = schedulers.GlobalResourceScheduler(schedulers.ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path/'private-e-pool.json', proof_resource_sampler=lambda: resources,
        total_cpu_slots=2, total_memory_mb=256, total_child_process_slots=2,
        proof_memory_headroom_mb=64, lane_reservations={}, auto_renew_leases=False))
    lookups, calls, workspaces = [], [], []
    raw = [process.RawProcessResult(returncode=1, stdout=output('CounterSatisfiable'))]
    def resolve():
        lookups.append(True)
        return owner
    monkeypatch.setattr(admission, 'get_global_resource_scheduler', resolve)
    monkeypatch.setattr(process.shutil, 'which', lambda *a, **k: sys.executable)
    def execute(self, invocation, cancellation=None):
        snapshot = owner.snapshot()
        assert snapshot['active_lease_count'] == snapshot['active_root_lease_count'] == 1
        assert snapshot['allocated'] == {'cpu_slots': 1, 'memory_mb': 64}
        assert snapshot['allocated_child_process_slots'] == 1
        assert cancellation is not None and not cancellation.is_set()
        assert (invocation.cwd/'problem.p').read_text() == SOURCE
        calls.append(invocation)
        workspaces.append(invocation.cwd)
        return raw[0]
    monkeypatch.setattr(process.SubprocessExecutor, 'execute', execute)
    yield SimpleNamespace(owner=owner, calls=calls, lookups=lookups, raw=raw)
    snapshot = owner.snapshot()
    assert snapshot['active_lease_count'] == snapshot['waiting_request_count'] == 0
    assert all(not workspace.exists() for workspace in workspaces)


@pytest.mark.parametrize('status', MODEL_STATUSES)
@pytest.mark.parametrize('kind', QUERY_KINDS)
def test_clean_e_exit_one_default_is_admitted_unvalidated_candidate(host, status, kind, parse_calls):
    host.raw[0] = process.RawProcessResult(returncode=1, stdout=output(status))
    req = request(kind)
    before, digest = req.to_dict(), req.digest
    outcome = adapters.EProverBackend().run(req)
    assert outcome.result.status is ResultStatus.CANDIDATE
    assert outcome.result.authority is ResultAuthority.CANDIDATE
    assert outcome.result.witness['candidate_kind'] == 'unvalidated_atp_model'
    assert outcome.proof_object is outcome.countermodel is None
    assert outcome.result.metadata['szs_status'] == status
    assert outcome.result.metadata['process']['returncode'] == 1
    assert outcome.result.metadata['process']['workspace_cleaned']
    assert outcome.source_binding.request_digest == req.digest
    assert outcome.result.bounds == req.bounds
    assert req.to_dict() == before and req.digest == digest
    assert parse_calls == [output(status)]
    assert len(host.calls) == len(host.lookups) == 1


@pytest.mark.parametrize('status', MODEL_STATUSES)
def test_model_parser_runs_once_with_original_exit_and_unverified_model(status, parse_calls):
    raw = lifecycle(stdout=output(status))
    runner = FixedRunner(raw)
    calls = []
    def model(binding, received, parsed):
        calls.append((binding, received, parsed))
        assert received is raw and received.returncode == 1
        return adapters.ATPCountermodel(request_digest=binding.request_digest,
            source_digest=binding.source_digest, model_format='fixture-model',
            model={'p': False}, validated=False)
    outcome = adapters.EProverBackend(runner=runner, proof_reconstructor=forbidden,
        countermodel_parser=model).run(request())
    assert outcome.result.status is ResultStatus.CANDIDATE
    assert outcome.countermodel is not None and not outcome.countermodel.validated
    assert outcome.proof_object is None
    assert len(calls) == len(runner.requests) == 1 and parse_calls == [output(status)]


BAD_OUTPUT = [(output(token), '') for token in (
    'Theorem', 'Unsatisfiable', 'ContradictoryAxioms', 'Unknown', 'GaveUp', 'Timeout', 'ResourceOut', 'Bogus')]
BAD_OUTPUT += [('', ''), ('Theorem proved. SZS status Satisfiable', ''),
    (output('Satisfiable')+output('CounterSatisfiable'), ''),
    (output('Satisfiable'), output('Theorem'))]


@pytest.mark.parametrize('stdout,stderr', BAD_OUTPUT)
def test_exit_one_requires_one_allowed_szs_status_and_never_calls_evidence_hooks(stdout, stderr, parse_calls):
    runner = FixedRunner(lifecycle(stdout=stdout, stderr=stderr))
    outcome = adapters.EProverBackend(runner=runner, proof_reconstructor=forbidden,
        countermodel_parser=forbidden).run(request())
    assert outcome.result.status is ResultStatus.ERROR
    assert outcome.proof_object is outcome.countermodel is None
    assert outcome.result.reason
    assert outcome.result.metadata['process']['returncode'] == 1
    assert len(parse_calls) == 1 and len(runner.requests) == 1


def test_identical_repeated_status_remains_unambiguous(parse_calls):
    text = output('Satisfiable')+output('Satisfiable')
    result = adapters.EProverBackend(runner=FixedRunner(lifecycle(stdout=text))).run(request())
    assert result.result.status is ResultStatus.CANDIDATE
    assert parse_calls == [text]


UNSAFE = [({'unavailable': True}, ResultStatus.UNAVAILABLE),
    ({'timed_out': True}, ResultStatus.TIMEOUT),
    ({'cancelled': True}, ResultStatus.ERROR),
    ({'resource_exhausted': True}, ResultStatus.ERROR),
    ({'output_truncated': True}, ResultStatus.ERROR),
    ({'workspace_limit_exceeded': True}, ResultStatus.ERROR),
    ({'error': 'fixture cleanup failed'}, ResultStatus.ERROR),
    ({'workspace_cleaned': False}, ResultStatus.ERROR),
    ({'process_tree_terminated': True}, ResultStatus.ERROR)]


@pytest.mark.parametrize('changes,status', UNSAFE)
def test_failure_gates_run_before_the_e_exit_exception_or_any_parser(monkeypatch, changes, status):
    monkeypatch.setattr(adapters, 'parse_szs_status', forbidden)
    raw = lifecycle(**changes)
    result = adapters.EProverBackend(runner=FixedRunner(raw), proof_reconstructor=forbidden,
        countermodel_parser=forbidden).run(request())
    assert result.result.status is status and result.proof_object is result.countermodel is None
    metadata = result.result.metadata['process']
    assert metadata['returncode'] == 1
    for name, value in changes.items():
        assert metadata[name] == value


@pytest.mark.parametrize('overflow', [False, True])
def test_combined_utf8_output_bound_precedes_exit_acceptance(monkeypatch, parse_calls, overflow):
    stdout = output('Satisfiable')+'é'*1800
    remaining = 8192-len(stdout.encode())
    stderr = 'é'*(remaining//2)+' '*(remaining%2)+('é' if overflow else '')
    assert len(stdout.encode()) < 8192 and len(stderr.encode()) < 8192
    assert len(stdout)+len(stderr) < 8192
    if overflow:
        monkeypatch.setattr(adapters, 'parse_szs_status', forbidden)
    result = adapters.EProverBackend(runner=FixedRunner(lifecycle(stdout=stdout, stderr=stderr))).run(request())
    assert result.result.status is (ResultStatus.ERROR if overflow else ResultStatus.CANDIDATE)
    assert result.result.metadata['process']['returncode'] == 1
    assert result.result.usage.output_bytes == 8192+(2 if overflow else 0)
    assert len(parse_calls) == (0 if overflow else 1)


@pytest.mark.parametrize('provider,code', [('vampire', 1), ('e', 2), ('e', -9), ('e', None),
                                         ('e', True), ('e', 1.0)])
def test_unreviewed_exit_codes_and_other_solver_do_not_parse_sat_output(monkeypatch, provider, code):
    monkeypatch.setattr(adapters, 'parse_szs_status', forbidden)
    req = request()
    selected = adapters.EProverBackend
    if provider == 'vampire':
        req = replace(req, requested_backend_id='vampire')
        selected = adapters.VampireBackend
    outcome = selected(runner=FixedRunner(lifecycle(returncode=code)),
        proof_reconstructor=forbidden, countermodel_parser=forbidden).run(req)
    assert outcome.result.status is ResultStatus.ERROR
    assert outcome.proof_object is outcome.countermodel is None
    assert outcome.result.metadata['process']['returncode'] == code


@pytest.mark.parametrize('code', [0, 1])
@pytest.mark.parametrize('kind', QUERY_KINDS)
def test_explicit_model_validation_retains_its_independent_authority_contract(code, kind):
    def model(binding, raw, status):
        assert raw.returncode == code and status is adapters.SZSStatus.COUNTER_SATISFIABLE
        return adapters.ATPCountermodel(request_digest=binding.request_digest,
            source_digest=binding.source_digest, model_format='fixture-validated-model',
            model={'p': False}, validated=True, validator_id='validator:fixture')
    outcome = adapters.EProverBackend(runner=FixedRunner(lifecycle(returncode=code)),
        proof_reconstructor=forbidden, countermodel_parser=model).run(request(kind))
    assert outcome.result.status is (ResultStatus.DISPROVED if kind is QueryKind.THEOREM_PROOF else ResultStatus.SATISFIABLE)
    assert outcome.countermodel is not None and outcome.countermodel.validated
    assert outcome.proof_object is None


@pytest.mark.parametrize('wrong', ['request', 'source'])
def test_exit_one_does_not_accept_a_countermodel_for_another_binding(wrong):
    def model(binding, raw, status):
        return adapters.ATPCountermodel(
            request_digest='3'*64 if wrong == 'request' else binding.request_digest,
            source_digest='4'*64 if wrong == 'source' else binding.source_digest,
            model_format='fixture-model', model={'p': False})
    with pytest.raises(adapters.ATPAdapterError, match='another source'):
        adapters.EProverBackend(runner=FixedRunner(lifecycle()), countermodel_parser=model).run(request())


@pytest.mark.parametrize('status', MODEL_STATUSES)
def test_default_registry_keeps_e_model_candidate_descriptive_and_raw_exit_intact(host, status):
    host.raw[0] = process.RawProcessResult(returncode=1, stdout=output(status))
    req = request()
    attempt, result = registry.default_backend_registry().run(req, backend_id='e')
    assert attempt.status.value == 'succeeded' and result.status.value == 'unknown'
    assert not result.is_theorem_proof
    assert result.payload['result_status'] == result.payload['result_authority'] == 'candidate'
    assert result.payload['result']['metadata']['process']['returncode'] == 1
    assert result.payload['result']['metadata']['szs_status'] == status
    assert result.request_digest == attempt.request_digest == req.digest
    assert result.attempt_digest == attempt.digest and result.bounds == req.bounds
    assert len(host.calls) == len(host.lookups) == 1


@pytest.mark.parametrize('status', MODEL_STATUSES)
@pytest.mark.parametrize('route', ['default', 'fixed'])
def test_v2_keeps_model_unvalidated_without_proof_replay_or_reconstruction(host, status, route):
    host.raw[0] = process.RawProcessResult(returncode=1, stdout=output(status))
    runner = FixedRunner(lifecycle(stdout=output(status))) if route == 'fixed' else None
    req = v2.AtpExecutionRequestV2(request_id='request:e:v2:exit', provider='eprover',
        source=SOURCE, mode='pinned_solver', bounds=request().bounds)
    before = req.to_dict()
    result = v2.AtpExecutionEngineV2(eprover_runner=runner).execute(req)
    evidence = result.evidence
    assert evidence.disposition is (v2.AtpDisposition.CANDIDATE_SATISFIABLE if status == 'Satisfiable'
                                    else v2.AtpDisposition.CANDIDATE_COUNTERMODEL)
    assert evidence.candidate_established and evidence.result_authority is ResultAuthority.CANDIDATE
    assert evidence.countermodel.present and not evidence.countermodel.validated
    assert not evidence.proof.present and evidence.replay is None
    assert not evidence.theorem_established and not evidence.proof_established
    assert not evidence.reconstruction_established
    assert result.backend_outcome.result.metadata['process']['returncode'] == 1
    assert result.backend_outcome.countermodel.model['excerpt'] == output(status)
    assert req.to_dict() == before
    assert len(host.calls) == len(host.lookups) == (1 if route == 'default' else 0)
    if runner is not None:
        assert len(runner.requests) == 1


@pytest.mark.parametrize('changes', [{'stdout': output('Theorem')}, {'workspace_cleaned': False}])
def test_v2_exit_one_failure_cannot_publish_model_candidate(changes):
    engine = v2.AtpExecutionEngineV2(eprover_runner=FixedRunner(lifecycle(**changes)))
    result = engine.execute(v2.AtpExecutionRequestV2(request_id='request:e:v2:rejected',
        provider='eprover', source=SOURCE, mode='pinned_solver', bounds=request().bounds))
    assert result.evidence.disposition is v2.AtpDisposition.ERROR
    assert not result.evidence.candidate_established
    assert not result.evidence.countermodel.present and not result.evidence.proof.present
    assert result.evidence.replay is None
    assert result.backend_outcome.result.metadata['process']['returncode'] == 1
