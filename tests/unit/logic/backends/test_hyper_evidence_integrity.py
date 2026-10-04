"""Immutable Hyper records and request-bound reconstruction, without native tools.

Content hashes establish consistency, not provenance. The preserved request
wire records trace_count only; these tests do not claim private-trace digest
binding or native model membership for a structural counterexample.
"""
from dataclasses import replace
import json
import operator
import subprocess
import threading

import pytest

from ipfs_datasets_py.logic.backends import process, resource_admission as admission
from ipfs_datasets_py.logic.backends.hyperproperties import adapters as hyper, execution_v2 as v2
from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.backends.smt import operation_budget as budget
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.claims import stable_digest
from ipfs_datasets_py.logic.software_verification.hyperproperties import ExecutionTrace
from tests.unit.logic.backends.test_hyper_resource_admission import (
    BACKENDS, SUCCESS, TRACE, VIOLATION, typed_request,
    host as private_admission,
)

from tests.unit.logic.backends._python_admission_fixtures import python_pool

pytestmark = pytest.mark.usefixtures("python_pool")


def denied(*args, **kwargs):
    pytest.fail('Hyper integrity fixture reached native execution or shared admission')


@pytest.fixture(autouse=True)
def no_native_or_shared_pool(monkeypatch):
    monkeypatch.setattr(subprocess, 'Popen', denied)
    monkeypatch.setattr(process.SubprocessExecutor, 'execute', denied)
    monkeypatch.setattr(admission, 'get_global_resource_scheduler', denied)


@pytest.fixture
def result_factory(private_admission):
    def make(provider='hyperltl', path='violated', *, absent=False):
        request = replace(typed_request(provider), source_ref_ids=('source:original',),
            metadata={'review': {'labels': ['original']}})
        selected = None
        if absent or path in {'unavailable', 'evaluator-fallback', 'empty-fallback'}:
            selected = BACKENDS[provider](which=lambda name: None)
        elif path == 'error':
            class Broken(BACKENDS[provider]):
                def check(self, document, **kwargs):
                    raise hyper.HyperpropertyAdapterError('controlled adapter failure')
            selected = Broken()
        if path == 'capability':
            request = replace(request, mode=v2.HyperExecutionMode.CAPABILITY_PROBE)
        elif path == 'mock':
            request = replace(request, mock_output={'review': {'labels': ['original']}})
        elif path == 'fallback-rejected':
            request = replace(request, fallback_output={'review': {'labels': ['original']}})
        elif path == 'evaluator-fallback':
            traces = tuple(ExecutionTrace(trace_id=f'execution:{i}', public_inputs={'user_id': 'alice'},
                private_inputs={'secret': str(i)}, observations={'status': status})
                for i, status in enumerate(('ok', 'leak')))
            request = replace(request, traces=traces, allow_fallback=True)
        elif path == 'empty-fallback':
            request = replace(request, allow_fallback=True)
        raw = SUCCESS[provider] if path == 'satisfied' else VIOLATION[provider]+TRACE
        if path == 'malformed-witness':
            raw = VIOLATION[provider]+TRACE.replace('obs.status = leak\n', '')
        private_admission.action[0] = lambda invocation, signal: process.RawProcessResult(returncode=0, stdout=raw)
        engine = v2.HyperExecutionEngineV2(**({provider: selected} if selected is not None else {}))
        return engine.execute(request)
    return make


def detached(value):
    return json.loads(json.dumps(value))


def at(value, path):
    for key in path:
        value = value[key]
    return value


def alter(value, path, replacement='changed'):
    operator.setitem(at(value, path[:-1]), path[-1], replacement)


def evidence_with(result, **changes):
    return replace(result.evidence, content_digest='', **changes)


