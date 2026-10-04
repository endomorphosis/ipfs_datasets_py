"""Independent Hyper registry routing with private, synthetic native execution.

The family declaration remains a legacy HyperLTL route. Individual engine IDs
must select only their named implementation without promoting typed authority.
"""
from dataclasses import replace
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.backends import process, registry as reg, resource_admission as admission
from ipfs_datasets_py.logic.backends.hyperproperties import adapters as hyper
from ipfs_datasets_py.logic.backends.smt import operation_budget as budget
from ipfs_datasets_py.logic.conformance.matrix import build_default_matrix
from ipfs_datasets_py.logic.families.generated_catalog import DEFAULT_GENERATED_CATALOG
from ipfs_datasets_py.logic.families.providers import BASELINE_PROVIDER_CATALOG
from ipfs_datasets_py.logic.ir_core.protocols import (
    BackendRequest, ExecutionBounds, ProofResult, QueryKind, SatisfiabilityResult,
)
from ipfs_datasets_py.logic.software_verification.hyperproperties import (
    HyperpropertyIR, HyperpropertyKind, InformationFlowPolicy, ObservationKind,
    ObservationSpec, QuantifierBinding, SecurityLabel, SecurityLevel,
    SelfCompositionBound, TraceQuantifier,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources


MIB = 1024**2
FAMILY = 'hyperltl_autohyper_mchyper'
ENGINES = ('hyperltl', 'autohyper', 'mchyper')
SUCCESS = {'hyperltl': 'sat\n', 'autohyper': 'SAT\n',
           'mchyper': 'Property proved. Time = 0.01 sec\n'}
AIGER = 'aag 1 1 0 1 0\n2\n2\ni0 user_id\no0 status\nc\nfixture\n'


def document():
    policy = InformationFlowPolicy(policy_id='policy:hyper:routing',
        low_input_fields=('user_id',), high_input_fields=('secret',), observation_fields=('status',),
        labels=(SecurityLabel('label:user', 'user_id', SecurityLevel.LOW, ObservationKind.INPUT),
                SecurityLabel('label:secret', 'secret', SecurityLevel.HIGH, ObservationKind.INPUT),
                SecurityLabel('label:status', 'status', SecurityLevel.LOW, ObservationKind.OUTPUT)),
        observations=(ObservationSpec('obs:status', 'status', ObservationKind.OUTPUT, SecurityLevel.LOW),))
    return HyperpropertyIR.noninterference_document(policy=policy,
        bound=SelfCompositionBound('bound:hyper:routing', max_traces=4, max_pairs=6, max_steps=16))


def request(engine='hyperltl', *, requested_id=None, token='one', with_model=True, allow_fallback=False):
    payload = {'document': document().to_dict(), 'allow_fallback': allow_fallback}
    if engine == 'mchyper' and with_model:
        payload['system_model'] = AIGER
    return BackendRequest(request_id=f'request:hyper:routing:{engine}:{token}', claim_id='claim:hyper:routing',
        declaration_id='declaration:hyper', claim_digest='1'*64,
        obligation_id='obligation:hyper', obligation_digest='2'*64,
        assumption_ids=('assumption:bounded',), logic_family='hyperproperty',
        query_kind=QueryKind.SATISFIABILITY, requested_backend_id=engine if requested_id is None else requested_id,
        bounds=ExecutionBounds(timeout_ms=5000, max_memory_bytes=128*MIB,
                               max_output_bytes=16384, max_steps=100), payload=payload)


def forbidden(*args, **kwargs):
    pytest.fail('Hyper routing fixture attempted a native process or shared scheduler access')


@pytest.fixture(autouse=True)
def no_native_or_shared_pool(monkeypatch):
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(process.SubprocessExecutor, 'execute', forbidden)
    monkeypatch.setattr(admission, 'get_global_resource_scheduler', forbidden)


@pytest.fixture
def clock(monkeypatch):
    now = [100.0]
    for module in (admission, reg, budget):
        monkeypatch.setattr(module, 'time', SimpleNamespace(monotonic=lambda: now[0]))
    return now


@pytest.fixture
def host(tmp_path, monkeypatch):
    healthy = ProofHostResources(8, 8192, 8192, pid_task_limit=8192, available_pid_tasks=8192)
    current = [healthy]
    owner = schedulers.GlobalResourceScheduler(schedulers.ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path/'private-hyper-routing-pool.json', proof_resource_sampler=lambda: current[0],
        total_cpu_slots=8, total_memory_mb=2048, total_child_process_slots=16,
        proof_memory_headroom_mb=64, lane_reservations={}, auto_renew_leases=False,
        proof_backoff_seconds=.01, poll_interval_seconds=.002))
    constructed, looked_up, calls, prepared, acquired, resolutions = [], [], [], [], [], []
    available = {engine: True for engine in ENGINES}
    original_init = hyper.HyperpropertyBackend.__init__
    def init(backend, *args, **kwargs):
        selected = backend.engine.value
        constructed.append(selected)
        def which(name):
            looked_up.append((selected, name))
            return sys.executable if available[selected] else None
        kwargs.setdefault('which', which)
        original_init(backend, *args, **kwargs)
    monkeypatch.setattr(hyper.HyperpropertyBackend, '__init__', init)
    monkeypatch.setattr(process.shutil, 'which', lambda *args, **kwargs: sys.executable)
    def resolve():
        resolutions.append(True)
        return owner
    monkeypatch.setattr(admission, 'get_global_resource_scheduler', resolve)
    original_acquire = owner.acquire
    def acquire(*args, **kwargs):
        lease = original_acquire(*args, **kwargs)
        acquired.append(lease)
        return lease
    monkeypatch.setattr(owner, 'acquire', acquire)
    original_write = process.BoundedToolRunner._write_inputs
    def write(workspace, tool_request):
        prepared.append(workspace)
        return original_write(workspace, tool_request)
    monkeypatch.setattr(process.BoundedToolRunner, '_write_inputs', staticmethod(write))
    action = [lambda engine, invocation, signal: process.RawProcessResult(returncode=0, stdout=SUCCESS[engine])]
    def execute(self, invocation, cancellation=None):
        assert '--version' not in invocation.argv
        selected = ('autohyper' if '--explicit' in invocation.argv else
                    'mchyper' if '-pdr' in invocation.argv else 'hyperltl')
        assert cancellation is not None and not cancellation.is_set()
        assert budget.current_proof_operation() is not None
        assert invocation.limits.resident_memory_bytes == 128*MIB
        assert 0 < invocation.limits.cpu_seconds <= 5
        snapshot = owner.snapshot()
        assert snapshot['active_root_lease_count'] >= 1
        calls.append((selected, invocation, snapshot))
        return action[0](selected, invocation, cancellation)
    monkeypatch.setattr(process.SubprocessExecutor, 'execute', execute)
    yield SimpleNamespace(owner=owner, healthy=healthy, current=current, available=available,
        constructed=constructed, looked_up=looked_up, calls=calls, prepared=prepared,
        acquired=acquired, resolutions=resolutions, action=action)
    snapshot = owner.snapshot()
    assert snapshot['active_lease_count'] == snapshot['waiting_request_count'] == 0
    assert all(not path.exists() for path in prepared)


