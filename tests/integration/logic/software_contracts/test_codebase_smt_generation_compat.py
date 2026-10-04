"""Genuine retained @1 bytes, explicit compatibility and default @2 evidence."""
import base64
import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from ipfs_datasets_py.logic.software_contracts import codebase_verification as bridge
from ipfs_datasets_py.logic.software_contracts import codebase_applicability as applicability
from ipfs_datasets_py.logic.software_contracts import codebase_smt_compat as compat
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts.content import canonical_dag_json_bytes
# Load the process owner before temporary subprocess monkeypatches: its native
# executor binds the Popen default at import time, as ordinary Python defaults do.
from ipfs_datasets_py.logic.backends import process as native_process
from tests.integration.logic.software_contracts.test_codebase_verification import prepared, native_solvers, verify


@pytest.fixture
def legacy(tmp_path):
    # This fixture was produced by real Z3/CVC5 before the @2 producer edits,
    # under the default shared scheduler. Never generate @1 using new code.
    data = json.loads((Path(__file__).parent / 'fixtures/codebase_smt_v1.json').read_text())
    artifacts = ImmutableCAS(tmp_path / 'cas')
    for cid, value in data['structured'].items():
        assert artifacts.put(value) == cid
    for cid, value in data['source'].items():
        assert artifacts.put_bytes(base64.b64decode(value)) == cid
    bridge._IMPORTED_SOURCE_PINS.clear()
    applicability._EXTRA_PINS.clear()
    return RepositoryCodebaseIndex(artifacts=artifacts), data['metadata']


def test_genuine_legacy_bytes_keys_and_authority_survive_without_any_native_process(legacy, monkeypatch):
    index, metadata = legacy
    def forbidden(*args, **kwargs):
        pytest.fail('historical compatibility launched a native process')
    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(native_process.SubprocessExecutor.__init__, '__kwdefaults__',
        {**native_process.SubprocessExecutor.__init__.__kwdefaults__, 'popen': forbidden})
    for name, loader in [('verification', bridge.load_codebase_verification),
                         ('applicability', applicability.load_codebase_applicability)]:
        cid = metadata[name + '_cid']
        original = index.artifacts.path_for(cid).read_bytes()
        loaded = loader(index, cid)
        assert loaded._payload == original == canonical_dag_json_bytes(loaded.to_dict())
        assert loaded.artifact_cid == cid and not loaded.observed_live
        assert loaded.conditional_proved
        assert all('execution' not in row for row in loaded.to_dict()['process_observations'])
        assert loaded.to_dict()['authority']['completion_authority'] is False
        assert index.artifacts.path_for(cid).read_bytes() == original


def test_legacy_replay_in_fresh_interpreter_needs_no_checkout_or_solver(legacy):
    index, metadata = legacy
    script = '''
import json, subprocess, sys
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts.codebase_verification import load_codebase_verification
from ipfs_datasets_py.logic.software_contracts.codebase_applicability import load_codebase_applicability
def forbidden(*args, **kwargs): raise AssertionError("historical replay launched a process")
subprocess.Popen = subprocess.run = forbidden
index = RepositoryCodebaseIndex(artifacts=ImmutableCAS(sys.argv[1]))
rows = [loader(index, cid) for loader, cid in zip((load_codebase_verification,load_codebase_applicability),sys.argv[2:])]
print(json.dumps([{'cid':row.artifact_cid,'live':row.observed_live,'proved':row.conditional_proved} for row in rows]))
'''
    observed = subprocess.run([sys.executable, '-c', script, str(index.artifacts.root),
        metadata['verification_cid'], metadata['applicability_cid']], capture_output=True, text=True, timeout=30)
    assert observed.returncode == 0, observed.stderr
    assert json.loads(observed.stdout.splitlines()[-1]) == [
        {'cid':metadata[name + '_cid'], 'live':False, 'proved':True} for name in ('verification','applicability')]


