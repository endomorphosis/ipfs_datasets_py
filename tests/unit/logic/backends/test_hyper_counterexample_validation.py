"""Native Hyper trace projections are checked, never treated as model replay.

All execution below uses a private admission owner and a synthetic executor.
These cases establish neither installed-engine grammar nor semantic reachability.
"""
from dataclasses import replace
import subprocess

import pytest

from ipfs_datasets_py.logic.backends import process, registry, resource_admission as admission
from ipfs_datasets_py.logic.backends.hyperproperties import adapters as hyper, execution_v2 as v2
from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.software_verification.hyperproperties import (
    ExecutionTrace, HyperpropertyIR, ObservationKind, ObservationSpec,
    QuantifierBinding, SecurityLabel, SecurityLevel, TraceQuantifier,
)
from tests.unit.logic.backends.test_hyper_resource_admission import (
    BACKENDS, MIB, TRACE, VIOLATION, document, request, typed_request,
    host as private_admission,
)

from tests.unit.logic.backends._python_admission_fixtures import python_pool

pytestmark = pytest.mark.usefixtures("python_pool")


def forbidden(*args, **kwargs):
    pytest.fail('structural Hyper fixture reached native execution or shared admission')


@pytest.fixture(autouse=True)
def no_native_or_shared_pool(monkeypatch):
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(process.SubprocessExecutor, 'execute', forbidden)
    monkeypatch.setattr(admission, 'get_global_resource_scheduler', forbidden)


@pytest.fixture
def context():
    base = document()
    policy = replace(base.information_flow_policy,
        observation_fields=('status', 'public_token'), subject_fields=('task_id',),
        labels=base.information_flow_policy.labels + (
            SecurityLabel('label:token', 'public_token', SecurityLevel.LOW, ObservationKind.OUTPUT),),
        observations=base.information_flow_policy.observations + (
            ObservationSpec('obs:token', 'public_token', ObservationKind.OUTPUT, SecurityLevel.LOW),))
    doc = HyperpropertyIR.noninterference_document(policy=policy, bound=base.self_composition_bound)
    return doc, hyper.ObservationMap.from_document(doc), hyper.QuantifierOrder.from_document(doc)


def block(label, status, token, *, user='alice', subject='task:1'):
    return (f'TRACE {label}:\n  public.user_id = {user}\n  obs.status = {status}\n'
            f'  obs.public_token = {token}\n  subject.task_id = {subject}\n')


LEFT = block('pi1', 'ok', 'a')
RIGHT = block('pi2', 'leak', 'b')
RAW = LEFT + RIGHT
DIFF = 'DIFF field=status left=ok right=leak\n'


def parse(context, raw=RAW):
    doc, mapping, order = context
    return hyper.parse_hyper_counterexample(raw, formula_id=doc.formula.formula_id,
        observation_map=mapping, quantifier_order=order)


def replay(context, value, **kwargs):
    doc, mapping, order = context
    return hyper.replay_hyper_counterexample(value, mapping, order,
        formula_id=kwargs.pop('formula_id', doc.formula.formula_id), **kwargs)


def bundle(context, value, **kwargs):
    doc, mapping, order = context
    return value.to_witness_bundle(observation_map=mapping, quantifier_order=order,
        formula_id=doc.formula.formula_id, **kwargs)


@pytest.mark.parametrize('raw', [RAW, RIGHT + LEFT, 'unsat\nengine log header\n' + RAW,
                               RAW + DIFF, RAW + DIFF + 'DIFF field=public_token left=a right=b\n'])
def test_complete_projection_uses_labels_and_derives_every_actual_difference(context, raw):
    value = parse(context, raw)
    assert value is not None and not value.replayed
    assert tuple(t.variable_id for t in value.traces) == context[2].variable_ids
    assert tuple(t.trace_id for t in value.traces) == ('trace:pi1', 'trace:pi2')
    assert [dict(t.observations) for t in value.traces] == [
        {'status': 'ok', 'public_token': 'a'}, {'status': 'leak', 'public_token': 'b'}]
    assert tuple(d.field for d in value.differences) == ('status', 'public_token')
    assert 'unsat' not in value.raw and 'engine log header' not in value.raw
    assert 'secret' not in value.raw
    checked = replay(context, value)
    assert checked.replayed and replay(context, checked).to_dict() == checked.to_dict()
    notes = ' '.join(checked.replay_notes).lower()
    assert 'structural' in notes and 'unvalidated' in notes
    witness = bundle(context, checked)
    assert not witness.authorizes_universal_proof
    assert witness.formula_id == context[0].formula.formula_id
    assert len(witness.differences) == 2 and len(witness.traces) == 2
    assert 'model' in witness.description.lower() and 'unvalidated' in witness.description.lower()


