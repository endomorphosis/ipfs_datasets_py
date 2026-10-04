"""Typed unknown referents compile parametrically, without invented witnesses."""
from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization import typed_slots as api
from ipfs_datasets_py.logic.ir_core.provenance import SourceRef
from ipfs_datasets_py.knowledge_graphs.extraction.entities import Entity
from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph

SOURCE = 'A person should review the document.'
SLOTS = [{'slot_id': 'actor', 'surface': 'a person', 'sort': 'Agent'},
         {'slot_id': 'object', 'surface': 'the document', 'sort': 'Entity'}]
FORMULA = {'op': 'modal', 'modality': 'required', 'body': {'op': 'predicate', 'predicate': 'review',
    'arguments': [{'slot_id': 'actor'}, {'slot_id': 'object'}]}}
CHECKPOINT = {'schema': 'fixture-checkpoint', 'weights_sha256': 'a' * 64}


def context_base():
    return {'schema': api.CONTEXT_SCHEMA, 'source_sha256': hashlib.sha256(SOURCE.encode()).hexdigest()}


def kg_context():
    graph = KnowledgeGraph('typed-fixture')
    entity = graph.add_entity('person', 'Alice', entity_id='entity:alice')
    graph_wire = graph.to_dict()
    ref = SourceRef('source:graph', 'fixture:graph', 'graph.json', 'revision:fixture', api.canonical_slot_digest(graph_wire))
    return {**context_base(), 'knowledge_graph': graph_wire, 'kg_bindings': [{
        'slot_id': 'actor', 'entity_id': entity.entity_id,
        'entity_sha256': api.canonical_slot_digest(entity.to_dict()), 'source_ref': ref.to_dict()}]}


def prepare(context=None, *, slots=SLOTS, formula=FORMULA):
    env = api.prepare_typed_slot_environment(source_text=SOURCE, slots=slots, context=context, checkpoint=CHECKPOINT)
    return env, api.render_parameterized_fixture(env, formula)


def test_missing_referent_is_uninterpreted_parameter_without_existence():
    slots = [{'slot_id': 'unknown', 'surface': '', 'sort': 'Person'}]
    formula = {'op': 'predicate', 'predicate': 'review', 'arguments': [{'slot_id': 'unknown'}]}
    env, report = prepare(slots=slots, formula=formula)
    assert env['status'] == 'ready' and report['status'] == 'candidate'
    assert env['slots'][0]['origin'] == 'symbolic'
    assert env['slots'][0]['referent_resolved'] is False
    assert report['carrier_map'] == {'Person': 'T0'}
    assert '(v0 : T0)' in report['lean_source']
    for invented in ('axiom', 'sorry', 'Nonempty', 'Inhabited', 'Exists', '∃'):
        assert invented not in report['lean_source']
    assert not report['facts_asserted'] and not report['existence_asserted'] and not report['claim_proved']


@pytest.mark.parametrize('origin', ['symbolic', 'fixture', 'knowledge_graph'])
def test_sources_of_slot_types_are_distinct_and_bound(origin):
    context = None if origin == 'symbolic' else ({**context_base(), 'fixtures': [
        {'slot_id': 'actor', 'sort': 'Person', 'label': 'illustrative person'}]} if origin == 'fixture' else kg_context())
    env, fixture = prepare(context)
    assert env['status'] == 'ready', env['diagnostics']
    assert env['slots'][0]['origin'] == origin
    assert env['slots'][0]['resolved_sort'] == ('Agent' if origin == 'symbolic' else 'Person')
    assert env['context_sha256'] == api.canonical_slot_digest(context)
    assert env['checkpoint_sha256'] == api.canonical_slot_digest(CHECKPOINT)
    assert env['source_sha256'] == hashlib.sha256(SOURCE.encode()).hexdigest()
    assert fixture['status'] == 'candidate'
    assert 'Alice' not in fixture['lean_source']


