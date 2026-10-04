"""Bounded private fallback evaluation and retained-context reconstruction.

Every default engine is unavailable. Private reevaluation checks bounded outcome
consistency, not exact trace identity or external execution provenance.
The generic registry permits explicitly requested fallback for missing canonical
Hyper tools; direct and typed V2 routes retain their bounded evaluator paths.
"""
from collections.abc import Sequence
from dataclasses import fields, replace
import json
import os
import subprocess
import threading
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.backends import process, registry, resource_admission
from ipfs_datasets_py.logic.backends.hyperproperties import adapters as hyper, execution_v2 as v2
from ipfs_datasets_py.logic.backends.results import ResultStatus
from ipfs_datasets_py.logic.backends.smt import operation_budget as budget
from ipfs_datasets_py.logic.software_verification import hyperproperties as core
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler
from tests.unit.logic.backends.test_hyper_resource_admission import (
    BACKENDS, AIGER, document as base_document, request as generic_request,
    typed_request as base_request,
)

from tests.unit.logic.backends._python_admission_fixtures import python_pool

pytestmark = pytest.mark.usefixtures("python_pool")

PRIVATE_LEFT = 'private-sentinel-left-never-export'
PRIVATE_RIGHT = 'private-sentinel-right-never-export'


def forbidden(*args, **kwargs):
    pytest.fail('fallback fixture reached native execution, workspace or scheduler')


@pytest.fixture(autouse=True)
def unavailable_native_and_no_scheduler(monkeypatch):
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(os, 'system', forbidden)
    monkeypatch.setattr(process.SubprocessExecutor, 'execute', forbidden)
    monkeypatch.setattr(process.BoundedToolRunner, '_write_inputs', staticmethod(forbidden))
    monkeypatch.setattr(resource_admission, 'get_global_resource_scheduler', forbidden)
    monkeypatch.setattr(resource_scheduler, 'get_global_resource_scheduler', forbidden)
    monkeypatch.setitem(hyper.HyperpropertyBackend.__init__.__kwdefaults__, 'which', lambda name: None)


@pytest.fixture
def clock(monkeypatch):
    now = [100.0]
    fake = SimpleNamespace(monotonic=lambda: now[0])
    for module in (budget, registry, resource_admission):
        monkeypatch.setattr(module, 'time', fake)
    return now


def document(*, max_traces=4, max_pairs=6):
    doc = base_document()
    return replace(doc, document_id='',
        information_flow_policy=replace(doc.information_flow_policy, subject_fields=('tenant',)),
        self_composition_bound=replace(doc.self_composition_bound,
            max_traces=max_traces, max_pairs=max_pairs))


def trace(name, *, secret=PRIVATE_LEFT, status='ok', user='alice', tenant='tenant:a'):
    return core.ExecutionTrace(trace_id=name, public_inputs={'user_id': user},
        private_inputs={'secret': secret}, observations={'status': status}, subject={'tenant': tenant})


def pair(*, violated=True):
    return (trace('trace:a'), trace('trace:b', secret=PRIVATE_RIGHT,
        status='leak' if violated else 'ok'))


def trace_mapping(value):
    # Test input only; these private mappings must never become public evidence.
    return {name: getattr(value, name).to_dict() if hasattr(getattr(value, name), 'to_dict')
            else getattr(value, name)
            for name in ('trace_id', 'public_inputs', 'private_inputs', 'observations', 'subject')}


def request(provider='hyperltl', *, traces=None, doc=None):
    return replace(base_request(provider), document=doc or document(),
        traces=pair() if traces is None else traces, allow_fallback=True)


def result(provider='hyperltl', *, traces=None, doc=None):
    return v2.HyperExecutionEngineV2().execute(request(provider, traces=traces, doc=doc))


def assert_private_absent(value):
    encoded = json.dumps(value, sort_keys=True)
    assert PRIVATE_LEFT not in encoded and PRIVATE_RIGHT not in encoded
    assert '"private_inputs":' not in encoded