BAD_RAW = [
    pytest.param(RAW.replace('pi1:', 'unknown:', 1), id='unknown-label-no-ordinal-alias'),
    pytest.param(RAW.replace('pi1:', 'Pi1:', 1), id='case-sensitive-label'),
    pytest.param(RAW + LEFT, id='duplicate-label'),
    pytest.param(LEFT, id='missing-trace'),
    pytest.param(RAW.replace('  obs.status = ok\n', ''), id='missing-observation'),
    pytest.param(RAW.replace('  public.user_id = alice\n', '', 1), id='missing-low-input'),
    pytest.param(RAW.replace('  subject.task_id = task:1\n', '', 1), id='missing-subject'),
    pytest.param(RAW.replace('  obs.status = ok', '  obs.status = ok\n  obs.status = ok'), id='duplicate-observation'),
    pytest.param(RAW.replace('  obs.status = ok', '  obs.status = ok\n  status = ok'), id='duplicate-unprefixed-alias'),
    pytest.param(RAW.replace('  public.user_id = alice', '  public.user_id = alice\n  public.user_id = alice', 1), id='duplicate-low-input'),
    pytest.param(RAW + '  obs.secret = stolen\n', id='unknown-observation'),
    pytest.param(RAW + '  private.secret = stolen\n', id='private-input'),
    pytest.param(RAW + '  subject.extra = unapproved\n', id='unknown-subject'),
    pytest.param(RAW + 'garbage inside trace body\n', id='unsupported-body-line'),
    pytest.param(RAW.replace('obs.status = ok', 'obs.status = '), id='empty-value'),
    pytest.param(RAW.replace('TRACE pi1:', 'TRACE pi1'), id='malformed-header'),
    pytest.param(RAW + 'DIFF field=status left=ok\n', id='missing-diff-value'),
    pytest.param(RAW + 'DIFF field=status left=leak right=ok\n', id='reversed-diff'),
    pytest.param(RAW + 'DIFF field=status left=ok right=invented\n', id='forged-diff'),
    pytest.param(RAW + 'DIFF field=status left=ok right=ok\n', id='equal-diff'),
    pytest.param(RAW + 'DIFF field=unknown left=ok right=leak\n', id='unknown-diff-field'),
    pytest.param(RAW + DIFF + DIFF, id='duplicate-diff'),
    pytest.param(DIFF + RAW, id='diff-before-traces'),
    pytest.param(RAW + '\x00', id='nul'),
]


@pytest.mark.parametrize('raw', BAD_RAW)
def test_malformed_or_incomplete_native_projection_is_not_salvaged(context, raw):
    assert parse(context, raw) is None


@pytest.mark.parametrize('separator', ['\x01', '\x7f', '\x85', '\u2028', '\u2029', '\ud800'])
def test_non_native_controls_and_invalid_utf8_cannot_create_trace_boundaries(context, separator):
    assert parse(context, RAW.replace('\n', separator, 1)) is None


def test_crlf_native_records_have_same_projection_as_lf(context):
    assert parse(context, RAW.replace('\n', '\r\n')).to_dict() == parse(context).to_dict()


@pytest.mark.parametrize('raw', [
    LEFT + block('pi2', 'ok', 'a'),
    LEFT + block('pi2', 'leak', 'b', user='bob'),
    LEFT + block('pi2', 'leak', 'b', subject='task:2'),
])
def test_complete_but_non_counterexample_projection_cannot_emit_bundle(context, raw):
    parsed = parse(context, raw)
    assert parsed is not None
    if parsed.traces[0].observations == parsed.traces[1].observations:
        assert parsed.differences == ()
    checked = replay(context, replace(parsed, replayed=True, replay_notes=('trusted solver',)))
    assert not checked.replayed and 'trusted solver' not in checked.replay_notes
    with pytest.raises(hyper.HyperpropertyAdapterError):
        bundle(context, checked)