@pytest.mark.parametrize('provider', BACKENDS)
@pytest.mark.parametrize('path', ['satisfied', 'violated'])
def test_all_native_fixture_engines_reconstruct_with_declared_bindings_and_bounded_authority(result_factory, provider, path):
    result = result_factory(provider, path)
    before = result.to_dict()
    assert replace(result).to_dict() == before
    assert detached(before) == before
    assert result.evidence.request_id == result.request.request_id
    assert result.evidence.request_digest == v2._digest_of(result.request.to_dict())
    assert result.evidence.bounds.timeout_ms == result.request.bounds.timeout_ms
    assert result.backend_result.bounds == result.request.bounds
    assert result.backend_result.authority is ResultAuthority.HYPERPROPERTY
    assert result.backend_result.translation_ceiling is EvidenceAuthority.BOUNDED
    assert result.evidence.hyperproperty_established and not result.is_proved
    assert not result.evidence.authorizes_universal_proof
    assert result.evidence.witness.replayed is (path == 'violated')
    assert result.backend_result.metadata['process']['workspace_cleaned']


@pytest.mark.parametrize('path', ['unavailable', 'error', 'capability', 'mock',
                                'fallback-rejected', 'evaluator-fallback', 'malformed-witness'])
def test_nonstandard_paths_still_reconstruct_without_gaining_proof_authority(result_factory, path):
    result = result_factory(path=path)
    assert replace(result).to_dict() == result.to_dict()
    assert not result.is_proved and not result.evidence.authorizes_universal_proof
    if path != 'malformed-witness':
        assert not result.evidence.hyperproperty_established
    if path == 'evaluator-fallback':
        assert result.evidence.evidence_path is hyper.HyperEvidencePath.BOUNDED_SELF_COMPOSITION
        assert result.evidence.witness.replayed and result.evidence.witness.counterexample['raw'] == ''
        assert not result.evidence.external_tool_proof
    if path == 'malformed-witness':
        assert result.disposition is v2.HyperDisposition.VIOLATED
        assert result.evidence.hyperproperty_established and not result.evidence.witness.replayed


def test_existing_content_digest_projection_is_preserved(result_factory):
    result = result_factory()
    wire = result.evidence.to_dict()
    projection = {key: wire[key] for key in ('bounds', 'disposition', 'engine', 'formula',
        'mode', 'request_digest', 'request_id', 'system', 'witness')}
    assert result.evidence.content_digest == v2._digest_of(projection)
    assert replace(result.evidence).content_digest == result.evidence.content_digest
    assert replace(result.evidence, content_digest='').to_dict() == wire


@pytest.mark.parametrize('kind', ['explicit-forgery', 'bounds', 'formula', 'witness', 'request-id'])
def test_stale_or_forged_supplied_content_hash_is_rejected(result_factory, kind):
    evidence = result_factory().evidence
    changes = {'explicit-forgery': {'content_digest': '0'*64},
        'bounds': {'bounds': replace(evidence.bounds, timeout_ms=evidence.bounds.timeout_ms+1)},
        'formula': {'formula': replace(evidence.formula, matrix_statement='different formula')},
        'witness': {'witness': replace(evidence.witness, trace_count=evidence.witness.trace_count+1)},
        'request-id': {'request_id': 'request:other'}}
    with pytest.raises(v2.HyperExecutionError):
        replace(evidence, **changes[kind])


@pytest.mark.parametrize('path', [
    ('formula', 'quantifier_prefix', 0, 'variable_id'),
    ('system', 'observation_map', 'low_input_fields', 0),
    ('capability', 'capability', 'limitations', 0),
    ('witness', 'counterexample', 'traces', 0, 'observations', 'status'),
    ('receipt', 'quantifier_order', 'bindings', 0, 'variable_id'),
])
def test_evidence_nested_mapping_and_sequence_mutation_is_denied(result_factory, path):
    result = result_factory()
    before = detached(result.to_dict())
    selected = getattr(result.evidence, path[0])
    if len(path) > 1 and not isinstance(selected, dict) and hasattr(selected, path[1]):
        selected = getattr(selected, path[1]); tail = path[2:]
    else:
        tail = path[1:]
    with pytest.raises(TypeError):
        alter(selected, tail)
    assert result.to_dict() == before
    assert replace(result).to_dict() == before