@pytest.mark.parametrize('provider', BACKENDS)
@pytest.mark.parametrize('route', ['direct', 'registry', 'v2'])
@pytest.mark.parametrize('violated', [False, True])
def test_missing_tool_routes_preserve_fallback_and_registry_availability_boundaries(monkeypatch, provider, route, violated):
    traces, doc = pair(violated=violated), document()
    expected = 'violated' if violated else 'unknown'
    if route == 'v2':
        value = result(provider, traces=traces, doc=doc)
        assert value.evidence.evidence_path is hyper.HyperEvidencePath.BOUNDED_SELF_COMPOSITION
        assert value.disposition.value == expected and value.evidence.witness.replayed is violated
        assert not value.hyperproperty_established and not value.is_proved
        assert not value.evidence.external_tool_proof
        assert replace(value).to_dict() == value.to_dict()
        assert value.backend_result.bounds == value.request.bounds
        exported = value.to_dict()
    elif route == 'direct':
        backend = BACKENDS[provider]()
        assert type(backend._runner) is resource_admission.ResourceAdmittedToolRunner
        value = backend.check(doc, traces=traces, allow_fallback=True,
            system_model=AIGER if provider == 'mchyper' else None)
        assert value.result.status.value == expected
        assert value.receipt.evidence_path is hyper.HyperEvidencePath.BOUNDED_SELF_COMPOSITION
        assert not value.receipt.external_tool_proof and not value.receipt.authorizes_universal_proof
        assert (value.receipt.counterexample is not None) is violated
        exported = value.to_dict()
    else:
        invoked = []
        run = hyper.HyperpropertyBackend.run
        fallback = hyper.HyperpropertyBackend._fallback_outcome
        def observe_run(*args, **kwargs):
            invoked.append('run')
            return run(*args, **kwargs)
        def observe_fallback(*args, **kwargs):
            invoked.append('fallback')
            return fallback(*args, **kwargs)
        monkeypatch.setattr(hyper.HyperpropertyBackend, 'run', observe_run)
        monkeypatch.setattr(hyper.HyperpropertyBackend, '_fallback_outcome', observe_fallback)
        req = generic_request(provider)
        req = replace(req, payload={**req.payload.to_dict(), 'document': doc.to_dict(),
            'allow_fallback': True, 'traces': [trace_mapping(item) for item in traces]})
        attempt, value = registry.default_backend_registry().run(req)
        assert attempt.status.value == 'succeeded'
        assert value.status.value == 'unknown'
        assert value.payload['result']['status'] == expected
        assert value.payload['result']['metadata']['evidence_path'] == 'bounded_self_composition'
        assert value.payload['result']['metadata']['external_tool_proof'] is False
        assert not value.is_theorem_proof
        assert invoked == ['run', 'fallback']
        assert value.request_digest == attempt.request_digest == req.digest
        exported = value.to_dict()
    assert_private_absent(exported)


@pytest.mark.parametrize('change', ['equal-high', 'observations', 'low-input', 'subject', 'trace-id'])
def test_same_count_trace_substitution_cannot_retain_a_previous_fallback_violation(change):
    original = result()
    left, right = original.request.traces
    updates = {'equal-high': {'private_inputs': left.private_inputs},
        'observations': {'observations': left.observations},
        'low-input': {'public_inputs': {'user_id': 'bob'}},
        'subject': {'subject': {'tenant': 'tenant:b'}},
        'trace-id': {'trace_id': 'trace:changed'}}
    changed = replace(original.request, traces=(left, replace(right, **updates[change])))
    assert changed.to_dict() == original.request.to_dict()
    assert v2._digest_of(changed.to_dict()) == original.evidence.request_digest
    if change == 'equal-high':
        assert changed.traces == original.request.traces  # compare=False private field
    with pytest.raises(v2.HyperExecutionError):
        replace(original, request=changed)
    assert replace(original).to_dict() == original.to_dict()


