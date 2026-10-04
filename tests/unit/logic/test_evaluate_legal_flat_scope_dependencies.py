"""Saved-output veto invariants, independent of model inference and labels."""
from copy import deepcopy
import json

import pytest

from scripts.ops.legal_ir import evaluate_legal_flat_scope_dependencies as q


def fixture(text='Registry shall file.', identity='example', supported=True):
    source = {'candidate_id': identity, 'source_text': text, 'source_sha256': q.composition.text_sha256(text)}
    plan = q.composition.prepare_source_plan(source, [{'clause_id': 'clause', 'char_start': 0,
        'char_end': len(text), 'scope': deepcopy(q.composition.FLAT_SCOPE)}])
    rule = {'actor': 'Registry', 'action': 'file', 'object': '', 'modality': 'O',
            'conditions': [], 'exceptions': [], 'temporal': []}
    attachments = {f: [] for f in q.composition.SPAN_FIELDS}
    for field in ('actor', 'action'):
        start = text.index(rule[field]); attachments[field] = [{'char_start': start, 'char_end': start+len(rule[field])}]
    predictions = [{'clause_id': 'clause', 'clause_source_sha256': source['source_sha256'], 'rule': rule,
                    'attachments': attachments, 'scope': deepcopy(q.composition.FLAT_SCOPE)}]
    value = q.composition.compose_rule_list(plan, predictions, expected_plan_sha256=plan['plan_sha256'])
    row = {'candidate_id': identity, 'source_sha256': source['source_sha256'], 'status': 'composed',
           'reason': None, 'segmentation_status': 'segmented', 'composition': value,
           'clause_generation': {'secret_raw_predictions': True}}
    target = {**source, 'supported': supported, 'clauses': [{'char_start': 0, 'char_end': len(text), 'rule': rule}] if supported else []}
    return source, {'rows': [row]}, target


def apply(generation, source, cache=None, evidence=None):
    return q.filter_saved(generation, [source], {} if cache is None else cache, {} if evidence is None else evidence)


def test_positive_nonvacuous_unchanged_canonical_and_occurrences():
    source, generation, target = fixture()
    actual, counts = apply(generation, source)
    assert actual['rows'][0]['composition'] == generation['rows'][0]['composition']
    assert counts == {'wrapper_calls': 1, 'wrapper_cache_aliases': 0}
    assert actual['rows'][0]['clause_generation'] is None
    change = q.compare(q.score(generation, [source], [target]), q.score(actual, [source], [target]))
    assert change['after']['exact'] == change['supported_coverage_after'] == 1
    assert not change['all_reject_after']


def test_nested_veto_has_no_emitted_formula_and_reference_denominator_retained():
    source, generation, target = fixture('Registry shall file unless Board may archive.', supported=False)
    actual, _ = apply(generation, source)
    row = actual['rows'][0]
    assert row['composition'] is row['clause_generation'] is None
    assert 'canonical_ir' not in row and 'formal_outputs' not in row
    change = q.compare(q.score(generation, [source], [target]), q.score(actual, [source], [target]))
    assert change['before']['unsupported_accepted'] == 1 and change['after']['unsupported_accepted'] == 0
    assert change['unsupported_acceptance_removed_ids'] == ['example']
    assert change['after']['count'] == 1 and change['all_reject_after']


def test_conservative_false_rejection_is_scored_as_exact_loss():
    source, generation, target = fixture('Registry shall file pursuant to section 2.', supported=True)
    filtered, _ = apply(generation, source)
    change = q.compare(q.score(generation, [source], [target]), q.score(filtered, [source], [target]))
    assert change['supported_exact_lost_ids'] == change['supported_acceptance_lost_ids'] == ['example']
    assert change['after']['supported'] == 1 and change['after']['exact'] == 0


def test_cache_binds_exact_predictions_and_plan_not_reference_label():
    source, generation, target = fixture(); cache = {}; evidence = {}
    first, counts = apply(generation, source, cache, evidence)
    second, aliases = apply(generation, source, cache, evidence)
    assert first == second and aliases['wrapper_calls'] == 0 and aliases['wrapper_cache_aliases'] == 1
    changed = deepcopy(generation); value = changed['rows'][0]['composition']
    value['clause_predictions'][0]['rule']['modality'] = 'P'
    changed['rows'][0]['composition'] = q.composition.compose_rule_list(value['source_plan'], value['clause_predictions'], expected_plan_sha256=value['source_plan_sha256'])
    third, counts = apply(changed, source, cache, evidence)
    assert counts['wrapper_calls'] == 1 and len(evidence) == 1 and len(cache) == 2
    assert third['rows'][0]['composition']['source_rule_list'][0]['modality'] == 'P'