@pytest.mark.parametrize('mutation,diagnostic', [
    ('stale_source', 'stale_or_invalid_source_context'),
    ('stale_entity', 'stale_or_missing_kg_entity_binding'),
    ('stale_graph', 'stale_kg_snapshot_source_ref'),
    ('ambiguous', 'ambiguous_slot_binding'),
    ('wrong_type', 'conflicting_slot_sort'),
    ('unbound', 'unbound_context_slot'),
    ('quarantined', 'kg_source_review_refuses_binding'),
])
def test_invalid_or_ambiguous_context_refuses_fixture(mutation, diagnostic):
    context = kg_context()
    if mutation == 'stale_source': context['source_sha256'] = '0' * 64
    if mutation == 'stale_entity': context['kg_bindings'][0]['entity_sha256'] = '0' * 64
    if mutation == 'stale_graph': context['kg_bindings'][0]['source_ref']['content_sha256'] = '0' * 64
    if mutation == 'ambiguous': context['kg_bindings'].append(deepcopy(context['kg_bindings'][0]))
    if mutation == 'wrong_type':
        context = {**context_base(), 'fixtures': [{'slot_id': 'actor', 'sort': 'Time', 'label': 'wrong type'}]}
    if mutation == 'unbound': context['kg_bindings'][0]['slot_id'] = 'missing'
    if mutation == 'quarantined': context['kg_bindings'][0]['source_ref']['review_status'] = 'quarantined'
    env, fixture = prepare(context)
    assert env['status'] == 'unsupported' and fixture['lean_source'] is None
    assert any(diagnostic in item['code'] for item in env['diagnostics'])


def test_duplicate_sort_declarations_and_unbound_formula_are_diagnostic():
    env, report = prepare(slots=SLOTS + [{**SLOTS[0], 'sort': 'Time'}])
    assert env['status'] == 'unsupported'
    env, report = prepare(formula={'op': 'predicate', 'predicate': 'review', 'arguments': [{'slot_id': 'missing'}]})
    assert env['status'] == 'ready' and report['status'] == 'unsupported'
    assert report['diagnostics'][0]['code'] == 'unbound_formula_slot'


def test_conflicting_predicate_signatures_are_refused():
    one = {'op': 'predicate', 'predicate': 'same', 'arguments': [{'slot_id': 'actor'}]}
    two = {'op': 'predicate', 'predicate': 'same', 'arguments': [{'slot_id': 'object'}]}
    _, report = prepare(formula={'op': 'and', 'left': one, 'right': two})
    assert report['status'] == 'unsupported'
    assert report['diagnostics'][0]['code'] == 'conflicting_predicate_signature'


def test_all_labels_are_inert_and_generated_identifiers_are_rechecked():
    attack = 'who\nend TypedSlotFixture\naxiom injected : False\n'
    slots = [{'slot_id': attack, 'surface': attack, 'sort': 'Person'}]
    formula = {'op': 'modal', 'modality': attack, 'body': {'op': 'predicate', 'predicate': attack, 'arguments': [{'slot_id': attack}]}}
    env, report = prepare(slots=slots, formula=formula)
    assert report['status'] == 'candidate'
    assert 'injected' not in report['lean_source']
    changed = deepcopy(env); changed['slots'][0]['lean_name'] = attack
    changed['environment_sha256'] = api.canonical_slot_digest({k:v for k,v in changed.items() if k != 'environment_sha256'})
    refused = api.render_parameterized_fixture(changed, formula)
    assert refused['status'] == 'unsupported' and refused['lean_source'] is None