def test_same_count_new_violation_cannot_retain_an_old_clean_fallback_result():
    original = result(traces=pair(violated=False))
    changed = replace(original.request, traces=pair(violated=True))
    assert changed.to_dict() == original.request.to_dict()
    with pytest.raises(v2.HyperExecutionError):
        replace(original, request=changed)


@pytest.mark.parametrize('change', ['permutation', 'equivalent-private-values'])
def test_equivalent_bounded_evaluation_remains_valid_without_claiming_exact_trace_identity(change):
    original = result()
    traces = (tuple(reversed(original.request.traces)) if change == 'permutation' else
        tuple(replace(item, private_inputs={'secret': 'replacement:'+str(index)})
              for index, item in enumerate(original.request.traces)))
    changed = replace(original.request, traces=traces)
    assert changed.to_dict() == original.request.to_dict()
    restored = replace(original, request=changed)
    assert restored.to_dict() == original.to_dict()
    assert not restored.hyperproperty_established and not restored.is_proved
    assert_private_absent(restored.to_dict())


def test_bounded_trace_selection_still_sorts_before_applying_declared_max_traces():
    doc = document(max_traces=2, max_pairs=1)
    ordered = (trace('trace:a'), trace('trace:b', secret=PRIVATE_RIGHT),
        trace('trace:z', secret='other', status='leak'))
    forward = doc.evaluate_bounded_noninterference(ordered)
    reverse = doc.evaluate_bounded_noninterference(tuple(reversed(ordered)))
    assert reverse.to_dict() == forward.to_dict()
    assert forward.verdict is core.HyperpropertyVerdict.INCONCLUSIVE
    assert forward.bound_hit and forward.explored_traces == 2 and forward.explored_pairs == 1


def test_pair_budget_counts_ineligible_pairs_and_does_not_search_past_limit():
    doc = document(max_traces=3, max_pairs=1)
    traces = (trace('trace:a'), trace('trace:b', user='bob', secret=PRIVATE_RIGHT),
        trace('trace:c', secret='third', status='leak'))
    outcome = doc.evaluate_bounded_noninterference(traces)
    assert outcome.explored_pairs == 1 and outcome.bound_hit
    assert outcome.verdict is core.HyperpropertyVerdict.INCONCLUSIVE
    assert outcome.witness_bundle is None


def test_max_steps_remains_disclosed_without_inventing_execution_step_semantics():
    doc = document()
    bounded = replace(doc, document_id='', self_composition_bound=replace(doc.self_composition_bound, max_steps=1))
    value = result(doc=bounded)
    assert value.evidence.bounds.composition_max_steps == 1
    assert value.evidence.receipt['fallback_bounds']['max_steps'] == 1
    assert value.disposition is v2.HyperDisposition.VIOLATED and not value.is_proved


def test_unsupported_formula_stays_unsupported_under_private_reconstruction():
    doc = document()
    doc = replace(doc, document_id='', formula=replace(doc.formula,
        kind=core.HyperpropertyKind.OBSERVATIONAL_DETERMINISM))
    value = result(doc=doc)
    assert value.disposition is v2.HyperDisposition.UNSUPPORTED
    assert value.evidence.witness.counterexample is None
    assert not value.evidence.witness.replayed and not value.is_proved
    assert replace(value).to_dict() == value.to_dict()


def test_mapping_normalization_detaches_nested_private_inputs_and_does_not_change_public_wire():
    mapping = trace_mapping(pair()[0])
    mapping['private_inputs'] = {'secret': {'parts': [PRIVATE_LEFT]}}
    normalized = core.normalize_execution_traces([mapping], allow_mappings=True)
    mapping['private_inputs']['secret']['parts'][0] = 'external mutation'
    assert normalized[0].private_inputs['secret']['parts'][0] == PRIVATE_LEFT
    with pytest.raises(TypeError):
        normalized[0].private_inputs['secret']['parts'][0] = 'mutation'
    assert_private_absent(normalized[0].to_public_dict())


def test_mapping_input_requires_explicit_normalization_opt_in():
    mapping = trace_mapping(pair()[0])
    with pytest.raises(core.HyperpropertyValidationError):
        core.normalize_execution_traces([mapping])
    assert core.normalize_execution_traces([mapping], allow_mappings=True)[0].trace_id == mapping['trace_id']


