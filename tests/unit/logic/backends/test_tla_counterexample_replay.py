"""Counterexample parsing supports real checker text without inventing replay.

The Apalache fixture is copied byte-for-byte from retained native evidence;
execution tests use only injected executors and private temporary workspaces.
"""
from dataclasses import replace
import hashlib
import subprocess
import sys
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.backends import process, registry, resource_admission
from ipfs_datasets_py.logic.backends.results import AuthoritySubstitutionError
from ipfs_datasets_py.logic.backends.smt import operation_budget
from ipfs_datasets_py.logic.backends.tla import compiler, execution_v2 as v2, runners
from ipfs_datasets_py.logic.ir_core import protocols


# Provenance: workspace/tla-artifact-payload-qualification-20261003/native/result.json
# JSON pointer: /cases/1/original_outcome/receipt/counterexample/raw
# Source JSON SHA256: 95e1595ece08ec69d9d83ff84931fb7d64638a93dddb2b3eda34be57d18a233b
APALACHE_TRACE = """---------------------------- MODULE counterexample ----------------------------

EXTENDS BoundedCounter

(* Constant initialization state *)
ConstInit == TRUE

(* Initial state [_transition(0)] *)
State0 == n = 0

(* State1 [_transition(0)] *)
State1 == n = 1

(* State2 [_transition(0)] *)
State2 == n = 2

(* The following formula holds true in the last state and violates the invariant *)
InvariantViolation == ~(0 <= n /\\ n <= 1)

================================================================================
(* Created by Apalache on Sat Oct 03 18:21:29 UTC 2026 *)
(* https://github.com/apalache-mc/apalache *)
"""
TLC_TRACE = ('Error: Invariant Safety is violated.\n'
             'State 1: <Initial predicate>\n/\\ n = 0\n/\\ step = 0\n'
             'State 2: <Next>\n/\\ n = 2\n/\\ step = 1\n')
# Exact suffix beginning at "Error: Invariant" from the retained real TLC run:
# workspace/apalache-execution-admission-qualification-20261003/native-accepted/result.json
# /mixed_cases/3/result/evidence/counterexample/raw_trace
# Source JSON SHA256: f202f38d4e73894dbc5c6a1088153ba85e3c2d9db6f141a11b92763974bdd804
TLC_NATIVE_SUFFIX = ('Error: Invariant Safety is violated.\n'
    'Error: The behavior up to this point is:\n'
    'State 1: <Initial predicate>\nn = 0\n\n'
    'State 2: <Next line 5, col 9 to line 5, col 27 of module BoundedCounter>\nn = 1\n\n'
    'State 3: <Next line 5, col 9 to line 5, col 27 of module BoundedCounter>\nn = 2\n\n'
    '3 states generated, 3 distinct states found, 0 states left on queue.\n'
    'The depth of the complete state graph search is 3.\n'
    'Finished in 00s at (2026-10-03 16:40:40)\n'
    'Trace exploration spec path: ./BoundedCounter_TTrace_1791045640.tla')
HELP = ('TLC - provides model checking and simulation of TLA+ specifications - Version 2026.07.31\n'
        'SYNOPSIS\nDESCRIPTION\n')


def mapping(*symbols):
    return tuple(compiler.TLASourceMapEntry('source:' + symbol, 'state_variable', symbol, 'variable')
                 for symbol in symbols)


def artifacts(*symbols):
    return compiler.GeneratedTLAArtifacts(
        module_name='BoundedCounter',
        model_text=('---- MODULE BoundedCounter ----\nEXTENDS Integers\nVARIABLE n\n'
                    "Init == n = 0\nNext == n < 2 /\\ n' = n + 1\n"
                    'Spec == Init /\\ [][Next]_n\nSafety == n \\in 0..1\n====\n'),
        tlc_config_text='SPECIFICATION Spec\nINVARIANT Safety\nCHECK_DEADLOCK FALSE\n',
        apalache_config_text='INIT Init\nNEXT Next\nINVARIANT Safety\n',
        source_map=mapping(*symbols), losses=(), bounds=compiler.TLACompileBounds(max_steps=3),
        source_document_id='source:counterexample-replay', source_kind='state_transition',
        safety_properties=('Safety',), liveness_properties=(), fairness_limitations=('Finite bounds only.',))