@pytest.mark.parametrize('field', ['mock_output', 'fallback_output', 'metadata'])
def test_request_nested_payloads_are_immutable_and_constructor_inputs_are_detached(result_factory, field):
    request = result_factory(path='capability').request
    source = {'review': {'labels': ['original']}}
    immutable = replace(request, **{field: source})
    before = detached(immutable.to_dict())
    source['review']['labels'][0] = 'external mutation'
    assert immutable.to_dict() == before
    with pytest.raises(TypeError):
        alter(getattr(immutable, field), ('review', 'labels', 0))
    wire = immutable.to_dict(); alter(wire, (field, 'review', 'labels', 0))
    assert immutable.to_dict() == before


@pytest.mark.parametrize('record', ['formula', 'system', 'witness', 'receipt', 'metadata'])
def test_binding_constructor_inputs_cannot_mutate_later_evidence(result_factory, record):
    evidence = result_factory().evidence
    original = detached(evidence.to_dict())
    if record == 'formula':
        source = evidence.formula.to_dict()['quantifier_prefix']
        bound = replace(evidence.formula, quantifier_prefix=source)
        source[0]['variable_id'] = 'var:external'
        assert bound.to_dict() == original['formula']
    elif record == 'system':
        source = evidence.system.to_dict()['observation_map']
        bound = replace(evidence.system, observation_map=source)
        source['low_input_fields'][0] = 'external'
        assert bound.to_dict() == original['system']
    elif record == 'witness':
        source = evidence.witness.to_dict()['counterexample']
        bound = replace(evidence.witness, counterexample=source)
        source['traces'][0]['observations']['status'] = 'external'
        assert bound.to_dict() == original['witness']
    else:
        source = evidence.to_dict()['receipt'] if record == 'receipt' else {'review': {'labels': ['original']}}
        bound = replace(evidence, **{record: source})
        before = detached(bound.to_dict())
        path = ('quantifier_order', 'bindings', 0, 'variable_id') if record == 'receipt' else ('review', 'labels', 0)
        alter(source, path)
        assert bound.to_dict() == before
        with pytest.raises(TypeError):
            alter(getattr(bound, record), path)
    assert evidence.to_dict() == original


@pytest.mark.parametrize('path', [
    ('request', 'metadata', 'review', 'labels', 0),
    ('evidence', 'formula', 'quantifier_prefix', 0, 'variable_id'),
    ('evidence', 'system', 'observation_map', 'low_input_fields', 0),
    ('evidence', 'capability', 'capability', 'limitations', 0),
    ('evidence', 'witness', 'counterexample', 'traces', 0, 'observations', 'status'),
    ('evidence', 'receipt', 'quantifier_order', 'bindings', 0, 'variable_id'),
    ('translation', 'quantifier_order', 'bindings', 0, 'variable_id'),
    ('translation', 'observation_map', 'observation_kinds', 'status'),
    ('translation', 'auxiliary_files', 'system.explicit'),
])
def test_serialized_nested_snapshots_are_fully_detached(result_factory, path):
    result = result_factory('autohyper')
    before = detached(result.to_dict()); snapshot = result.to_dict()
    alter(snapshot, path)
    assert result.to_dict() == before
    assert replace(result).to_dict() == before