@pytest.mark.parametrize('name', ['verification', 'applicability'])
@pytest.mark.parametrize('mutation', ['producer', 'dependency', 'missing', 'extra', 'reordered', 'v2_pin_substitution'])
def test_unreviewed_legacy_generations_fail_closed(legacy, name, mutation):
    index, metadata = legacy
    value = index.artifacts.get(metadata[name + '_cid'])
    pins = value['environment']['module_pins']
    if mutation == 'producer':
        pins[0]['sha256'] = '0' * 64
    elif mutation == 'dependency':
        pins[1]['sha256'] = '0' * 64
    elif mutation == 'missing':
        pins.pop()
    elif mutation == 'extra':
        pins.append({'module':'owner.unreviewed', 'sha256':'0'*64})
    elif mutation == 'reordered':
        pins[0], pins[1] = pins[1], pins[0]
    else:
        value['environment']['module_pins'] = applicability._pins() if name == 'applicability' else bridge._module_pins()
    cid = index.artifacts.put(value)
    loader = applicability.load_codebase_applicability if name == 'applicability' else bridge.load_codebase_verification
    with pytest.raises(bridge.CodebaseVerificationError, match='legacy implementation generation'):
        loader(index, cid)


@pytest.mark.parametrize('is_applicability', [False, True])
def test_legacy_allowance_refuses_semantic_dependency_change_even_when_old_pins_are_exact(legacy, is_applicability):
    index, metadata = legacy
    name = 'applicability' if is_applicability else 'verification'
    recorded = index.artifacts.get(metadata[name + '_cid'])['environment']['module_pins']
    current = copy.deepcopy(applicability._pins() if is_applicability else bridge._module_pins())
    current[1]['sha256'] = '0' * 64
    with pytest.raises(ValueError, match='semantic dependency changed'):
        compat.validate_legacy_module_pins(recorded, current, applicability=is_applicability)


@pytest.mark.parametrize('name', ['verification', 'applicability'])
def test_legacy_record_cannot_claim_new_schema_or_containment(legacy, name):
    index, metadata = legacy
    value = index.artifacts.get(metadata[name + '_cid'])
    if name == 'verification':
        value.update(schema=bridge.CODEBASE_VERIFICATION_SCHEMA, profile=bridge.CODEBASE_VERIFICATION_PROFILE)
        loader = bridge.load_codebase_verification
    else:
        value.update(schema=applicability.CODEBASE_APPLICABILITY_SCHEMA, profile=applicability.CODEBASE_APPLICABILITY_PROFILE)
        loader = applicability.load_codebase_applicability
    with pytest.raises(bridge.CodebaseVerificationError, match='implementation generation'):
        loader(index, index.artifacts.put(value))