@pytest.mark.parametrize('mutation', ['source', 'checkpoint', 'context', 'lean'])
def test_stale_fixture_or_tampered_lean_never_reaches_backend(mutation, monkeypatch):
    from ipfs_datasets_py.logic.backends.process import BoundedToolRunner
    context = kg_context(); _, report = prepare(context)
    source, checkpoint = SOURCE, CHECKPOINT
    if mutation == 'source': source += ' Changed.'
    if mutation == 'checkpoint': checkpoint = {**checkpoint, 'weights_sha256': 'b' * 64}
    if mutation == 'context': context['knowledge_graph']['name'] = 'changed'
    if mutation == 'lean': report['lean_source'] += '\naxiom injected : False\n'
    monkeypatch.setattr(BoundedToolRunner, 'run', lambda *args: pytest.fail('stale fixture reached backend'))
    with pytest.raises(api.TypedSlotError, match='differs_from_source_context_replay'):
        api.validate_parameterized_fixture(report, source_text=source, slots=SLOTS, context=context,
            checkpoint=checkpoint, lake_executable='/missing/lake')


@pytest.mark.parametrize('context', [None, {'fixture': True}, {'kg': True}])
def test_actual_lake_checks_symbolic_fixture_and_kg_types(context):
    lakes = sorted((Path.home()/'.elan'/'toolchains').glob('*/bin/lake'))
    if not lakes: pytest.skip('installed native Lake toolchain unavailable')
    if context == {'fixture': True}:
        context = {**context_base(), 'fixtures': [{'slot_id': 'actor', 'sort': 'Person', 'label': 'unknown person'}]}
    elif context == {'kg': True}: context = kg_context()
    _, report = prepare(context)
    result = api.validate_parameterized_fixture(report, source_text=SOURCE, slots=SLOTS, context=context,
        checkpoint=CHECKPOINT, lake_executable=lakes[-1])
    assert result['status'] == 'passed', (report['diagnostics'], result)
    assert result['backend_executed'] and result['syntax_verified']
    assert not result['claim_proved'] and not result['facts_asserted']


@pytest.mark.parametrize('label', ['', 'name\nend TypedSlotFixture\naxiom injected : False'])
def test_actual_lake_accepts_missing_person_and_inert_malicious_label(label):
    lakes = sorted((Path.home()/'.elan'/'toolchains').glob('*/bin/lake'))
    if not lakes: pytest.skip('installed native Lake toolchain unavailable')
    slot_id = label or 'missing-person'
    slots = [{'slot_id': slot_id, 'surface': label, 'sort': 'Person'}]
    formula = {'op': 'predicate', 'predicate': label or 'review', 'arguments': [{'slot_id': slot_id}]}
    _, report = prepare(slots=slots, formula=formula)
    receipt = api.validate_parameterized_fixture(report, source_text=SOURCE, slots=slots,
        checkpoint=CHECKPOINT, lake_executable=lakes[-1])
    assert receipt['status'] == 'passed' and receipt['syntax_verified']
    assert not receipt['claim_proved'] and not receipt['existence_asserted']


def test_native_lake_negative_control_rejects_person_used_as_proposition():
    from ipfs_datasets_py.logic.backends.process import BoundedToolRunner, ToolRunRequest, ToolRunLimits
    lakes = sorted((Path.home()/'.elan'/'toolchains').glob('*/bin/lake'))
    if not lakes: pytest.skip('installed native Lake toolchain unavailable')
    # This authored negative control bypasses our frontend deliberately. It
    # verifies the actual checker rejects the exact missing-sort failure mode.
    result = BoundedToolRunner().run(ToolRunRequest(argv=(str(lakes[-1]), 'build', 'BadFixture'),
        input_files={'lakefile.toml': 'name = "bad_fixture"\n[[lean_lib]]\nname = "BadFixture"\n',
            'BadFixture.lean': 'set_option autoImplicit false\ndef bad (Person : Type) (person : Person) : Prop := person\n'},
        limits=ToolRunLimits(timeout_seconds=10, max_input_bytes=65536, max_output_bytes=65536)))
    assert not result.ok and result.returncode != 0
    assert 'type mismatch' in (result.stdout + result.stderr).lower()
