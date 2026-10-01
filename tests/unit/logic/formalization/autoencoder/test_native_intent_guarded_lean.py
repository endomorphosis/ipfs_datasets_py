"""Actual finite source joins, counterexamples, replay, Lean and SANY."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import subprocess

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import native_intent_guarded_lean as api
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lean_emitters as old
from ipfs_datasets_py.logic.intent_ir.schema import (IntentIRDocument, IntentKind, IntentStatement,
    StatementKind, IntentModality, IntentAction, IntentControlEdge, ControlEdgeKind, SourceRef)
from ipfs_datasets_py.logic.intent_ir.formalize.projection_contracts import source_ir_sha256

LAKE = Path('/home/barberb/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lake')
JAVA = Path('/home/barberb/.local/share/ipfs_datasets_py/theorem-provers/advisors/temurin-jdk/17.0.20+8/jdk/bin/java')
JAR = Path('/home/barberb/.local/share/ipfs_datasets_py/theorem-provers/tlc/1.8.0/tla2tools.jar')


def fixture(*, initial=(True,), outcomes=(True,)):
    ref = SourceRef('source', 'urn:authored:guarded-test', 'fixture', 'v1', content_sha256='a' * 64)
    statements = (
        IntentStatement('goal', StatementKind.GOAL, IntentModality.REQUIRED, 'Publish report.',
                        ('source',), 'publish', ('officer', 'report')),
        IntentStatement('pre', StatementKind.PRECONDITION, IntentModality.ASSERTED,
                        'Report ready.', ('source',), 'ready', ('report',)),
        IntentStatement('effect', StatementKind.EFFECT, IntentModality.ASSERTED,
                        'Report complete.', ('source',), 'complete', ('report',)))
    action = IntentAction('act', 'officer', 'publish', ('report',), ('source',),
                          precondition_ids=('pre',), effect_ids=('effect',))
    document = IntentIRDocument('guarded', 'Authored guarded test', IntentKind.PROCEDURE,
                               (ref,), statements, (action,), (), ('act',), ('act',))
    workflow = {'semantics': 'finite_guarded_state_flow', 'source_ir_sha256': source_ir_sha256(document),
        'evidence_ref': 'source', 'variables': [
            {'variable_id': 'ready', 'kind': 'boolean', 'domain': [False, True],
             'initial_values': list(initial), 'evidence_ref': 'source'},
            {'variable_id': 'complete', 'kind': 'boolean', 'domain': [False, True],
             'initial_values': [False], 'evidence_ref': 'source'}],
        'predicate_bindings': [{'statement_id': 'pre',
            'expression': {'op': 'eq', 'variable_id': 'ready', 'value': True}, 'evidence_ref': 'source'}],
        'action_updates': [{'action_id': 'act', 'outcomes': [
            {'values': {'complete': value}, 'evidence_ref': 'source'} for value in outcomes], 'evidence_ref': 'source'}],
        'retry_bounds': []}
    effects = {'schema': api.BINDING_SCHEMA, 'source_ir_sha256': source_ir_sha256(document),
        'bindings': [{'statement_id': 'effect', 'expression': {'op': 'eq', 'variable_id': 'complete', 'value': True},
                      'evidence_ref': 'source'}]}
    return document, {'state': {'max_steps': 10, 'workflow': workflow}}, effects


def prepare(parts=None):
    document, context, effects = parts or fixture()
    return api.prepare_guarded_payload(document, context, api.IntentEffectBindings.from_dict(effects))


def row(payload, kind='state'):
    family, profile = api.ROUTES[kind]
    return {'projection_id': api.PREFIX + kind + '/v1', 'logic_family': family,
            'profile': profile, 'payload': payload}


def rebind(document, context, effects):
    digest = source_ir_sha256(document)
    context['state']['workflow']['source_ir_sha256'] = effects['source_ir_sha256'] = digest
    return document, context, effects


@pytest.mark.parametrize('kind', api.KINDS)
def test_supported_routes_preserve_native_model_and_never_assert_goals(kind):
    payload = prepare()
    source, details = api.emit_projection(row(payload, kind))
    assert payload['ready_for_training'] and len(payload['effect_checks']) == 1
    assert all(payload[name] is False for name in ('admitted', 'roundtrip_ok', 'qualified',
        'source_semantics_verified', 'normative_compliance_verified', 'goals_asserted_true'))
    assert 'theorem action_case_0_checks' in source
    assert 'theorem complete_model_has_no_deadlock' in source
    assert 'def condition0' in source and 'update configuration1.values' in source
    assert bool(details['syntax_requirements']) == (kind == 'tla_plus')
    assert details['retained_native_records'] == payload['native_document']
    assert 'sorry' not in source and 'axiom' not in source
    assert payload['native_state']['metadata'] == payload['retained_normalization_provenance']['metadata']
    assert payload['normalized_state']['metadata'] == {}


@pytest.mark.parametrize('initial,unreachable', [((False, True), False), ((False,), True)])
def test_false_precondition_preserves_deadlock_and_unreachable_diagnostics(initial, unreachable):
    payload = prepare(fixture(initial=initial))
    assert not payload['ready_for_training'] and not payload['graph']['deadlock_free']
    assert payload['graph']['initial_valuation_count'] == len(initial)
    assert bool(payload['unreachable_actions']) == unreachable
    assert payload['graph']['deadlocks'][0]['reason'] == 'precondition_false'
    for kind in api.KINDS:
        with pytest.raises(old.UnsupportedNativeLean, match='deadlock_unreachable_action_or_false_effect'):
            api.emit_projection(row(payload, kind))


def test_every_nondeterministic_effect_outcome_is_retained_including_failure():
    payload = prepare(fixture(outcomes=(True, False)))
    assert len(payload['effect_checks']) == 2
    assert {check['passed'] for check in payload['effect_checks']} == {True, False}
    assert payload['graph']['deadlock_free'] and not payload['ready_for_training']
    assert not payload['unreachable_actions']
    with pytest.raises(old.UnsupportedNativeLean):
        api.emit_projection(row(payload))


@pytest.mark.parametrize('field', ['ready_for_training', 'native_state', 'normalized_state', 'graph',
    'effect_checks', 'producer_pins', 'retained_normalization_provenance', 'bounded_tla', 'predicate_bindings'])
def test_any_forged_derived_field_fails_complete_source_replay(field):
    payload = prepare()
    payload[field] = False if field == 'ready_for_training' else {}
    with pytest.raises((ValueError, old.UnsupportedNativeLean), match='replay_differs'):
        api.emit_projection(row(payload))


def test_immutable_binding_inputs_and_native_outputs_do_not_alias():
    document, context, effects = fixture()
    immutable = api.IntentEffectBindings.from_dict(effects)
    effects['bindings'][0]['expression']['value'] = False
    copy = immutable.to_dict(); copy['bindings'].clear()
    payload = api.prepare_guarded_payload(document, context, immutable)
    context['state']['workflow']['action_updates'].clear()
    assert payload['ready_for_training'] and immutable.to_dict()['bindings']
    assert payload['context']['state']['workflow']['action_updates']


@pytest.mark.parametrize('change', ['missing', 'extra', 'duplicate', 'source', 'evidence', 'variable', 'bool_int', 'unknown'])
def test_invalid_effect_interpretations_fail_closed(change):
    document, context, effects = fixture()
    item = effects['bindings'][0]
    if change == 'missing': effects['bindings'].clear()
    elif change == 'extra': effects['bindings'].append({**item, 'statement_id': 'goal'})
    elif change == 'duplicate': effects['bindings'].append(deepcopy(item))
    elif change == 'source': effects['source_ir_sha256'] = 'b' * 64
    elif change == 'evidence': item['evidence_ref'] = 'foreign'
    elif change == 'variable': item['expression']['variable_id'] = 'unknown'
    elif change == 'bool_int': item['expression']['value'] = 1
    else: item['expression']['discarded'] = True
    with pytest.raises(ValueError): prepare((document, context, effects))


@pytest.mark.parametrize('modality', [IntentModality.REQUIRED, IntentModality.PERMITTED])
def test_modal_effect_cannot_be_interpreted_as_state_truth(modality):
    document, context, effects = fixture()
    document = replace(document, statements=tuple(replace(s, modality=modality) if s.statement_id == 'effect' else s
                                                 for s in document.statements))
    with pytest.raises(ValueError, match='asserted native'):
        prepare(rebind(document, context, effects))


def test_same_native_predicate_and_arguments_require_consistent_truth_interpretation():
    document, context, effects = fixture()
    document = replace(document, statements=tuple(replace(s, predicate='ready') if s.statement_id == 'effect' else s
                                                 for s in document.statements))
    rebind(document, context, effects)
    with pytest.raises(ValueError, match='conflicting binding'):
        prepare((document, context, effects))
    effects['bindings'][0]['expression']['variable_id'] = 'ready'
    assert prepare((document, context, effects))['ready_for_training']


def test_ordered_arguments_are_distinct_source_atoms():
    document, context, effects = fixture()
    document = replace(document, statements=tuple(replace(s, predicate='relation', arguments=('a', 'b')
        if s.statement_id == 'pre' else ('b', 'a')) if s.statement_id in ('pre', 'effect') else s
        for s in document.statements))
    assert prepare(rebind(document, context, effects))['ready_for_training']


def test_empty_postconditions_cannot_earn_program_floor_credit():
    document, context, effects = fixture()
    document = replace(document, actions=(replace(document.actions[0], effect_ids=()),),
                       statements=tuple(s for s in document.statements if s.statement_id != 'effect'))
    effects['bindings'] = []
    payload = prepare(rebind(document, context, effects))
    _, details = api.emit_projection(row(payload, 'action_contract'))
    assert payload['ready_for_training'] and not details['capability_floor_eligible']


def test_complete_document_and_route_metadata_are_required():
    document, context, effects = fixture()
    wire = document.to_dict(); wire['discarded_semantics'] = True
    with pytest.raises(ValueError): prepare((wire, context, effects))
    target = row(prepare()); target['logic_family'] = 'temporal'
    with pytest.raises(old.UnsupportedNativeLean, match='route_family_profile'):
        api.emit_projection(target)
    with pytest.raises(NotImplementedError): api.emit_projection({'projection_id': 'other'})


def test_producer_drift_fails_before_modeling(monkeypatch):
    monkeypatch.setitem(api._PINS, api.__name__, '0' * 64)
    with pytest.raises(ValueError, match='producer drift'): prepare()


def retry_fixture():
    document, context, effects = fixture()
    second = replace(document.actions[0], action_id='finish', verb='archive')
    edges = (IntentControlEdge('exit', 'act', 'finish', ControlEdgeKind.NEXT, source_ref_ids=('source',)),
             IntentControlEdge('retry', 'act', 'act', ControlEdgeKind.RETRY, source_ref_ids=('source',)))
    document = replace(document, actions=(*document.actions, second), control_edges=edges,
                       terminal_action_ids=('finish',))
    workflow = context['state']['workflow']
    workflow['action_updates'].append({'action_id': 'finish', 'outcomes': [{'values': {}, 'evidence_ref': 'source'}],
                                        'evidence_ref': 'source'})
    workflow['retry_bounds'] = [{'edge_id': 'retry', 'max_traversals': 1, 'evidence_ref': 'source'}]
    return rebind(document, context, effects)


def test_bounded_retry_and_separate_routing_phases_are_preserved():
    payload = prepare(retry_fixture())
    assert payload['ready_for_training'] and payload['graph']['max_abstract_steps'] == 6
    assert max(c['retry_counts'].get('retry', 0) for c in payload['graph']['configurations']) == 1
    assert any(r['transition_kind'] == 'route' for r in payload['graph']['transitions'])
    source, _ = api.emit_projection(row(payload, 'workflow'))
    assert 'retryCount' in source and '< 1' in source and 'graph_case_' in source
    document, context, effects = retry_fixture(); context['state']['max_steps'] = 5
    with pytest.raises(Exception, match='step_budget_does_not_cover'):
        prepare((document, context, effects))


def lake_build(path, source):
    path.mkdir()
    (path / 'IntentIR.lean').write_text(source)
    (path / 'lakefile.toml').write_text('name = "guarded_fixture"\nversion = "0.1.0"\n[[lean_lib]]\nname = "IntentIR"\n')
    result = subprocess.run([str(LAKE), 'build', 'IntentIR'], cwd=path, capture_output=True, text=True, timeout=60)
    (path / 'build.log').write_text(result.stdout + result.stderr)
    return result


@pytest.mark.skipif(not LAKE.is_file(), reason='installed Lean4 Lake required; no download')
def test_real_lake_checks_guards_updates_retries_and_rejects_false_postcondition(tmp_path):
    source, _ = api.emit_projection(row(prepare(retry_fixture())))
    good = lake_build(tmp_path / 'positive', source)
    assert good.returncode == 0, good.stdout + good.stderr
    failed = prepare(fixture(outcomes=(True, False)))
    # Exercise the actual generated check beyond the public readiness guard.
    bad = lake_build(tmp_path / 'false-effect', api._lean_semantics(failed))
    assert bad.returncode != 0 and 'is false' in bad.stdout + bad.stderr
    false_pre = prepare(fixture(initial=(False, True)))
    deadlocked = lake_build(tmp_path / 'false-precondition', api._lean_semantics(false_pre))
    assert deadlocked.returncode != 0 and 'is false' in deadlocked.stdout + deadlocked.stderr


@pytest.mark.skipif(not JAVA.is_file() or not JAR.is_file(), reason='local Java17 and SANY required; no download')
def test_real_sany_parses_exact_guarded_bounded_tla_without_modelchecking_claim():
    _, details = api.emit_projection(row(prepare(retry_fixture()), 'tla_plus'))
    receipt = api.tla.check_sany(details['syntax_requirements'][0], java_executable=JAVA, tla2tools_jar=JAR)
    assert receipt['status'] == 'passed', receipt
    assert receipt['level_checking_enabled'] and not receipt['model_checker_executed'] and not receipt['admitted']