def assert_bound(req, pair, *, selected, engine):
    attempt, result = pair
    assert attempt.backend_id == result.backend_id == selected
    assert attempt.status.value == 'succeeded' and result.status.value == 'unknown'
    assert not result.is_theorem_proof and result.authority.scope_digest == req.digest
    assert attempt.request_digest == result.request_digest == req.digest
    assert result.attempt_digest == attempt.digest and result.bounds == attempt.bounds == req.bounds
    assert result.assumption_ids == req.assumption_ids
    assert result.payload['result_status'] == 'satisfied'
    assert result.payload['result_authority'] == 'hyperproperty'
    typed = result.payload['result']
    assert typed['backend_id'] == engine and typed['metadata']['engine'] == engine
    assert typed['metadata']['process']['workspace_cleaned']
    assert typed['bounds'].to_dict() == req.bounds.to_dict()


@pytest.mark.parametrize('engine', ENGINES)
@pytest.mark.parametrize('selector', ['requested', 'explicit', 'both'])
@pytest.mark.parametrize('kind', [QueryKind.SATISFIABILITY, QueryKind.THEOREM_PROOF])
def test_each_canonical_engine_reaches_only_its_named_admitted_implementation(host, engine, selector, kind):
    owner = reg.default_backend_registry()
    req = replace(request(engine, requested_id='' if selector == 'explicit' else engine), query_kind=kind)
    original = req.to_dict()
    pair = owner.run(req, backend_id=None if selector == 'requested' else engine)
    assert_bound(req, pair, selected=engine, engine=engine)
    assert isinstance(pair[1], ProofResult if kind is QueryKind.THEOREM_PROOF else SatisfiabilityResult)
    assert req.to_dict() == original
    assert host.constructed == [engine] and {name for name, _ in host.looked_up} == {engine}
    assert [name for name, *_ in host.calls] == [engine]
    assert len(host.acquired) == len(host.prepared) == len(host.resolutions) == 1
    assert host.acquired[0].released
    snapshot = host.calls[0][2]
    assert snapshot['allocated'] == {'cpu_slots': 2, 'memory_mb': 128}
    assert snapshot['allocated_child_process_slots'] == 4