def test_guard_receives_source_and_plan_only(monkeypatch):
    source, generation, _ = fixture(); original = q.checked.compose_checked_flat; seen = []
    def wrapper(src, plan, predictions, **kwargs):
        assert set(src) == {'candidate_id', 'source_text', 'source_sha256'}
        assert set(kwargs) == {'expected_plan_sha256'}
        seen.append(True); return original(src, plan, predictions, **kwargs)
    monkeypatch.setattr(q.checked, 'compose_checked_flat', wrapper)
    apply(generation, source); assert seen == [True]


def test_actual_nested_guard_prepare_count_matches_declared_accounting(monkeypatch):
    source, generation, _ = fixture(); calls = {'v1': 0, 'v2': 0}
    for name, module in (('v1', q.checked.dependencies.base), ('v2', q.checked.dependencies)):
        original = module.prepare_flat_scope_dependencies
        def capture(src, plan, *, expected_plan_sha256, _original=original, _name=name, **kwargs):
            assert set(src) == {'candidate_id', 'source_text', 'source_sha256'}
            calls[_name] += 1
            return _original(src, plan, expected_plan_sha256=expected_plan_sha256, **kwargs)
        monkeypatch.setattr(module, 'prepare_flat_scope_dependencies', capture)
    _, counts = apply(generation, source)
    assert counts['wrapper_calls'] == 1 and calls == {'v1': 2, 'v2': 2}


def test_v2_necessary_condition_remains_vetoed_without_formula_rewrite():
    source, generation, _ = fixture('Registry shall file only if application is complete.')
    filtered, _ = apply(generation, source)
    assert filtered['rows'][0]['composition'] is None
    assert 'unclassified_necessary_condition_cue' in filtered['rows'][0]['dependency_reasons']


def test_upstream_abstention_never_creates_a_guard_success(monkeypatch):
    source, generation, target = fixture()
    generation['rows'][0].update(status='abstained', composition=None, reason='span_overlap')
    monkeypatch.setattr(q.checked, 'compose_checked_flat', lambda *a, **k: pytest.fail('abstention reached composer'))
    actual, counts = apply(generation, source)
    assert counts['wrapper_calls'] == 0 and actual['rows'][0]['dependency_evidence_key'] is None
    assert q.score(actual, [source], [target])['metrics']['exact'] == 0


@pytest.mark.parametrize('field', ['canonical_ir', 'occurrences', 'source_rule_list', 'canonical_to_source_ordinal'])
def test_repaired_composition_hash_cannot_hide_corruption(field):
    source, generation, _ = fixture(); value = generation['rows'][0]['composition']
    value[field] = []
    value['composition_sha256'] = q.composition.digest({k: v for k, v in value.items() if k != 'composition_sha256'})
    with pytest.raises(ValueError, match='saved canonical'):
        apply(generation, source)


@pytest.mark.parametrize('kind', ['prediction_hash', 'target_text', 'target_hash', 'duplicate_prediction', 'duplicate_reference', 'missing_prediction'])
def test_complete_source_reference_identity_required(kind):
    source, generation, target = fixture(); targets = [target]
    if kind == 'prediction_hash': generation['rows'][0]['source_sha256'] = '0'*64
    if kind == 'target_text': target['source_text'] += ' '
    if kind == 'target_hash': target['source_sha256'] = '0'*64
    if kind == 'duplicate_prediction': generation['rows'] *= 2
    if kind == 'duplicate_reference': targets *= 2
    if kind == 'missing_prediction': generation['rows'] = []
    with pytest.raises(ValueError): q.score(generation, [source], targets)