@pytest.mark.parametrize('kind', ['cycle', 'nan', 'infinity', 'large-integer', 'surrogate', 'opaque'])
def test_private_invalid_values_fail_without_echoing_or_rendering_private_payload(kind):
    class Sensitive:
        def __repr__(self):
            pytest.fail('private opaque value was rendered')
    invalid = {'nan': float('nan'), 'infinity': float('inf'), 'large-integer': 1 << 4096,
        'surrogate': '\ud800', 'opaque': Sensitive()}
    if kind == 'cycle':
        value = {}; value['loop'] = value
    else:
        value = invalid[kind]
    mapping = trace_mapping(pair()[0]); mapping['private_inputs'] = {'secret': PRIVATE_LEFT, 'invalid': value}
    with pytest.raises(core.HyperpropertyValidationError) as caught:
        core.normalize_execution_traces([mapping], allow_mappings=True)
    assert PRIVATE_LEFT not in str(caught.value) and PRIVATE_LEFT not in repr(caught.value)


def test_finite_numeric_private_inputs_are_supported_without_exporting_them():
    mapping = trace_mapping(pair()[0]); mapping['private_inputs'] = {'secret': -(1 << 4095), 'fraction': .125}
    normalized = core.normalize_execution_traces([mapping], allow_mappings=True)
    assert normalized[0].private_inputs['secret'] == -(1 << 4095)
    assert normalized[0].private_inputs['fraction'] == .125
    assert 'private_inputs' not in normalized[0].to_public_dict()


@pytest.mark.parametrize('route', ['core', 'v2'])
def test_incremental_normalization_observes_cancel_without_consuming_remaining_inputs(route):
    cancelled = threading.Event(); visits = []
    class Rows(Sequence):
        def __len__(self):
            return 100
        def __getitem__(self, index):
            if index >= 100:
                raise IndexError
            visits.append(index)
            if index == 2:
                cancelled.set()
            return trace('trace:'+str(index))
    with pytest.raises(budget.ProofOperationCancelled):
        with budget.proof_operation_scope(timeout_ms=1000, cancellation=cancelled) as operation:
            if route == 'core':
                core.normalize_execution_traces(Rows(), checkpoint=lambda *args: operation.checkpoint('test ingestion'))
            else:
                request(traces=Rows())
    assert 3 <= len(visits) < 100
    assert budget.current_proof_operation() is None


@pytest.mark.parametrize('stop', ['cancel', 'timeout'])
def test_checkpoint_interrupts_pair_evaluation_and_withholds_late_witness(monkeypatch, clock, stop):
    cancelled = threading.Event(); projections = []
    original = core._projection
    def project(*args):
        value = original(*args); projections.append(True)
        if stop == 'cancel':
            cancelled.set()
        else:
            clock[0] += 2
        return value
    monkeypatch.setattr(core, '_projection', project)
    expected = budget.ProofOperationCancelled if stop == 'cancel' else budget.ProofOperationTimeout
    with pytest.raises(expected):
        with budget.proof_operation_scope(timeout_ms=1000, cancellation=cancelled) as operation:
            document().evaluate_bounded_noninterference(pair(),
                checkpoint=lambda *args: operation.checkpoint('test pair'))
    assert projections and budget.current_proof_operation() is None


def test_cancellation_during_witness_construction_is_checked_before_publication(monkeypatch):
    cancelled = threading.Event(); constructed = []
    original = core.ExecutionTrace.to_witness
    def witness(self, *args, **kwargs):
        value = original(self, *args, **kwargs)
        constructed.append(value); cancelled.set()
        return value
    monkeypatch.setattr(core.ExecutionTrace, 'to_witness', witness)
    with pytest.raises(budget.ProofOperationCancelled):
        with budget.proof_operation_scope(timeout_ms=1000, cancellation=cancelled) as operation:
            document().evaluate_bounded_noninterference(pair(),
                checkpoint=lambda *args: operation.checkpoint('test witness'))
    assert constructed and budget.current_proof_operation() is None