@pytest.mark.parametrize('requested,selected', [('hyperltl', 'autohyper'), ('autohyper', 'mchyper'),
    ('mchyper', 'hyperltl'), (FAMILY, 'hyperltl'), ('hyperltl', FAMILY)])
def test_conflicting_canonical_selectors_fail_before_construction_or_lookup(host, requested, selected):
    req = request(requested_id=requested); original = req.to_dict()
    with pytest.raises(reg.BackendRegistryError, match='conflicts'):
        reg.default_backend_registry().run(req, backend_id=selected)
    assert req.to_dict() == original
    assert host.constructed == host.looked_up == host.calls == host.resolutions == []


@pytest.mark.parametrize('selector', ['requested', 'explicit', 'implicit'])
def test_legacy_family_and_implicit_choice_keep_hyperltl_default(host, selector):
    owner = reg.default_backend_registry()
    req = request(requested_id=FAMILY if selector == 'requested' else '')
    if selector == 'implicit':
        assert set(owner.supporting(req)) == {FAMILY, *ENGINES}
        assert owner.supporting(req)[0] == 'autohyper'  # Declaration order is not the legacy execution choice.
    pair = owner.run(req, backend_id=FAMILY if selector == 'explicit' else None)
    assert_bound(req, pair, selected=FAMILY, engine='hyperltl')
    assert host.constructed == ['hyperltl'] and [row[0] for row in host.calls] == ['hyperltl']


def test_implicit_software_verification_keeps_historical_first_provider(host, monkeypatch):
    factories = reg._factory_constructors()
    selected = []
    def factory():
        selected.append('apalache')
        # Deliberately opaque caller fixture: only routing is under test here.
        return SimpleNamespace(is_available=lambda: True, run=lambda req: None)
    factories['apalache'] = factory
    monkeypatch.setattr(reg, '_factory_constructors', lambda: factories)
    owner = reg.default_backend_registry()
    req = replace(request(requested_id=''), logic_family='software_verification')
    candidates = owner.supporting(req)
    assert candidates[0] == 'apalache' and FAMILY in candidates
    attempt, result = owner.run(req)
    assert attempt.backend_id == result.backend_id == 'apalache'
    assert attempt.status.value == 'succeeded' and result.status.value == 'unknown'
    assert attempt.request_digest == result.request_digest == req.digest
    assert selected == ['apalache'] and host.constructed == host.calls == host.resolutions == []