@pytest.mark.parametrize('producer', ['verification', 'applicability'])
@pytest.mark.parametrize('failure_kind', ['operational', 'cancelled', 'os'])
def test_both_producers_forward_actual_owner_and_propagate_failed_execution_without_releasing_parent(
        prepared, native_solvers, monkeypatch, producer, failure_kind):
    import threading
    import time
    from ipfs_datasets_py.logic.software_contracts import codebase_smt_execution as execution
    from ipfs_datasets_py.logic.software_contracts.codebase_resources import acquire_codebase_resources
    from ipfs_datasets_py.logic.software_verification.applicability import RequestedInputDomain
    from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import LeaseCancelledError
    original = verify(prepared) if producer == 'applicability' else None
    signal = threading.Event()
    captured = []
    invoked = []
    failure = (execution.CodebaseSmtExecutionError('controlled phase failure', {'status':'failed'})
               if failure_kind == 'operational' else
               LeaseCancelledError('controlled phase failure') if failure_kind == 'cancelled' else
               OSError('controlled phase failure'))
    failure.execution = FrozenMap({'status':'failed'})
    index, repository, head, owner, _ = prepared
    with acquire_codebase_resources(scheduler=owner) as parent:
        started = time.monotonic()
        def factory(solver, executable, **ownership):
            actual = ownership['parent_lease']
            assert actual.parent_lease_id == parent.lease_id
            assert actual._scheduler is owner
            assert actual.memory_mb == 512 and actual.cpu_slots == actual.child_process_slots == 1
            assert started < ownership['deadline'] <= time.monotonic() + 30
            assert ownership['max_script_bytes'] == 256 * 1024
            assert not ownership['cancel_event'].is_set()
            captured.append(ownership)
            def fail(smtlib, bounds):
                assert smtlib and bounds.timeout_ms > 0
                invoked.append(solver)
                signal.set()
                assert ownership['cancel_event'].is_set()
                signal.clear()
                raise failure
            return fail
        monkeypatch.setattr(execution, 'make_codebase_smt_runner', factory)
        bridge._IMPORTED_SOURCE_PINS.clear()
        applicability._EXTRA_PINS.clear()
        with pytest.raises(type(failure), match='controlled phase failure') as error:
            if producer == 'verification':
                verify(prepared, scheduler=None, parent_lease=parent, cancel_event=signal, timeout_seconds=30)
            else:
                applicability.verify_current_codebase_applicability(index, repository,
                    expected_head=head, verification_cid=original.artifact_cid,
                    domains=[RequestedInputDomain('increment', ('True',))],
                    parent_lease=parent, cancel_event=signal, timeout_seconds=30)
        assert error.value is failure and error.value.execution['status'] == 'failed'
        assert invoked == ['z3']  # Swallowed OSError cannot launch the second solver.
        assert len(captured) == 2 and captured[0]['parent_lease'] is captured[1]['parent_lease']
        assert owner.snapshot()['active_lease_count'] == 1
        assert not parent._released
        signal.set()
        assert all(row['cancel_event'].is_set() for row in captured)


@pytest.mark.parametrize('producer', ['verification', 'applicability'])
def test_v2_phase_input_caps_match_exact_sidecar_limit_even_when_transport_change_is_valid(
        prepared, native_solvers, producer):
    from ipfs_datasets_py.logic.software_contracts.codebase_smt_execution import validate_execution_receipt
    from ipfs_datasets_py.logic.backends.smt.differential import SmtRawSolverOutput, normalize_smtlib_for_solver
    from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds
    from ipfs_datasets_py.logic.software_verification.applicability import RequestedInputDomain
    index, repository, head, owner, _ = prepared
    # Also exercise a genuine nondefault input limit: the join must derive from
    # this sidecar's request, rather than hardcoding the profile's default cap.
    limits = bridge.CodebaseVerificationLimits(max_script_bytes=64 * 1024)
    parent = verify(prepared, limits=limits)
    if producer == 'verification':
        record = parent
        loader = bridge.load_codebase_verification
    else:
        record = applicability.verify_current_codebase_applicability(index, repository,
            expected_head=head, verification_cid=parent.artifact_cid,
            domains=[RequestedInputDomain('increment', ('True',))], scheduler=owner, limits=limits)
        loader = applicability.load_codebase_applicability
    assert loader(index, record.artifact_cid)._payload == record._payload
    value = record.to_dict()
    for row in value['process_observations']:
        for phase in row['execution']['phases']:
            assert phase['limits']['max_input_bytes'] == limits.max_script_bytes
            phase['limits']['max_input_bytes'] += 64
    first = value['process_observations'][0]
    compilation = (value['solver_artifacts'][0] if producer == 'verification' else value['checks'][0])['compilation']
    raw = SmtRawSolverOutput(**{name:first[name] for name in (
        'stdout','stderr','returncode','elapsed_ms','solver_version','timed_out','unavailable')})
    # All phases still agree, and the altered cap fits the transport's bounds.
    # Only the exact producer-to-transport join distinguishes this forged claim.
    validate_execution_receipt(first['execution'], solver=first['backend_id'],
        executable=value['environment']['executables'][0]['path'],
        smtlib=normalize_smtlib_for_solver(compilation['smtlib']),
        bounds=ExecutionBounds.from_dict(value['effective_bounds']), raw=raw)
    with pytest.raises(bridge.CodebaseVerificationError, match='input cap differs from sidecar script limit'):
        loader(index, index.artifacts.put(value))