@pytest.mark.parametrize('field', ['observation-kinds', 'quantifier-bindings', 'auxiliary-files'])
def test_adapter_translation_containers_are_immutable_and_input_detached(result_factory, field):
    translation = result_factory('autohyper').translation
    before = translation.to_dict()
    if field == 'observation-kinds':
        source = dict(translation.observation_map.observation_kinds)
        changed = replace(translation.observation_map, observation_kinds=source)
        source['status'] = 'external'
        assert changed.to_dict() == translation.observation_map.to_dict()
        target, path = changed.observation_kinds, ('status',)
    elif field == 'quantifier-bindings':
        source = translation.quantifier_order.to_dict()['bindings']
        changed = replace(translation.quantifier_order, bindings=source)
        source[0]['variable_id'] = 'var:external'
        assert changed.to_dict() == translation.quantifier_order.to_dict()
        target, path = changed.bindings, (0, 'variable_id')
    else:
        source = dict(translation.auxiliary_files)
        changed = replace(translation, auxiliary_files=source)
        source['system.explicit'] = 'external'
        assert changed.to_dict() == before
        target, path = changed.auxiliary_files, ('system.explicit',)
    with pytest.raises(TypeError):
        alter(target, path)
    assert translation.to_dict() == before


@pytest.mark.parametrize('field', ['request_id', 'timeout_ms', 'max_steps', 'max_memory_bytes',
    'max_output_bytes', 'source_ref_ids', 'system_model', 'document', 'mode', 'allow_fallback'])
@pytest.mark.parametrize('path', ['satisfied', 'violated'])
def test_reconstructed_result_cannot_be_rebound_to_a_different_request(result_factory, field, path):
    result = result_factory(path=path); request = result.request
    if field in {'timeout_ms', 'max_steps', 'max_memory_bytes', 'max_output_bytes'}:
        altered = replace(request, bounds=replace(request.bounds, **{field: getattr(request.bounds, field)+1}))
    elif field == 'document':
        doc = request.document
        altered = replace(request, document=replace(doc, document_id='',
            formula=replace(doc.formula, formula_id='formula:other')))
    else:
        values = {'request_id': 'request:other', 'source_ref_ids': ('source:other',),
            'system_model': 'different reviewed system', 'mode': v2.HyperExecutionMode.MOCK,
            'allow_fallback': not request.allow_fallback}
        altered = replace(request, **{field: values[field]})
    with pytest.raises(v2.HyperExecutionError):
        replace(result, request=altered)


@pytest.mark.parametrize('field', ['request_id', 'request_digest', 'source_ref_ids',
    'timeout', 'steps', 'composition', 'formula_digest', 'document_digest', 'quantifier_prefix',
    'system_digest', 'observation_map', 'status'])
def test_recomputed_evidence_digest_does_not_authorize_inconsistent_binding(result_factory, field):
    result = result_factory('autohyper', path='satisfied'); evidence = result.evidence
    changes = {}
    if field in {'request_id', 'request_digest', 'source_ref_ids', 'status'}:
        key, value = {'request_id': ('request_id', 'request:other'),
            'request_digest': ('request_digest', '1'*64), 'source_ref_ids': ('source_ref_ids', ('source:other',)),
            'status': ('result_status', ResultStatus.UNKNOWN)}[field]
        changes[key] = value
    elif field in {'timeout', 'steps', 'composition'}:
        key = {'timeout': 'timeout_ms', 'steps': 'max_steps', 'composition': 'max_pairs'}[field]
        changes['bounds'] = replace(evidence.bounds, **{key: getattr(evidence.bounds, key)+1})
    elif field in {'formula_digest', 'document_digest', 'quantifier_prefix'}:
        value = '1'*64
        if field == 'quantifier_prefix':
            value = evidence.formula.to_dict()['quantifier_prefix']; value[0]['variable_id'] = 'var:other'
        changes['formula'] = replace(evidence.formula, **{field: value})
    elif field == 'system_digest':
        changes['system'] = replace(evidence.system, system_digest='1'*64)
    else:
        value = evidence.system.to_dict()['observation_map']; value['low_input_fields'] = ['different']
        changes['system'] = replace(evidence.system, observation_map=value)
    with pytest.raises(v2.HyperExecutionError):
        replace(result, evidence=evidence_with(result, **changes))