def test_catalogs_and_closed_matrix_publish_individual_engines_without_alias_or_live_claim(host):
    owner = reg.default_backend_registry()
    declarations = reg.declared_backend_catalog(owner)
    matrix = build_default_matrix()
    for name in (FAMILY, *ENGINES):
        assert name in owner and name in matrix.provider_ids
        assert BASELINE_PROVIDER_CATALOG.resolve(name).provider_id == name
        assert DEFAULT_GENERATED_CATALOG.get_provider(name).provider_id == name
        assert owner.capabilities_for(name).supports('hyperproperty', QueryKind.SATISFIABILITY)
        assert owner.supporting(request(requested_id=name)) == (name,)
        assert next(row for row in declarations if row['provider_id'] == name)['availability'] == 'declared'
    for name in ENGINES:
        assert name not in reg.EXECUTABLE_PROVIDER_ALIASES
        assert BASELINE_PROVIDER_CATALOG.is_available(name) is False
        assert DEFAULT_GENERATED_CATALOG.claims_proof(name) is False
    assert host.constructed == host.looked_up == host.calls == host.resolutions == []


@pytest.mark.parametrize('engine', ENGINES)
def test_explicit_availability_probe_constructs_only_named_engine(host, engine):
    owner = reg.default_backend_registry()
    assert owner.is_available(engine)
    assert host.constructed == [engine] and {name for name, _ in host.looked_up} == {engine}
    assert host.calls == host.prepared == host.acquired == host.resolutions == []


