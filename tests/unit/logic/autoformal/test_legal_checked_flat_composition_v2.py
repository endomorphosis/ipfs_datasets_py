"""The structural veto must run before any formula can be emitted."""
from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.autoformal import legal_checked_flat_composition_v2 as checked
from ipfs_datasets_py.logic.autoformal import legal_rule_list_composition as composition


def example(text='Registry shall file.'):
    source = {'candidate_id': 'example', 'source_text': text,
              'source_sha256': composition.text_sha256(text)}
    plan = composition.prepare_source_plan(source, [{'clause_id': 'one', 'char_start': 0,
        'char_end': len(text), 'scope': deepcopy(composition.FLAT_SCOPE)}])
    rule = {'actor': 'Registry', 'modality': 'O', 'action': 'file', 'object': '',
            'conditions': [], 'exceptions': [], 'temporal': []}
    attachments = {field: [] for field in ('actor', 'action', 'object', 'conditions', 'exceptions', 'temporal')}
    for field in ('actor', 'action'):
        start = text.index(rule[field])
        attachments[field] = [{'char_start': start, 'char_end': start + len(rule[field])}]
    predictions = [{'clause_id': 'one', 'clause_source_sha256': source['source_sha256'],
        'rule': rule, 'attachments': attachments, 'scope': deepcopy(composition.FLAT_SCOPE)}]
    return source, plan, predictions


def invoke(source, plan, predictions):
    return checked.compose_checked_flat(source, plan, predictions,
        expected_plan_sha256=plan['plan_sha256'])


def test_accepted_rule_and_occurrence_ledger_are_unchanged():
    source, plan, predictions = example()
    report = invoke(source, plan, predictions)
    assert report['status'] == 'composed'
    expected = composition.compose_rule_list(plan, predictions, expected_plan_sha256=plan['plan_sha256'])
    assert report['composition'] == expected
    assert report['canonical_ir'] == expected['canonical_ir']
    assert checked.validate_checked_flat(report, source, plan, predictions,
        expected_plan_sha256=plan['plan_sha256'])


def test_nested_norm_is_deferred_before_composition(monkeypatch):
    source, plan, predictions = example('Registry shall file unless Board may archive.')
    def forbidden(*args, **kwargs):
        pytest.fail('a nested source reached the flat composer')
    monkeypatch.setattr(composition, 'compose_rule_list', forbidden)
    report = invoke(source, plan, predictions)
    assert report['status'] == 'deferred'
    assert report['composition'] is report['canonical_ir'] is None
    assert report['dependency_evidence']['allows_flat_composition'] is False


@pytest.mark.parametrize('field', ['qualified', 'admitted', 'proof_authority',
    'source_semantics_verified', 'independent_scope_verified', 'training_executed',
    'model_inference_executed'])
def test_repaired_hash_cannot_grant_authority(field):
    source, plan, predictions = example()
    report = invoke(source, plan, predictions)
    report[field] = True
    report['report_sha256'] = composition.digest({k: v for k, v in report.items() if k != 'report_sha256'})
    with pytest.raises(ValueError, match='authoritative regeneration'):
        checked.validate_checked_flat(report, source, plan, predictions,
            expected_plan_sha256=plan['plan_sha256'])


def test_dependency_check_never_receives_predictions(monkeypatch):
    source, plan, predictions = example()
    original = checked.dependencies.prepare_flat_scope_dependencies
    calls = []
    def capture(*args, **kwargs):
        assert len(args) == 2 and args[0] == source and args[1] == plan
        assert set(kwargs) == {'expected_plan_sha256'}
        calls.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(checked.dependencies, 'prepare_flat_scope_dependencies', capture)
    report = invoke(source, plan, predictions)
    assert calls and report['source_only_dependency_check']


def test_accepted_profile_still_rejects_missing_rule():
    source, plan, _ = example()
    with pytest.raises(ValueError, match='one-prediction-per-clause'):
        invoke(source, plan, [])


def test_exact_source_is_authoritative():
    source, plan, predictions = example()
    source['source_text'] = 'Council shall file.'
    source['source_sha256'] = composition.text_sha256(source['source_text'])
    with pytest.raises(ValueError):
        invoke(source, plan, predictions)


def test_external_plan_commitment_cannot_be_replaced():
    source, plan, predictions = example()
    with pytest.raises(ValueError):
        checked.compose_checked_flat(source, plan, predictions, expected_plan_sha256='0' * 64)


def test_reference_or_formula_fields_cannot_enter_source():
    source, plan, predictions = example()
    source['reference_ir'] = {'rules': []}
    with pytest.raises(ValueError):
        invoke(source, plan, predictions)


def test_inputs_are_not_mutated():
    source, plan, predictions = example()
    before = deepcopy((source, plan, predictions))
    invoke(source, plan, predictions)
    assert (source, plan, predictions) == before


@pytest.mark.parametrize('text,separator', [
    ('Registry shall file unless record duty [2]. Board may archive.', '. '),
    ('Registry shall file unless rEcOrD duty [2]. Board may archive.', '. '),
    ('Registry shall file notice; otherwise Board may archive.', '; '),
    ('Registry shall file notice. In that case Board may archive.', '. '),
    ('Registry shall file only if the permit is active.', None),
    ('Registry shall file provided however the permit is active.', None),
    ('Registry shall file unless lower caption. Board may archive.', '. '),
])
def test_v2_rejects_unclassified_scope_before_composition(text, separator, monkeypatch):
    source = {'candidate_id': 'v2-scope-probe', 'source_text': text,
              'source_sha256': composition.text_sha256(text)}
    cuts = [] if separator is None else [text.index(separator) + 1]
    clauses = []
    left = 0
    for ordinal, end in enumerate([*cuts, len(text)]):
        while text[left].isspace():
            left += 1
        clauses.append({'clause_id': str(ordinal), 'char_start': left, 'char_end': end,
                        'scope': deepcopy(composition.FLAT_SCOPE)})
        left = end
    plan = composition.prepare_source_plan(source, clauses)
    def forbidden(*args, **kwargs):
        pytest.fail('unclassified scope reached the flat composer')
    monkeypatch.setattr(composition, 'compose_rule_list', forbidden)
    report = invoke(source, plan, [])
    assert report['status'] == 'deferred'
    assert report['composition'] is report['canonical_ir'] is None


def test_numeric_alias_cannot_replace_boolean_authority():
    source, plan, predictions = example()
    report = invoke(source, plan, predictions)
    report['qualified'] = 0
    report['report_sha256'] = composition.digest({k: v for k, v in report.items() if k != 'report_sha256'})
    with pytest.raises(ValueError, match='authoritative regeneration'):
        checked.validate_checked_flat(report, source, plan, predictions,
            expected_plan_sha256=plan['plan_sha256'])