@pytest.mark.parametrize('field', ['backend_id', 'status', 'timeout_ms', 'max_steps',
                                 'max_memory_bytes', 'max_output_bytes'])
def test_typed_backend_result_must_match_provider_status_and_every_declared_execution_bound(result_factory, field):
    result = result_factory()
    backend = result.backend_result
    if field in {'backend_id', 'status'}:
        changed = replace(backend, **{field: 'other-provider' if field == 'backend_id' else ResultStatus.SATISFIED})
    else:
        changed = replace(backend, bounds=replace(backend.bounds, **{field: getattr(backend.bounds, field)+1}))
    with pytest.raises(v2.HyperExecutionError):
        replace(result, backend_result=changed)


@pytest.mark.parametrize('field', ['engine', 'document_digest', 'formula_id', 'matrix_statement',
                                 'auxiliary_files', 'quantifier_order'])
def test_attached_translation_cannot_be_swapped_independently_of_evidence(result_factory, field):
    result = result_factory('autohyper', path='satisfied')
    translation = result.translation
    values = {'engine': hyper.HyperEngine.MCHYPER, 'document_digest': '1'*64,
        'formula_id': 'formula:other', 'matrix_statement': 'different statement',
        'auxiliary_files': {'system.explicit': 'different explicit system'}}
    if field == 'quantifier_order':
        rows = translation.quantifier_order.to_dict()['bindings']; rows[0]['variable_id'] = 'var:other'
        value = replace(translation.quantifier_order, bindings=rows)
    else:
        value = values[field]
    with pytest.raises(v2.HyperExecutionError):
        replace(result, translation=replace(translation, **{field: value}))


@pytest.mark.parametrize('field,value', [('document_digest', '1'*64), ('translation_digest', '1'*64),
    ('engine', 'mchyper'), ('timeout_ms', 999), ('status', 'satisfied')])
def test_receipt_cross_links_cannot_be_replaced_under_an_otherwise_valid_content_digest(result_factory, field, value):
    result = result_factory()
    receipt = result.evidence.to_dict()['receipt']; receipt[field] = value
    with pytest.raises(v2.HyperExecutionError):
        replace(result, evidence=evidence_with(result, receipt=receipt))


@pytest.mark.parametrize('path', ['unavailable', 'error', 'capability', 'mock',
                                'fallback-rejected', 'evaluator-fallback', 'malformed-witness'])
def test_request_binding_is_required_on_paths_without_a_positive_native_witness(result_factory, path):
    result = result_factory(path=path)
    with pytest.raises(v2.HyperExecutionError):
        replace(result, request=replace(result.request, request_id='request:other'))


@pytest.mark.parametrize('provider', BACKENDS)
@pytest.mark.parametrize('path', ['engine', 'capability'])
def test_unicode_document_preserves_legitimate_adapter_and_v2_digest_conventions(private_admission, provider, path):
    request = typed_request(provider)
    doc = replace(request.document, document_id='', metadata={'description': 'π café 日本語'})
    request = replace(request, document=doc,
        mode=v2.HyperExecutionMode.ENGINE if path == 'engine' else v2.HyperExecutionMode.CAPABILITY_PROBE)
    private_admission.action[0] = lambda invocation, signal: process.RawProcessResult(
        returncode=0, stdout=SUCCESS[provider])
    result = v2.HyperExecutionEngineV2().execute(request)
    assert replace(result).to_dict() == result.to_dict()
    assert result.evidence.request_digest == v2._digest_of(request.to_dict())
    if path == 'engine':
        assert result.translation.document_digest == stable_digest(doc.semantic_dict())
        assert result.translation.document_digest != request.document_digest
        assert result.evidence.formula.document_digest == result.translation.document_digest
        assert result.disposition is v2.HyperDisposition.SATISFIED
    else:
        assert result.evidence.formula.document_digest == request.document_digest
        assert not result.evidence.hyperproperty_established