def request(selected):
    return protocols.BackendRequest(request_id='request:counterexample-replay', claim_id='claim:counter',
        declaration_id='declaration:counter', claim_digest='1' * 64,
        obligation_id='obligation:counter', obligation_digest='2' * 64,
        assumption_ids=('assumption:bounded',), logic_family='state_transition',
        query_kind=protocols.QueryKind.SATISFIABILITY,
        bounds=protocols.ExecutionBounds(timeout_ms=2000, max_steps=3,
            max_memory_bytes=256 * 1024**2, max_output_bytes=65536),
        payload={'artifacts': selected.to_dict()})


@pytest.fixture(autouse=True)
def no_native_or_shared_pool(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail('counterexample fixtures must not start native tools or consult the shared pool')
    monkeypatch.setattr(subprocess, 'Popen', denied)
    monkeypatch.setattr(process.SubprocessExecutor, 'execute', denied)
    monkeypatch.setattr(resource_admission, 'get_global_resource_scheduler', denied)
    clock = SimpleNamespace(monotonic=lambda: 100.0)
    monkeypatch.setattr(runners, 'time', clock)
    monkeypatch.setattr(operation_budget, 'time', clock)


def test_retained_apalache_trace_has_exact_provenance_and_zero_based_labels():
    assert hashlib.sha256(APALACHE_TRACE.encode()).hexdigest() == '31e06e2ad86080012a129a630636da3770d753b52bc8de7761f047bf6190f333'
    parsed = runners.parse_counterexample_trace(APALACHE_TRACE)
    assert parsed.raw == APALACHE_TRACE
    assert [state.index for state in parsed.states] == [1, 2, 3]
    assert [state.label for state in parsed.states] == ['State0', 'State1', 'State2']
    assert [dict(state.assignments) for state in parsed.states] == [{'n': '0'}, {'n': '1'}, {'n': '2'}]
    assert all(state.label + ' ==' in state.raw for state in parsed.states)
    assert not parsed.replayed
    replayed = runners.replay_counterexample(parsed, mapping('n'))
    assert replayed.replayed and replayed.states == parsed.states
    assert replayed.raw == parsed.raw
    assert any('replayed mapped symbols: n' in note for note in replayed.replay_notes)


def test_tlc_labels_indices_assignments_and_step_compatibility():
    parsed = runners.parse_counterexample_trace(TLC_TRACE)
    assert [state.index for state in parsed.states] == [1, 2]
    assert [state.label for state in parsed.states] == ['Initial predicate', 'Next']
    assert [dict(state.assignments) for state in parsed.states] == [{'n': '0', 'step': '0'}, {'n': '2', 'step': '1'}]
    replayed = runners.replay_counterexample(parsed, mapping('n'))
    assert replayed.replayed
    assert not any('unmapped' in note for note in replayed.replay_notes)


def test_retained_tlc_single_variable_trace_separates_runtime_summary():
    assert hashlib.sha256(TLC_NATIVE_SUFFIX.encode()).hexdigest() == '6632bff4aebd928858ed1d12b1eb6c90394f6f018e6119d5f3207a9ffc7a7613'
    parsed = runners.parse_counterexample_trace(TLC_NATIVE_SUFFIX)
    assert parsed.raw == TLC_NATIVE_SUFFIX
    assert [dict(state.assignments) for state in parsed.states] == [{'n': '0'}, {'n': '1'}, {'n': '2'}]
    assert runners.replay_counterexample(parsed, mapping('n')).replayed


@pytest.mark.parametrize('style', ['tlc', 'apalache'])
def test_multiline_values_and_multiple_assignments_are_not_discarded(style):
    body = ('/\\ n = 0\n/\\ record = [label |-> "a=b",\n               items |-> <<1, 2>>]\n'
            '/\\ choices = {1,\n               2}\n/\\ message = "State0 == n = 9"\n')
    text = ('State 1: <Initial predicate>\n' + body if style == 'tlc'
            else '---- MODULE counterexample ----\nState0 ==\n' + body + '\n====\n')
    parsed = runners.parse_counterexample_trace(text)
    assert len(parsed.states) == 1
    values = dict(parsed.states[0].assignments)
    assert set(values) == {'n', 'record', 'choices', 'message'}
    assert values['n'] == '0'
    assert 'items |-> <<1, 2>>' in values['record'] and values['record'].endswith(']')
    assert values['choices'].replace(' ', '').replace('\n', '') == '{1,2}'
    assert values['message'] == '"State0 == n = 9"'
    assert runners.replay_counterexample(parsed, mapping(*values)).replayed


@pytest.mark.parametrize('body', [
    'State0 == /\\ n = 0 /\\ pc = "idle"\n',
    'State0 == n = 0 /\\ pc = "idle"\n',
])
def test_apalache_same_line_conjunction_assignments_are_distinct(body):
    parsed = runners.parse_counterexample_trace('---- MODULE counterexample ----\n' + body + '====\n')
    assert len(parsed.states) == 1
    assert dict(parsed.states[0].assignments) == {'n': '0', 'pc': '"idle"'}
    assert runners.replay_counterexample(parsed, mapping('n', 'pc')).replayed


INVALID_TRACES = [
    pytest.param('', id='empty'),
    pytest.param('The invariant was violated but no state was emitted.', id='unparsed-output'),
    pytest.param('State 1: <Initial predicate>\n', id='empty-tlc-state'),
    pytest.param('State0 ==\n', id='empty-apalache-state'),
    pytest.param('State 1: <Initial>\n/\\ n = 0\n/\\ n = 1\n', id='duplicate-tlc-assignment'),
    pytest.param('State0 == /\\ n = 0 /\\ n = 1\n', id='duplicate-apalache-assignment'),
    pytest.param('State 1: <Initial>\n/\\ n = 0\nState 1: <Next>\n/\\ n = 1\n', id='duplicate-tlc-index'),
    pytest.param('State0 == n = 0\nState0 == n = 1\n', id='duplicate-apalache-index'),
    pytest.param('State 1: <Initial>\n/\\ n = 0\nState 3: <Next>\n/\\ n = 1\n', id='missing-tlc-index'),
    pytest.param('State0 == n = 0\nState2 == n = 1\n', id='missing-apalache-index'),
    pytest.param('State 0: <Initial>\n/\\ n = 0\n', id='zero-tlc-index'),
    pytest.param('State1 == n = 0\nState0 == n = 1\n', id='reordered-apalache-index'),
    pytest.param('State0 == n = 0\nState 2: <Next>\n/\\ n = 1\n', id='mixed-formats'),
    pytest.param('State0 == n = 0\nState1 == n =\n', id='truncated-final-value'),
    pytest.param('State 1: <Initial>\n/\\ n = 0\n/\\ pc =\n', id='missing-tlc-value'),
    pytest.param('State0 == /\\ n = 0\n/\\ items = <<1,\n', id='truncated-sequence'),
    pytest.param('State0 == /\\ n = 0\n/\\ pc = "unterminated\n', id='truncated-string'),
    pytest.param('State0 == /\\ n = 0\n/\\ record = [a |-> 1\n', id='truncated-record'),
    pytest.param('State0 == /\\ n = 0\n/\\ choices = {1, 2\n', id='truncated-set'),
    pytest.param('State0 == n = 0\n/\\ FALSE\n', id='unsupported-state-conjunct'),
    pytest.param('State0 == n = 0\n(* comment *)\n/\\ unknown = 1\n', id='comment-cannot-hide-unmapped-assignment'),
    pytest.param('---- MODULE counterexample ----\nState0 == n = 0\n', id='truncated-declared-module'),
    pytest.param('---- MODULE counterexample ----\nState0 == n = 0\n(*\n====\n*)\n', id='commented-module-footer'),
]


@pytest.mark.parametrize('text', INVALID_TRACES)
def test_incomplete_or_ambiguous_trace_never_claims_structural_replay(text):
    parsed = runners.parse_counterexample_trace(text)
    replayed = runners.replay_counterexample(parsed, mapping('n', 'pc', 'items', 'record', 'choices'))
    assert not replayed.replayed
    assert replayed.raw == text
    assert replayed.replay_notes


def test_commented_out_state_is_never_a_genuine_counterexample_state():
    text = ('---- MODULE counterexample ----\n(*\nState0 == n = 0\n*)\n'
            'InvariantViolation == n = 1\n====\n')
    parsed = runners.parse_counterexample_trace(text)
    assert parsed.states == ()
    assert parsed.raw == text
    assert not runners.replay_counterexample(parsed, mapping('n')).replayed


def test_multiline_comment_between_assignments_cannot_hide_partial_state():
    text = ('State0 == /\\ n = 0\n(* first line\n second line *)\n/\\ pc = "idle"\n')
    parsed = runners.parse_counterexample_trace(text)
    replayed = runners.replay_counterexample(parsed, mapping('n', 'pc'))
    assert replayed.raw == text
    if replayed.replayed:
        assert len(replayed.states) == 1
        assert dict(replayed.states[0].assignments) == {'n': '0', 'pc': '"idle"'}
    else:
        assert replayed.replay_notes


@pytest.mark.parametrize('text,symbols', [
    (TLC_TRACE, ()),
    (TLC_TRACE, ('other',)),
    ('State 1: <Initial>\n/\\ n = 0\n/\\ foreign = 1\n', ('n',)),
    ('State 1: <Initial>\n/\\ step = 0\n', ('n',)),
    ('State 1: <Initial>\n/\\ n = 0\nState 2: <Next>\n/\\ step = 1\n', ('n',)),
])
def test_empty_partial_or_missing_source_mapping_refuses_replay(text, symbols):
    parsed = runners.parse_counterexample_trace(text)
    replayed = runners.replay_counterexample(parsed, mapping(*symbols))
    assert not replayed.replayed
    assert replayed.states == parsed.states and replayed.raw == parsed.raw
    assert replayed.replay_notes


def test_structural_replay_is_idempotent_and_never_trusts_input_success_flag():
    parsed = runners.parse_counterexample_trace(TLC_TRACE)
    replayed = runners.replay_counterexample(parsed, mapping('n'))
    assert runners.replay_counterexample(replayed, mapping('n')).to_dict() == replayed.to_dict()
    assert not runners.replay_counterexample(replayed, mapping('different')).replayed
    forged = runners.CounterexampleTrace(raw='unparsed trace', replayed=True)
    assert not runners.replay_counterexample(forged, mapping('n')).replayed


def test_replay_requires_every_mapped_variable_but_not_property_definitions():
    parsed = runners.parse_counterexample_trace(TLC_TRACE)
    assert not runners.replay_counterexample(parsed, mapping('n', 'pc')).replayed
    property_entry = compiler.TLASourceMapEntry('property:safety', 'state_predicate', 'Safety', 'invariant')
    accepted = runners.replay_counterexample(parsed, (*mapping('n'), property_entry))
    assert accepted.replayed
    assert any('source:n' in note for note in accepted.replay_notes)
    assert any('structural' in note and 'not evaluated' in note for note in accepted.replay_notes)
    property_only = replace(mapping('n')[0], role='invariant')
    assert not runners.replay_counterexample(parsed, (property_only,)).replayed


@pytest.mark.parametrize('mutation', ['changed-value', 'empty-assignments', 'duplicate-state', 'missing-state', 'changed-raw'])
def test_replay_rechecks_supplied_states_against_raw_trace(mutation):
    original = runners.parse_counterexample_trace(TLC_TRACE)
    if mutation == 'changed-value':
        first = replace(original.states[0], assignments={'n': '999', 'step': '0'})
        forged = replace(original, states=(first, original.states[1]), replayed=True)
    elif mutation == 'empty-assignments':
        forged = replace(original, states=(replace(original.states[0], assignments={}),), replayed=True)
    elif mutation == 'duplicate-state':
        forged = replace(original, states=(original.states[0], original.states[0]), replayed=True)
    elif mutation == 'missing-state':
        forged = replace(original, states=(original.states[0],), replayed=True)
    else:
        forged = replace(original, raw=original.raw.replace('n = 2', 'n = 999'), replayed=True)
    replayed = runners.replay_counterexample(forged, mapping('n'))
    assert not replayed.replayed
    assert replayed.raw == forged.raw and replayed.states == forged.states
    assert replayed.replay_notes


@pytest.mark.parametrize('text', [
    pytest.param(''.join(f'State{i} == n = {i}\n' for i in range(513)), id='state-cap'),
    pytest.param('State0 == n = ' + '(' * 129 + '0' + ')' * 129 + '\n', id='nesting-cap'),
    pytest.param('\\* ' + 'a' * 262144 + '\nState0 == n = 0\n', id='text-cap'),
])
def test_parser_limit_never_silently_replays_a_partial_prefix(text):
    parsed = runners.parse_counterexample_trace(text)
    assert parsed.raw == text
    replayed = runners.replay_counterexample(parsed, mapping('n'))
    assert not replayed.replayed
    assert any('incomplete' in note for note in replayed.replay_notes)


def test_maximum_reviewed_state_count_still_replays():
    text = ''.join(f'State{i} == n = {i}\n' for i in range(512))
    parsed = runners.parse_counterexample_trace(text)
    assert len(parsed.states) == 512
    assert parsed.states[-1].index == 512 and parsed.states[-1].label == 'State511'
    assert runners.replay_counterexample(parsed, mapping('n')).replayed


@pytest.fixture
def backend_factory(tmp_path):
    workspaces = []
    def make(text, *, provider='apalache', unsafe=None):
        calls = []
        def execute(invocation, cancellation):
            phase = 'version' if invocation.argv[-1] in ('-help', 'version') else 'model'
            calls.append(phase)
            workspaces.append(invocation.cwd)
            if phase == 'version':
                return process.RawProcessResult(returncode=1 if provider == 'tlc' else 0,
                    stdout=HELP if provider == 'tlc' else '0.58.3\n')
            if provider == 'apalache':
                (invocation.cwd / 'violation.tla').write_text(text, encoding='utf-8')
            return process.RawProcessResult(returncode=12,
                stdout=('Error: Invariant Safety is violated.\n' if provider == 'apalache' else text))
        class FixtureRunner(process.BoundedToolRunner):
            def run(self, req, **kwargs):
                result = super().run(req, **kwargs)
                return replace(result, **unsafe) if unsafe and req.argv[-1] not in ('-help', 'version') else result
        selected = FixtureRunner(executor=execute, workspace_root=tmp_path)
        backend_type = runners.TLCBackend if provider == 'tlc' else runners.ApalacheBackend
        return backend_type(runner=selected, executable=sys.executable, jvm_probe=lambda: True,
                            lazy_install=False), calls
    yield make
    assert all(not directory.exists() for directory in workspaces)


@pytest.mark.parametrize('route', ['raw', 'registry', 'v2'])
@pytest.mark.parametrize('text,symbols,expected,provider', [
    pytest.param(APALACHE_TRACE, ('n',), True, 'apalache', id='native-apalache'),
    pytest.param(TLC_TRACE, ('n',), True, 'tlc', id='tlc-compatible'),
    pytest.param(APALACHE_TRACE, (), False, 'apalache', id='unmapped-native'),
    pytest.param('Unparseable raw counterexample', ('n',), False, 'apalache', id='unparsed-native'),
    pytest.param('State0 == n = 0\nState1 == n =\n', ('n',), False, 'apalache', id='partial-native'),
])
def test_real_trace_and_nonreplayable_witness_propagate_without_authority_upgrade(
        backend_factory, route, text, symbols, expected, provider):
    selected = artifacts(*symbols)
    backend, calls = backend_factory(text, provider=provider)
    req = request(selected)
    if route == 'raw':
        outcome = backend.run(req)
        trace = outcome.receipt.counterexample.to_dict()
        assert outcome.result.witness['counterexample'].to_dict() == trace
        assert outcome.result.status.value == 'violated'
        with pytest.raises(AuthoritySubstitutionError):
            outcome.result.require_authority('theorem')
        assert outcome.receipt.bounded and not outcome.receipt.unbounded_proof
    elif route == 'registry':
        backend_id = 'tla_tlc' if provider == 'tlc' else 'apalache'
        entry = next(e for e in registry.EXECUTABLE_PROVIDER_MATRIX if e.provider_id == backend_id)
        wrapper = registry.LazyMatrixProofBackend(entry, factory=lambda: backend)
        attempt, result = registry.ProofBackendRegistry((wrapper,)).run(req, backend_id=backend_id)
        assert attempt.status is protocols.AttemptStatus.SUCCEEDED
        assert result.status is protocols.ResultStatus.UNKNOWN and not result.is_theorem_proof
        assert result.payload['result_status'] == 'violated'
        assert result.payload['result_authority'] == 'model_check'
        assert result.request_digest == attempt.request_digest == req.digest
        trace = result.payload['result']['witness']['counterexample'].to_dict()
    else:
        engine = v2.StateExecutionEngineV2(**{provider: backend})
        outcome = engine.execute(v2.StateExecutionRequestV2(request_id='request:replay:v2',
            provider=provider, artifacts=selected, bounds=req.bounds))
        trace = outcome.outcome.receipt.counterexample.to_dict()
        binding = outcome.evidence.counterexample
        assert binding.replayed is expected
        assert binding.status is (v2.StateReplayStatus.REPLAYED if expected else v2.StateReplayStatus.NON_REPLAYABLE)
        assert binding.state_count == len(trace['states'])
        assert binding.raw_trace == trace['raw'].rstrip('\n')
        assert binding.bindings_complete()
        assert not outcome.evidence.is_theorem_authority
        assert outcome.evidence.disposition is v2.StateDisposition.COUNTEREXAMPLE
    assert trace['replayed'] is expected
    assert trace['raw'] == text
    assert trace['replay_notes']
    assert trace['source'] == ('checker_counterexample_file' if provider == 'apalache' else 'stdout_stderr')
    assert calls == ['model', 'version']


@pytest.mark.parametrize('changes', [
    {'output_truncated': True}, {'workspace_limit_exceeded': True},
    {'resource_exhausted': True}, {'workspace_cleaned': False},
])
def test_valid_supplemental_trace_cannot_override_failed_transport(backend_factory, changes):
    backend, calls = backend_factory(APALACHE_TRACE, unsafe=changes)
    outcome = backend.run(request(artifacts('n')))
    assert not outcome.result.is_conclusive
    assert outcome.receipt.counterexample is None
    assert 'counterexample' not in outcome.result.witness
    assert calls == ['model']


def test_v2_from_trace_does_not_accept_legacy_raw_only_replayed_flag(backend_factory):
    selected = artifacts('n')
    backend, _ = backend_factory(APALACHE_TRACE)
    result = v2.StateExecutionEngineV2(apalache=backend).execute(v2.StateExecutionRequestV2(
        request_id='request:legacy-raw-only', provider='apalache', artifacts=selected,
        bounds=request(selected).bounds))
    evidence = result.evidence
    legacy = runners.CounterexampleTrace(raw=APALACHE_TRACE, replayed=True)
    bound = v2.StateCounterexampleBindingV2.from_trace(
        disposition=v2.StateDisposition.COUNTEREXAMPLE, trace=legacy,
        module=evidence.module, config=evidence.config, bounds=evidence.bounds,
        properties=evidence.properties)
    assert bound.status is v2.StateReplayStatus.NON_REPLAYABLE
    assert not bound.replayed and bound.state_count == 0
    assert bound.raw_trace == APALACHE_TRACE.rstrip('\n')


def test_long_source_identity_keeps_truthful_replay_and_bounded_v2_notes(backend_factory):
    selected = replace(artifacts('n'), source_map=(replace(mapping('n')[0], source_id='source:' + 'n' * 800),))
    backend, _ = backend_factory(APALACHE_TRACE)
    result = v2.StateExecutionEngineV2(apalache=backend).execute(v2.StateExecutionRequestV2(
        request_id='request:long-source-id', provider='apalache', artifacts=selected,
        bounds=request(selected).bounds))
    binding = result.evidence.counterexample
    assert binding.replayed and binding.state_count == 3
    assert binding.status is v2.StateReplayStatus.REPLAYED
    assert all(len(note) <= 512 for note in binding.replay_notes)
    assert any('abbreviated' in note for note in binding.replay_notes)
    assert result.outcome.artifacts.source_map == selected.source_map


def test_v2_recomputes_mapping_for_injected_legacy_success_flag(backend_factory, monkeypatch):
    selected = artifacts()  # The injected receipt cannot manufacture a source map.
    backend, _ = backend_factory(APALACHE_TRACE)
    original_check = backend.check
    returned = []
    def legacy_check(*args, **kwargs):
        outcome = original_check(*args, **kwargs)
        legacy = replace(outcome.receipt.counterexample, replayed=True, replay_notes=('legacy flag',))
        result = replace(outcome, receipt=replace(outcome.receipt, counterexample=legacy))
        returned.append(result)
        return result
    monkeypatch.setattr(backend, 'check', legacy_check)
    result = v2.StateExecutionEngineV2(apalache=backend).execute(v2.StateExecutionRequestV2(
        request_id='request:legacy-map-flag', provider='apalache', artifacts=selected,
        bounds=request(selected).bounds))
    assert len(returned) == 1
    assert result.outcome is returned[0]
    assert result.outcome.receipt.counterexample.replayed  # Original observation stays descriptive.
    binding = result.evidence.counterexample
    assert not binding.replayed and binding.status is v2.StateReplayStatus.NON_REPLAYABLE
    assert binding.state_count == 3 and binding.raw_trace == APALACHE_TRACE.rstrip('\n')
    assert not result.evidence.is_theorem_authority


@pytest.mark.parametrize('changes', [
    {'state_count': 0, 'states': ()},
    {'state_count': 2},
    {'states': ({'index': 0, 'label': 'State0', 'assignments': {'n': '0'}, 'raw': 'State0 == n = 0'},)},
    {'states': ({'index': 1, 'label': 'State0', 'assignments': {}, 'raw': 'State0 == n = 0'},)},
])
def test_v2_replayed_binding_cannot_serialize_empty_or_inconsistent_states(backend_factory, changes):
    selected = artifacts('n')
    backend, _ = backend_factory(APALACHE_TRACE)
    result = v2.StateExecutionEngineV2(apalache=backend).execute(v2.StateExecutionRequestV2(
        request_id='request:state-binding', provider='apalache', artifacts=selected,
        bounds=request(selected).bounds))
    with pytest.raises(v2.StateExecutionError):
        replace(result.evidence.counterexample, **changes)