def test_empty_subject_policy_rejects_unapproved_subject_assignments():
    doc = document()
    mapping, order = hyper.ObservationMap.from_document(doc), hyper.QuantifierOrder.from_document(doc)
    assert hyper.parse_hyper_counterexample(TRACE + 'subject.task_id = task:1\n',
        formula_id=doc.formula.formula_id, observation_map=mapping, quantifier_order=order) is None


@pytest.mark.parametrize('cap', ['bytes', 'lines', 'fields', 'traces'])
def test_parser_limits_refuse_the_whole_projection_not_a_successful_prefix(context, monkeypatch, cap):
    constants = {'bytes': ('_MAX_COUNTEREXAMPLE_BYTES', len(RAW.encode()) - 1),
                 'lines': ('_MAX_COUNTEREXAMPLE_LINES', 2),
                 'fields': ('_MAX_COUNTEREXAMPLE_FIELDS', 1),
                 'traces': ('_MAX_COUNTEREXAMPLE_TRACES', 1)}
    name, limit = constants[cap]
    monkeypatch.setattr(hyper, name, limit)
    assert parse(context) is None


def mutate_counterexample(value, mutation):
    if mutation == 'formula':
        return replace(value, formula_id='formula:stale')
    if mutation == 'policy':
        return replace(value, observation_policy_id='policy:stale')
    if mutation == 'fields':
        return replace(value, observed_fields=('status',))
    if mutation == 'raw':
        return replace(value, raw=value.raw + 'obs.unknown = hidden\n')
    if mutation == 'no-raw':
        return replace(value, raw='')
    if mutation == 'diff-digest':
        return replace(value, differences=(replace(value.differences[0], left_digest='sha256:'+'0'*64),
                                            *value.differences[1:]))
    if mutation == 'missing-difference':
        return replace(value, differences=value.differences[:1])
    if mutation == 'trace-order':
        return replace(value, traces=tuple(reversed(value.traces)))
    changes = {'variable': {'variable_id': 'var:stale'},
               'trace-label': {'trace_id': 'trace:unbound'},
               'public-digest': {'public_inputs_digest': 'sha256:'+'0'*64},
               'observation-digest': {'observations_digest': 'sha256:'+'0'*64},
               'value': {'observations': {'status': 'invented', 'public_token': 'a'}},
               'missing-field': {'subject': {}}}
    return replace(value, traces=(replace(value.traces[0], **changes[mutation]), value.traces[1]))


TAMPERS = ('formula', 'policy', 'fields', 'raw', 'no-raw', 'diff-digest', 'missing-difference',
           'trace-order', 'variable', 'trace-label', 'public-digest', 'observation-digest',
           'value', 'missing-field')


@pytest.mark.parametrize('mutation', TAMPERS)
def test_claimed_replayed_flag_and_stale_notes_cannot_hide_tampered_evidence(context, mutation):
    valid = replay(context, parse(context))
    forged = replace(mutate_counterexample(valid, mutation), replayed=True,
                     replay_notes=('already independently proved',))
    checked = replay(context, forged)
    assert not checked.replayed and 'already independently proved' not in checked.replay_notes
    assert replay(context, checked).to_dict() == checked.to_dict()
    with pytest.raises(hyper.HyperpropertyAdapterError):
        bundle(context, forged)


@pytest.mark.parametrize('container', ['traces', 'differences', 'observed_fields'])
def test_forged_container_excess_refused_before_trace_normalization(context, monkeypatch, container):
    value = parse(context)
    extras = {'traces': value.traces + value.traces[:1],
              'differences': value.differences * 2,
              'observed_fields': ('status',) * 257}
    forged = replace(value, replayed=True, **{container: extras[container]})
    monkeypatch.setattr(hyper, 'parse_hyper_counterexample', forbidden)
    assert not replay(context, forged).replayed


@pytest.mark.parametrize('missing', ['formula_id', 'observation_map', 'quantifier_order'])
def test_bundle_requires_explicit_request_context_even_for_previously_checked_trace(context, missing):
    value = replay(context, parse(context))
    kwargs = dict(formula_id=context[0].formula.formula_id,
                  observation_map=context[1], quantifier_order=context[2])
    del kwargs[missing]
    with pytest.raises(hyper.HyperpropertyAdapterError):
        value.to_witness_bundle(**kwargs)