@pytest.mark.parametrize('kind', ['cycle', 'depth', 'nodes', 'bytes'])
def test_public_payload_freezing_has_finite_cycle_depth_node_and_byte_bounds(kind):
    if kind == 'cycle':
        payload = {}; payload['loop'] = payload
    elif kind == 'depth':
        nested = 'leaf'
        for _ in range(70):
            nested = [nested]
        payload = {'nested': nested}
    elif kind == 'nodes':
        payload = {'nodes': [0]*65_537}
    else:
        # Reuse one 1MiB string: exercise total encoded size without allocating
        # a 17MiB fixture or materializing its serialization.
        payload = {'chunks': ['x'*(1024**2)]*17}
    with pytest.raises(v2.HyperExecutionError):
        replace(typed_request('hyperltl'), mock_output=payload)


def test_large_payload_freezing_observes_operation_cancellation_before_consuming_all_items():
    cancelled = threading.Event(); visited = []
    class InterruptingMapping(dict):
        def items(self):
            for index in range(256):
                visited.append(index)
                if index == 10:
                    cancelled.set()
                yield str(index), {'value': index}
    request = typed_request('hyperltl')
    with pytest.raises(budget.ProofOperationCancelled):
        with budget.proof_operation_scope(timeout_ms=1000, cancellation=cancelled):
            replace(request, mock_output=InterruptingMapping())
    assert 11 <= len(visited) < 256
    assert budget.current_proof_operation() is None


@pytest.mark.parametrize('field', ['request-metadata', 'evidence-metadata', 'observation-map'])
def test_none_mapping_normalization_remains_compatible(result_factory, field):
    result = result_factory(path='capability')
    if field == 'request-metadata':
        value = replace(result.request, metadata=None)
        assert value.to_dict()['metadata'] == {}
        assert value.mock_output is None and value.fallback_output is None
    elif field == 'evidence-metadata':
        value = replace(result.evidence, metadata=None)
        assert value.to_dict()['metadata'] == {} and value.receipt is None
    else:
        value = replace(result.evidence.system, observation_map=None)
        assert value.to_dict()['observation_map'] == {}


@pytest.mark.parametrize('kind', ['cyclic-variable', 'nested-index', 'unknown-cyclic-field'])
def test_quantifier_binding_rows_reject_nested_or_cyclic_data_before_recursive_freezing(kind):
    order = hyper.QuantifierOrder.from_document(typed_request('hyperltl').document)
    rows = order.to_dict()['bindings']
    if kind == 'cyclic-variable':
        rows[0]['variable_id'] = rows[0]
    elif kind == 'nested-index':
        rows[0]['index'] = {'nested': [0]}
    else:
        rows[0]['extension'] = rows[0]
    with pytest.raises(hyper.HyperpropertyAdapterError):
        replace(order, bindings=rows)


@pytest.mark.parametrize('path', ['mock', 'fallback-rejected'])
def test_absent_tool_rejection_preserves_request_availability_and_separate_capability(result_factory, path):
    result = result_factory(path=path, absent=True)
    assert replace(result).to_dict() == result.to_dict()
    assert result.request.available and result.evidence.available
    assert not result.evidence.capability.available
    assert result.backend_result is None and result.evidence.receipt is None
    assert not result.evidence.hyperproperty_established and not result.evidence.external_tool_proof


def test_empty_fallback_retains_unavailable_terminal_disclosure(result_factory):
    result = result_factory(path='empty-fallback')
    assert result.request.allow_fallback and result.request.traces == ()
    assert result.disposition is v2.HyperDisposition.UNAVAILABLE
    assert result.evidence.evidence_path is hyper.HyperEvidencePath.NONE
    assert result.evidence.receipt['fallback_bounds']['max_pairs'] == result.request.document.self_composition_bound.max_pairs
    assert not result.evidence.hyperproperty_established and not result.evidence.witness.replayed
    assert replace(result).to_dict() == result.to_dict()