@pytest.mark.parametrize('late', [False, True])
def test_opaque_legacy_evaluator_keeps_signature_once_and_outer_stop_gate(clock, late):
    visits = []
    class Legacy(core.HyperpropertyIR):
        def evaluate_bounded_noninterference(self, traces):
            visits.append(traces)
            outcome = core.HyperpropertyIR.evaluate_bounded_noninterference(self, traces)
            if late:
                clock[0] += 2
            return outcome
    doc = document(); legacy = Legacy(**{field.name: getattr(doc, field.name) for field in fields(doc)})
    backend = hyper.HyperLTLBackend()
    if late:
        with pytest.raises(budget.ProofOperationTimeout):
            with budget.proof_operation_scope(timeout_ms=1000):
                backend.check(legacy, traces=pair(), allow_fallback=True)
    else:
        value = backend.check(legacy, traces=pair(), allow_fallback=True)
        assert value.result.status is ResultStatus.VIOLATED
    assert len(visits) == 1


def test_opaque_evaluator_typeerror_is_not_retried():
    visits = []
    class Broken(core.HyperpropertyIR):
        def evaluate_bounded_noninterference(self, traces):
            visits.append(True)
            raise TypeError('controlled callback failure')
    doc = document(); broken = Broken(**{field.name: getattr(doc, field.name) for field in fields(doc)})
    with pytest.raises(TypeError, match='controlled callback failure'):
        hyper.HyperLTLBackend().check(broken, traces=pair(), allow_fallback=True)
    assert visits == [True]


@pytest.mark.parametrize('route', ['core', 'v2', 'adapter'])
def test_record_limit_stops_at_cap_plus_one_without_materializing_the_iterable(monkeypatch, route):
    monkeypatch.setattr(core, 'MAX_EVALUATION_INPUT_TRACES', 2)
    consumed = []
    def rows():
        for index in range(100):
            consumed.append(index)
            if index > 2:
                pytest.fail('trace cap did not stop incremental consumption')
            yield trace('trace:'+str(index))
    if route == 'core':
        with pytest.raises(core.HyperpropertyValidationError):
            core.normalize_execution_traces(rows())
    elif route == 'v2':
        with pytest.raises(v2.HyperExecutionError):
            request(traces=rows())
    else:
        outcome = hyper.HyperLTLBackend().check(document(), traces=rows(), allow_fallback=True)
        assert outcome.result.status is ResultStatus.UNSUPPORTED
        assert outcome.receipt.counterexample is None
    assert consumed == [0, 1, 2]


def test_record_cap_exact_boundary_is_accepted(monkeypatch):
    monkeypatch.setattr(core, 'MAX_EVALUATION_INPUT_TRACES', 2)
    normalized = core.normalize_execution_traces(pair())
    assert len(normalized) == 2
    assert document().evaluate_bounded_noninterference(normalized).verdict is core.HyperpropertyVerdict.VIOLATED


def test_generic_adapter_rejects_excessive_trace_payload_before_checking_or_probing(monkeypatch):
    rows = [trace_mapping(trace('trace:'+str(i))) for i in range(3)]
    req = generic_request()
    req = replace(req, payload={**req.payload.to_dict(), 'traces': rows, 'allow_fallback': True})
    monkeypatch.setattr(core, 'MAX_EVALUATION_INPUT_TRACES', 2)
    backend = hyper.HyperLTLBackend()
    monkeypatch.setattr(backend, 'check', forbidden)
    monkeypatch.setattr(backend, 'probe', forbidden)
    with pytest.raises(hyper.HyperpropertyAdapterError):
        backend.run(req)