def test_alignment_path_inventory_does_not_attribute_peer_binaries_to_missing_engine(host, tmp_path, monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import alignment_capabilities as inventory
    looked_up = []
    def which(command):
        looked_up.append(command)
        return '/synthetic/'+command if command in {'AutoHyper', 'mchyper'} else None
    monkeypatch.setattr(inventory.shutil, 'which', which)
    monkeypatch.setattr(inventory, '_gguf_metadata', forbidden)
    report = inventory.describe_alignment_capabilities(tmp_path, workspace_root=tmp_path)
    assert report['inventory_only'] and not report['execution_performed'] and not report['proof_verified']
    expected = {FAMILY: ('hyperltl', 'hyperltl-sat'), 'hyperltl': ('hyperltl', 'hyperltl-sat'),
                'autohyper': ('AutoHyper', 'autohyper'), 'mchyper': ('mchyper', 'MCHyper')}
    for name, commands in expected.items():
        row = next(item for item in report['providers'] if item['provider_id'] == name)
        discovery = row['binary_discovery']
        assert tuple(item['command'] for item in discovery['commands']) == commands
        assert discovery['status'] == ('discovered' if name in {'autohyper', 'mchyper'} else 'not_found_on_path')
        assert not discovery['version_probed'] and not discovery['runtime_verified']
        assert not row['proof_verified'] and row['current_proof_authority'] == 'none'
        assert all(command in looked_up for command in commands)
    assert host.constructed == host.calls == host.resolutions == []


@pytest.mark.parametrize('engine', ENGINES)
def test_missing_selected_engine_does_not_fallback_to_available_peer_or_self_composition(host, engine):
    owner = reg.default_backend_registry(); host.available[engine] = False
    req = request(engine, allow_fallback=True); original = req.to_dict()
    attempt, result = owner.run(req)
    assert attempt.status.value == 'unavailable' and result.status.value == 'unknown'
    assert attempt.backend_id == result.backend_id == engine
    assert result.request_digest == attempt.request_digest == req.digest
    assert not result.is_theorem_proof and req.to_dict() == original
    assert host.constructed == [engine] and {name for name, _ in host.looked_up} == {engine}
    assert host.calls == host.prepared == host.acquired == host.resolutions == []


def test_missing_mchyper_system_model_is_unsupported_without_peer_execution(host):
    req = request('mchyper', with_model=False)
    attempt, result = reg.default_backend_registry().run(req)
    assert attempt.status.value == 'failed' and result.status.value == 'error'
    assert result.payload['result_status'] == 'unsupported'
    assert result.payload['result']['metadata']['engine'] == 'mchyper'
    assert not result.is_theorem_proof and result.request_digest == req.digest
    assert host.constructed == ['mchyper'] and host.calls == host.resolutions == []


def test_autohyper_unsupported_prefix_does_not_switch_to_hyperltl(host):
    doc = document()
    prefix = tuple(QuantifierBinding(item.binding_id,
        TraceQuantifier.FORALL if index == 0 else TraceQuantifier.EXISTS,
        item.variable_id, item.index) for index, item in enumerate(doc.formula.quantifier_prefix))
    doc = replace(doc, document_id='', formula=replace(doc.formula, kind=HyperpropertyKind.GENERAL,
        quantifier_prefix=prefix, matrix_statement='forall pi1. exists pi2. true'))
    req = replace(request('autohyper'), payload={'document': doc.to_dict()})
    attempt, result = reg.default_backend_registry().run(req)
    assert attempt.status.value == 'failed' and result.status.value == 'error'
    assert result.payload['result_status'] == 'unsupported' and not result.is_theorem_proof
    assert host.constructed == ['autohyper'] and host.calls == host.resolutions == []


def test_sequential_individual_engines_keep_separate_cached_delegates(host):
    owner = reg.default_backend_registry()
    for index, engine in enumerate((*ENGINES, 'autohyper')):
        req = request(engine, token=str(index))
        assert_bound(req, owner.run(req), selected=engine, engine=engine)
    assert host.constructed == list(ENGINES)
    assert [row[0] for row in host.calls] == [*ENGINES, 'autohyper']
    assert len({id(owner[engine]._delegate) for engine in ENGINES}) == 3


def until(predicate):
    deadline = time.monotonic()+2
    while not predicate():
        if time.monotonic() >= deadline:
            pytest.fail('private Hyper routing fixture wait expired')
        time.sleep(.003)


def test_concurrent_engines_share_registry_without_crossed_identity_or_leaked_leases(host):
    owner = reg.default_backend_registry(); release = threading.Event(); results = {}; errors = []
    def held(engine, invocation, signal):
        assert release.wait(3), 'test did not release synthetic engine'
        return process.RawProcessResult(returncode=0, stdout=SUCCESS[engine])
    host.action[0] = held
    def run(engine):
        try:
            req = request(engine)
            results[engine] = (req, owner.run(req))
        except BaseException as error:
            errors.append(error)
    workers = [threading.Thread(target=run, args=(engine,)) for engine in ENGINES]
    for worker in workers:
        worker.start()
    try:
        until(lambda: len(host.calls) == 3)
        snapshot = host.owner.snapshot()
        assert snapshot['active_root_lease_count'] == 3
        assert snapshot['allocated'] == {'cpu_slots': 6, 'memory_mb': 384}
        assert snapshot['allocated_child_process_slots'] == 12
    finally:
        release.set()
        for worker in workers:
            worker.join(3)
    assert not errors and all(not worker.is_alive() for worker in workers)
    assert set(results) == set(ENGINES) and sorted(host.constructed) == sorted(ENGINES)
    for engine, (req, pair) in results.items():
        assert_bound(req, pair, selected=engine, engine=engine)
    assert all(lease.released for lease in host.acquired)


@pytest.mark.parametrize('stop', ['cancel', 'timeout'])
def test_queue_interruption_keeps_selection_and_cached_engine_reusable(host, clock, stop):
    owner = reg.default_backend_registry(); token = threading.Event(); observed = {}
    host.current[0] = replace(host.healthy, available_memory_mb=32)
    req = request('autohyper')
    def run():
        try:
            observed['pair'] = owner.run(req, operation_timeout_ms=500, cancellation=token)
        except BaseException as error:
            observed['error'] = error
    worker = threading.Thread(target=run); worker.start()
    try:
        until(lambda: host.owner.snapshot()['proof_backoff'].get('reason') == 'proof_memory_headroom')
        assert host.calls == host.prepared == host.acquired == []
        if stop == 'cancel':
            token.set()
        else:
            clock[0] += .6
        worker.join(3)
        assert not worker.is_alive() and 'error' not in observed
        attempt, result = observed['pair']
        assert attempt.backend_id == result.backend_id == 'autohyper'
        assert attempt.status.value == ('cancelled' if stop == 'cancel' else 'timed_out')
        assert result.status.value == 'unknown' and result.request_digest == req.digest
    finally:
        token.set(); host.current[0] = host.healthy; worker.join(3)
    assert host.owner.snapshot()['waiting_request_count'] == 0
    later = request('autohyper', token='later')
    assert_bound(later, owner.run(later), selected='autohyper', engine='autohyper')
    assert host.constructed == ['autohyper'] and len(host.calls) == len(host.acquired) == 1