@pytest.mark.parametrize('path', [
    ('counterexample', 'formula_id'),
    ('counterexample', 'traces', 0, 'observations', 'status'),
    ('witness_bundle', 'formula_id'),
    ('witness_bundle', 'traces', 0, 'observations', 'status'),
])
def test_typed_backend_witness_cannot_disagree_with_validated_native_projection(result_factory, path):
    result = result_factory()
    witness = result.backend_result.witness.to_dict()
    alter(witness, path)
    with pytest.raises(v2.HyperExecutionError):
        replace(result, backend_result=replace(result.backend_result, witness=witness))


@pytest.mark.parametrize('field,value', [('formula_id', 'formula:forged'), ('raw', 'TRACE forged:\n'),
                                       ('replayed', False)])
def test_receipt_counterexample_tampering_cannot_hide_behind_old_receipt_identity(result_factory, field, value):
    result = result_factory()
    receipt = result.evidence.to_dict()['receipt']
    receipt['counterexample'][field] = value
    with pytest.raises(v2.HyperExecutionError):
        replace(result, evidence=evidence_with(result, receipt=receipt))


def test_fractional_receipt_timeout_restores_original_float_for_identity_validation(private_admission):
    request = typed_request('hyperltl')
    request = replace(request, bounds=replace(request.bounds, timeout_ms=1379))
    private_admission.action[0] = lambda invocation, signal: process.RawProcessResult(returncode=0, stdout='sat\n')
    result = v2.HyperExecutionEngineV2().execute(request)
    assert result.evidence.receipt['timeout_ms'] == 1379
    assert 'timeout_seconds' not in result.evidence.receipt
    assert replace(result).to_dict() == result.to_dict()


@pytest.mark.parametrize('attachment', ['counterexample-and-bundle', 'bundle-only'])
def test_no_evidence_path_rejects_witness_attachments_even_with_recomputed_crosslinks(result_factory, attachment):
    positive = result_factory()
    result = result_factory(path='unavailable')
    original = detached(result.to_dict())
    assert result.evidence.evidence_path is hyper.HyperEvidencePath.NONE
    assert result.disposition is v2.HyperDisposition.UNAVAILABLE
    assert positive.evidence.witness.replayed
    receipt = result.evidence.to_dict()['receipt']
    witness = result.backend_result.witness.to_dict()
    witness['witness_bundle'] = positive.backend_result.witness.to_dict()['witness_bundle']
    projected = result.evidence.witness
    if attachment == 'counterexample-and-bundle':
        receipt['counterexample'] = positive.evidence.witness.to_dict()['counterexample']
        witness['counterexample'] = detached(receipt['counterexample'])
        projected = positive.evidence.witness

    # Bind the forged attachments consistently: the rejection must be the
    # NONE-path rule, rather than an old digest, receipt ID or result ID.
    preimage = {key: value for key, value in receipt.items()
                if key not in {'receipt_id', 'timeout_ms'}}
    preimage['timeout_seconds'] = max(.001, result.request.bounds.timeout_ms / 1000.0)
    receipt['receipt_id'] = 'hyperproperty-check-receipt:' + stable_digest(preimage)
    witness['receipt_id'] = receipt['receipt_id']
    backend = replace(result.backend_result, witness=witness,
        result_id='hyperproperty-result:' + stable_digest({'receipt': receipt['receipt_id']}))
    evidence = evidence_with(result, receipt=receipt, witness=projected)
    assert evidence.content_digest == v2._digest_of({key: evidence.to_dict()[key]
        for key in ('bounds', 'disposition', 'engine', 'formula', 'mode',
                    'request_digest', 'request_id', 'system', 'witness')})
    with pytest.raises(v2.HyperExecutionError,
                       match='^no-evidence path cannot carry counterexample or witness bundle$'):
        replace(result, backend_result=backend, evidence=evidence)
    assert result.to_dict() == original
    assert replace(result).to_dict() == original