def test_aggregate_json_node_limit_cannot_be_reset_per_trace(monkeypatch):
    # A minimal trace accounts for a record, ID and four empty field maps.
    rows = [{'trace_id': 'a'}, {'trace_id': 'b'}]
    monkeypatch.setattr(core, 'MAX_EVALUATION_INPUT_NODES', 11)
    assert len(core.normalize_execution_traces(rows[:1], allow_mappings=True)) == 1
    with pytest.raises(core.HyperpropertyValidationError, match='node limit'):
        core.normalize_execution_traces(rows, allow_mappings=True)
    monkeypatch.setattr(core, 'MAX_EVALUATION_INPUT_NODES', 12)
    assert len(core.normalize_execution_traces(rows, allow_mappings=True)) == 2


def test_utf8_byte_limit_is_aggregate_and_counts_multibyte_private_text(monkeypatch):
    row = {'trace_id': 'a', 'private_inputs': {'x': 'é'}}
    monkeypatch.setattr(core, 'MAX_EVALUATION_INPUT_BYTES', 4)  # a+x+two UTF-8 bytes
    assert len(core.normalize_execution_traces([row], allow_mappings=True)) == 1
    monkeypatch.setattr(core, 'MAX_EVALUATION_INPUT_BYTES', 3)
    with pytest.raises(core.HyperpropertyValidationError, match='byte limit'):
        core.normalize_execution_traces([row], allow_mappings=True)
    monkeypatch.setattr(core, 'MAX_EVALUATION_INPUT_BYTES', 7)
    with pytest.raises(core.HyperpropertyValidationError, match='byte limit'):
        core.normalize_execution_traces([row, {**row, 'trace_id': 'b'}], allow_mappings=True)


def test_depth_limit_allows_exact_boundary_and_refuses_deeper_private_containers(monkeypatch):
    row = {'trace_id': 'a', 'private_inputs': {'secret': {'parts': [0]}}}
    monkeypatch.setattr(core, 'MAX_EVALUATION_INPUT_DEPTH', 3)
    assert len(core.normalize_execution_traces([row], allow_mappings=True)) == 1
    monkeypatch.setattr(core, 'MAX_EVALUATION_INPUT_DEPTH', 2)
    with pytest.raises(core.HyperpropertyValidationError, match='depth limit'):
        core.normalize_execution_traces([row], allow_mappings=True)


@pytest.mark.parametrize('phase', ['bounded trace selection', 'bounded noninterference pair',
                                   'bounded noninterference observation',
                                   'before bounded evaluation publication'])
def test_evaluator_checkpoints_withhold_results_at_selection_pair_observation_and_publication(phase):
    stopped = []
    class Stop(Exception):
        pass
    def checkpoint(current):
        if current == phase:
            stopped.append(current)
            raise Stop('controlled checkpoint stop')
    with pytest.raises(Stop, match='controlled checkpoint stop'):
        document().evaluate_bounded_noninterference(pair(), checkpoint=checkpoint)
    assert stopped == [phase]


def test_large_private_text_checks_cancel_between_small_encoding_chunks():
    cancelled = threading.Event(); observed = []
    mapping = {'trace_id': 'a', 'private_inputs': {'secret': 'x'*12_000}}
    def checkpoint(phase):
        if phase == 'bounded trace text traversal':
            observed.append(phase)
            if len(observed) == 4:
                cancelled.set()
        operation.checkpoint('test private encoding')
    with pytest.raises(budget.ProofOperationCancelled):
        with budget.proof_operation_scope(timeout_ms=1000, cancellation=cancelled) as operation:
            core.normalize_execution_traces([mapping], allow_mappings=True, checkpoint=checkpoint)
    assert len(observed) == 4


@pytest.mark.parametrize('stop', ['cancel', 'timeout'])
def test_reconstruction_observes_stop_inside_private_reevaluation(monkeypatch, clock, stop):
    original = result()
    cancelled = threading.Event(); entered = []
    projection = core._projection
    def interrupt(*args):
        entered.append(True)
        if stop == 'cancel':
            cancelled.set()
        else:
            clock[0] += 2
        return projection(*args)
    monkeypatch.setattr(core, '_projection', interrupt)
    expected = budget.ProofOperationCancelled if stop == 'cancel' else budget.ProofOperationTimeout
    with pytest.raises(expected):
        with budget.proof_operation_scope(timeout_ms=1000, cancellation=cancelled):
            replace(original)
    assert entered and budget.current_proof_operation() is None