def test_replay_requires_expected_formula_instead_of_self_attested_formula(context):
    value = parse(context)
    assert not hyper.replay_hyper_counterexample(value, context[1], context[2]).replayed
    assert not replay(context, value, formula_id='formula:other').replayed


@pytest.mark.parametrize('signature', [('exists', 'forall'), ('forall', 'exists'),
                                       ('forall', 'forall', 'forall')])
def test_non_universal_pairs_or_longer_prefixes_are_not_structural_counterexamples(context, signature):
    doc, mapping, _ = context
    names = tuple('pi'+str(i+1) for i in range(len(signature)))
    ids = tuple('var:'+name for name in names)
    bindings = tuple(QuantifierBinding('bind:'+str(i), TraceQuantifier(quantifier), ids[i], i).to_dict()
                     for i, quantifier in enumerate(signature))
    order = hyper.QuantifierOrder(signature, ids, names, bindings)
    raw = RAW + (block('pi3', 'other', 'c') if len(names) == 3 else '')
    parsed = parse((doc, mapping, order), raw)
    assert parsed is not None and not replay((doc, mapping, order), parsed).replayed


@pytest.mark.parametrize('bad_context', ['duplicate-names', 'duplicate-ids', 'binding-index',
                                        'duplicate-observations', 'private-overlap'])
def test_inconsistent_context_cannot_enable_ordinal_binding(context, bad_context):
    doc, mapping, order = context
    if bad_context == 'duplicate-names':
        order = replace(order, variable_names=('pi1', 'pi1'))
    elif bad_context == 'duplicate-ids':
        order = replace(order, variable_ids=('var:pi1', 'var:pi1'))
    elif bad_context == 'binding-index':
        order = replace(order, bindings=({**order.bindings[0], 'index': 1}, order.bindings[1]))
    elif bad_context == 'duplicate-observations':
        mapping = replace(mapping, observation_fields=('status', 'status'))
    else:
        mapping = replace(mapping, high_input_fields=('status',))
    assert parse((doc, mapping, order)) is None


@pytest.mark.parametrize('engine', BACKENDS)
@pytest.mark.parametrize('route', ['direct', 'registry', 'v2'])
@pytest.mark.parametrize('valid', [True, False])
def test_default_routes_keep_engine_verdict_separate_from_structural_witness(private_admission, engine, route, valid):
    raw = TRACE if valid else TRACE.replace('obs.status = leak\n', '')
    private_admission.action[0] = lambda invocation, signal: process.RawProcessResult(
        returncode=0, stdout=VIOLATION[engine]+raw)
    req = request(engine)
    original = req.to_dict()
    if route == 'direct':
        outcome = BACKENDS[engine]().run(req)
        result = outcome.result
        assert outcome.request_digest == req.digest
        assert outcome.receipt.status is hyper.HyperCheckOutcomeStatus.VIOLATED
        assert (outcome.receipt.counterexample is not None) is valid
        witness = result.witness.to_dict()
        assert ('witness_bundle' in witness) is valid
    elif route == 'registry':
        attempt, projected = registry.default_backend_registry().run(req, backend_id=engine)
        assert attempt.status.value == 'succeeded' and projected.status.value == 'unknown'
        assert projected.request_digest == req.digest and projected.attempt_digest == attempt.digest
        assert not projected.is_theorem_proof
        assert projected.payload['result_status'] == 'violated'
        typed = projected.payload['result']
        assert ('witness_bundle' in typed['witness']) is valid
        result = None
    else:
        typed = typed_request(engine)
        before = typed.to_dict()
        outcome = v2.HyperExecutionEngineV2().execute(typed)
        result = outcome.backend_result
        assert typed.to_dict() == before
        assert outcome.disposition is v2.HyperDisposition.VIOLATED
        assert outcome.evidence.hyperproperty_established
        assert outcome.evidence.witness.replayed is valid
        assert (outcome.witness_status is v2.HyperWitnessStatus.COUNTEREXAMPLE_REPLAYED) is valid
        assert not outcome.evidence.authorizes_universal_proof
    if result is not None:
        assert result.status is ResultStatus.VIOLATED and result.authority is ResultAuthority.HYPERPROPERTY
        assert result.translation_ceiling is EvidenceAuthority.BOUNDED and result.bounds == req.bounds
        assert result.metadata['process']['workspace_cleaned']
    assert req.to_dict() == original
    assert len(private_admission.calls) == len(private_admission.acquired) == 1
    invocation, _, snapshot, _ = private_admission.calls[0]
    assert snapshot['allocated'] == {'cpu_slots': 2, 'memory_mb': 128}
    assert snapshot['allocated_child_process_slots'] == 4
    assert invocation.limits.resident_memory_bytes == 128*MIB
    assert private_admission.acquired[0].released
    assert not private_admission.prepared[0].exists()