def test_historical_before_counts_and_memberships_must_match():
    source, generation, target = fixture(); measured = q.score(generation, [source], [target])
    expected = {**measured['metrics'], 'rows': measured['rows'], 'joint_exact': 1,
                'supported_ids': ['example'], 'unsupported_ids': [], 'joint_exact_ids': ['example']}
    q.check_historical_score(measured, expected)
    expected['joint_exact_ids'] = ['wrong']
    with pytest.raises(ValueError, match='membership'): q.check_historical_score(measured, expected)


@pytest.mark.parametrize('field', ['exact', 'composed', 'supported', 'count'])
def test_historical_count_corruption_rejected(field):
    source, generation, target = fixture(); measured = q.score(generation, [source], [target])
    expected = deepcopy(measured['metrics']); expected[field] += 1
    with pytest.raises(ValueError, match='historical count'): q.check_historical_score(measured, expected)


def test_veto_must_never_create_acceptance_or_improve_exactness():
    source, generation, target = fixture(); after = q.score(generation, [source], [target])
    before = deepcopy(after); before['rows'][0].update(composed=False, exact=False)
    with pytest.raises(ValueError, match='created acceptance'): q.compare(before, after)


@pytest.mark.parametrize('field', ['payload_sha256', 'source_sha256', 'target_sha256'])
def test_alias_key_binds_prediction_source_and_reference(field):
    a = {'payload_sha256': 'a', 'source_sha256': 'b', 'target_sha256': 'c'}
    b = dict(a); b[field] += 'x'
    assert q.job_identity(a) != q.job_identity(b)


def test_file_mutation_is_rejected(tmp_path):
    path = tmp_path/'saved.json'; path.write_text('{}'); pin = q.ref(path)
    path.write_text('{"changed":true}')
    with pytest.raises(ValueError, match='authenticated'): q.read_ref(pin)


def test_sample_is_source_only_sorted_and_bounded(monkeypatch):
    triples = [fixture(identity=i) for i in ('c', 'a', 'b')]; visited = []
    def selector(records, sources, **kwargs):
        identity = sources[0]['candidate_id']; visited.append(identity)
        return {'rows': [{'candidate': sources[0], 'interpretation': {}}], 'excluded': []}
    monkeypatch.setattr(q.previous, 'document_selection', selector)
    result = q.sampled_native([g['rows'][0] for s,g,t in triples], [s for s,g,t in triples], toolchain='test')
    assert visited == ['a', 'b'] and len(result['rows']) == 2
    assert result['accepted_count'] == result['source_count'] == 3
    assert result['reference_metrics_used_for_selection'] is False


def test_native_batches_separate_same_id_different_formulas():
    entries = [{'candidate': {'candidate_id': x}, 'interpretation': {'n': i}} for i,x in enumerate(('a','a','b','b'))]
    batches = q.native_batches(entries)
    assert len(batches) == 2 and sum(map(len,batches)) == 4
    assert all(len({e['candidate']['candidate_id'] for e in b}) == len(b) for b in batches)


def test_repeated_rule_occurrences_are_never_deduplicated():
    text = 'Registry shall file. Registry shall file.'
    source = {'candidate_id': 'repeat', 'source_text': text, 'source_sha256': q.composition.text_sha256(text)}
    _, first, target = fixture(); prototype = first['rows'][0]['composition']['clause_predictions'][0]
    split = text.index('Registry', 1); spans = [(0,split-1),(split,len(text))]
    plan = q.composition.prepare_source_plan(source, [{'clause_id': str(i), 'char_start': a, 'char_end': b,
        'scope': deepcopy(q.composition.FLAT_SCOPE)} for i,(a,b) in enumerate(spans)])
    predictions=[]
    for i,clause in enumerate(plan['clauses']):
        item=deepcopy(prototype); item.update(clause_id=str(i),clause_source_sha256=clause['source_sha256'])
        for coords in item['attachments'].values():
            for point in coords:
                point['char_start']+=clause['char_start'];point['char_end']+=clause['char_start']
        predictions.append(item)
    value=q.composition.compose_rule_list(plan,predictions,expected_plan_sha256=plan['plan_sha256'])
    generation={'rows':[{**first['rows'][0], 'candidate_id':'repeat','source_sha256':source['source_sha256'],'composition':value}]}
    filtered,_=apply(generation,source)
    assert filtered['rows'][0]['composition']==value and len(value['occurrences'])==2