def test_stopped_evaluation_does_not_poison_later_independent_operation(monkeypatch):
    value = result()
    event = threading.Event(); event.set()
    with pytest.raises(budget.ProofOperationCancelled):
        with budget.proof_operation_scope(timeout_ms=1000, cancellation=event):
            replace(value)
    event.clear()
    with budget.proof_operation_scope(timeout_ms=1000):
        assert replace(value).to_dict() == value.to_dict()
    assert budget.current_proof_operation() is None


def test_empty_trace_fallback_remains_nonreplayed_unavailable():
    value = result(traces=())
    assert value.disposition is v2.HyperDisposition.UNAVAILABLE
    assert value.evidence.evidence_path is hyper.HyperEvidencePath.NONE
    assert value.evidence.witness.counterexample is None
    assert not value.evidence.witness.replayed
    assert replace(value).to_dict() == value.to_dict()


def test_v2_mapping_defaults_and_none_trace_input_remain_compatible():
    req = request(traces=[{'private_inputs': None, 'public_inputs': None,
        'observations': None, 'subject': None, 'unrelated_extension': 'ignored'}])
    assert req.traces[0].trace_id == 'trace:0'
    assert dict(req.traces[0].private_inputs) == {}
    assert core.normalize_execution_traces(None) == ()
    assert_private_absent(req.to_dict())


def test_same_count_no_high_variation_cannot_reuse_clean_sample_reason():
    original = result(traces=pair(violated=False))
    left, right = original.request.traces
    changed = replace(original.request, traces=(left, replace(right, private_inputs=left.private_inputs)))
    assert changed.to_dict() == original.request.to_dict()
    # Both evaluator outcomes project UNKNOWN, so status equality alone is insufficient.
    assert document().evaluate_bounded_noninterference(changed.traces).verdict is core.HyperpropertyVerdict.INCONCLUSIVE
    with pytest.raises(v2.HyperExecutionError):
        replace(original, request=changed)


def test_generic_adapter_keeps_required_trace_ids_before_execution():
    req = generic_request()
    req = replace(req, payload={**req.payload.to_dict(), 'allow_fallback': True,
                               'traces': [{'public_inputs': {}, 'private_inputs': {}}]})
    with pytest.raises(hyper.HyperpropertyAdapterError):
        hyper.HyperLTLBackend().run(req)


@pytest.mark.parametrize('stop', ['cancel', 'timeout'])
def test_standalone_direct_fallback_owns_budget_and_checks_explicit_signal(monkeypatch, clock, stop):
    token = threading.Event(); visits = []
    projection = core._projection
    def interrupt(*args):
        visits.append(True)
        if stop == 'cancel':
            token.set()
        else:
            clock[0] += 2
        return projection(*args)
    monkeypatch.setattr(core, '_projection', interrupt)
    expected = budget.ProofOperationCancelled if stop == 'cancel' else budget.ProofOperationTimeout
    with pytest.raises(expected):
        hyper.HyperLTLBackend().check(document(), traces=pair(), allow_fallback=True,
            cancellation=token, bounds=replace(base_request('hyperltl').bounds, timeout_ms=1000))
    assert visits and budget.current_proof_operation() is None


def test_standalone_result_reconstruction_enforces_request_timeout_without_outer_scope(monkeypatch, clock):
    original = result()
    assert budget.current_proof_operation() is None
    entered = []
    projection = core._projection
    def consume_remaining_time(*args):
        operation = budget.current_proof_operation()
        assert operation is not None
        entered.append(operation)
        clock[0] += original.request.bounds.timeout_ms / 1000.0 + 1
        return projection(*args)
    monkeypatch.setattr(core, '_projection', consume_remaining_time)
    with pytest.raises(budget.ProofOperationTimeout):
        replace(original)
    assert entered and budget.current_proof_operation() is None