@pytest.mark.parametrize('mutation', ['raw', 'policy', 'formula', 'diff-digest', 'public-digest'])
def test_v2_from_outcome_rechecks_actual_document_not_incoming_replayed_flag(context, mutation):
    forged = replace(mutate_counterexample(replay(context, parse(context)), mutation), replayed=True)
    binding = v2.HyperWitnessBindingV2.from_outcome(document=context[0],
        disposition=v2.HyperDisposition.VIOLATED, evidence_path=hyper.HyperEvidencePath.ENGINE,
        counterexample=forged, observation_policy_id=context[1].policy_id)
    assert not binding.replayed
    assert binding.status is v2.HyperWitnessStatus.COUNTEREXAMPLE_UNREPLAYABLE
    assert not binding.authorizes_universal_proof


def test_v2_from_outcome_revalidates_even_when_incoming_flag_is_false(context):
    binding = v2.HyperWitnessBindingV2.from_outcome(document=context[0],
        disposition=v2.HyperDisposition.VIOLATED, evidence_path=hyper.HyperEvidencePath.ENGINE,
        counterexample=parse(context), observation_policy_id=context[1].policy_id)
    assert binding.replayed and binding.status is v2.HyperWitnessStatus.COUNTEREXAMPLE_REPLAYED
    assert not binding.authorizes_universal_proof


@pytest.mark.parametrize('tamper', ['raw', 'document'])
def test_v2_result_constructor_refuses_self_attested_replay_against_actual_request(private_admission, tamper):
    private_admission.action[0] = lambda invocation, signal: process.RawProcessResult(
        returncode=0, stdout=VIOLATION['hyperltl']+TRACE)
    result = v2.HyperExecutionEngineV2().execute(typed_request('hyperltl'))
    assert result.evidence.witness.replayed
    with pytest.raises(v2.HyperExecutionError):
        if tamper == 'raw':
            payload = dict(result.evidence.witness.counterexample)
            payload['raw'] += 'obs.hidden = omitted\n'
            forged = replace(result.evidence.witness, counterexample=payload, replayed=True)
            replace(result, evidence=replace(result.evidence, witness=forged))
        else:
            doc = result.request.document
            changed = HyperpropertyIR.noninterference_document(
                policy=replace(doc.information_flow_policy, policy_id='policy:other'),
                bound=doc.self_composition_bound)
            replace(result, request=replace(result.request, document=changed))


def test_evaluator_fallback_preserves_its_separate_non_native_witness_path():
    doc = document()
    traces = tuple(ExecutionTrace(trace_id='execution:'+str(i), public_inputs={'user_id': 'alice'},
        private_inputs={'secret': str(i)}, observations={'status': status})
        for i, status in enumerate(('ok', 'leak')))
    backend = hyper.HyperLTLBackend(which=lambda name: None)
    outcome = backend.check(doc, traces=traces, allow_fallback=True)
    assert outcome.result.status is ResultStatus.VIOLATED
    assert outcome.receipt.evidence_path is hyper.HyperEvidencePath.BOUNDED_SELF_COMPOSITION
    assert not outcome.receipt.external_tool_proof and not outcome.receipt.authorizes_universal_proof
    assert outcome.receipt.counterexample.replayed and outcome.receipt.counterexample.raw == ''
    witness = outcome.result.witness.to_dict()
    assert witness['witness_bundle']['authorizes_universal_proof'] is False
    assert all(t['trace_id'].startswith('execution:') for t in witness['witness_bundle']['traces'])
