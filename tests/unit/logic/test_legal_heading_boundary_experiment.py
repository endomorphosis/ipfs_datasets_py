"""Matched supported-only fitting and boundary retention without hidden guards."""
from copy import deepcopy

import pytest
from scripts.ops.legal_ir import run_legal_heading_boundary_experiment as runner


def train_rows():
    return ([{'candidate_id': f'replay-{i}', 'supported': True} for i in range(17)],
            [{'candidate_id': f'heading-{i}', 'supported': True} for i in range(19)])


def score(raw=12, exact=10, guard=20):
    return {'documents': 96, 'supported_documents': 48, 'unsupported_documents': 48,
            'raw_boundary_document_exact': raw, 'raw_supported_scope_correct': 47,
            'exact_supported_segmentation': exact, 'raw_unsupported_accepted': 30,
            'unsupported_accepted': guard}


def panels():
    return {'heading_new': score(), 'historical': score()}


def improved():
    result = panels()
    result['heading_new']['raw_boundary_document_exact'] += 1
    return result


def test_matched_supported_batches_reproduce_all_identities_and_wrap():
    left, right = train_rows()
    a = list(runner.batch_schedule(left, right))
    assert a == list(runner.batch_schedule(left, right)) and len(a) == 400
    seen_left, seen_right = set(), set()
    for step, (rows, receipt) in enumerate(a, 1):
        assert receipt['steps'] == step and len(rows) == 12
        assert receipt['supported_count'] == 12 and receipt['unsupported_count'] == 0
        assert receipt['common_replay_ids'] == [r['candidate_id'] for r in rows[:6]]
        assert receipt['extra_ids'] == [r['candidate_id'] for r in rows[6:]]
        seen_left.update(receipt['common_replay_ids']); seen_right.update(receipt['extra_ids'])
    assert seen_left == {r['candidate_id'] for r in left}
    assert seen_right == {r['candidate_id'] for r in right}


@pytest.mark.parametrize('steps', [0, 401, True, 1.5])
def test_budget_must_be_bounded_integer(steps):
    with pytest.raises(ValueError): next(runner.batch_schedule(*train_rows(), steps=steps))


@pytest.mark.parametrize('invalid', ['unsupported', 'duplicate', 'empty'])
def test_no_unsupported_zero_boundary_supervision_or_duplicate_training(invalid):
    left, right = train_rows()
    if invalid == 'unsupported': left[0]['supported'] = False
    elif invalid == 'duplicate': right[0]['candidate_id'] = left[0]['candidate_id']
    else: left = []
    with pytest.raises(ValueError): next(runner.batch_schedule(left, right))


def test_component_improvement_can_retain_nonzero_parent_guard_errors():
    assert runner.gates(improved(), panels(), True) == {'eligible': True, 'failures': []}
    assert not runner.gates(panels(), panels(), True)['eligible']


@pytest.mark.parametrize('change', ['raw', 'delivered', 'guard', 'raw_guard', 'raw_support', 'scope', 'reject_all'])
def test_each_boundary_and_guard_regression_blocks_selection(change):
    candidate = improved(); identity = True
    if change == 'raw': candidate['historical']['raw_boundary_document_exact'] -= 1
    elif change == 'delivered': candidate['historical']['exact_supported_segmentation'] -= 1
    elif change == 'guard': candidate['historical']['unsupported_accepted'] += 1
    elif change == 'raw_guard': candidate['historical']['raw_unsupported_accepted'] -= 1
    elif change == 'raw_support': candidate['historical']['raw_supported_scope_correct'] -= 1
    elif change == 'reject_all': candidate['historical']['exact_supported_segmentation'] = 0
    else: identity = False
    assert not runner.gates(candidate, panels(), identity)['eligible']


@pytest.mark.parametrize('key,value', [('documents', 95), ('raw_boundary_document_exact', True),
    ('raw_boundary_document_exact', 49), ('raw_unsupported_accepted', -1),
    ('exact_supported_segmentation', float('nan')), ('unsupported_accepted', 49)])
def test_malformed_metrics_fail_closed(key, value):
    candidate = improved(); candidate['heading_new'][key] = value
    with pytest.raises(ValueError): runner.gates(candidate, panels(), True)


def test_missing_panel_or_count_cannot_pass():
    candidate = improved(); del candidate['historical']
    with pytest.raises(ValueError): runner.gates(candidate, panels(), True)
    candidate = improved(); del candidate['heading_new']['raw_boundary_document_exact']
    with pytest.raises(ValueError): runner.gates(candidate, panels(), True)


def stages(eligible=True):
    return [{'steps': n, 'eligible': eligible, 'metrics': improved()} for n in runner.STEPS]


def test_ranking_uses_complete_raw_boundaries_before_delivered_exactness():
    values = stages()
    values[1]['metrics']['heading_new']['raw_boundary_document_exact'] += 1
    values[2]['metrics']['heading_new']['exact_supported_segmentation'] += 2
    assert runner.select_stage(values)['steps'] == 200
    assert runner.select_stage(stages())['steps'] == 100
    assert runner.select_stage(stages(False)) is None
    with pytest.raises(ValueError): runner.select_stage(values[:-1])


def test_primary_ties_favor_control_and_preserve_fallback():
    trials = [{'name': arm, 'stages': stages(False), 'selected_steps': 0} for arm in runner.ARMS]
    assert runner.select_primary(trials) == 'parent'
    for trial in trials: trial.update(stages=stages(), selected_steps=100)
    assert runner.select_primary(trials) == 'control'
    trials[1]['stages'][0]['metrics']['heading_new']['raw_boundary_document_exact'] += 1
    assert runner.select_primary(trials) == 'rehearsal'
    trials[1]['selected_steps'] = 400
    with pytest.raises(ValueError): runner.select_primary(trials)
    with pytest.raises(ValueError): runner.select_primary(trials[:1])


@pytest.mark.parametrize('field', ['scope_logits', 'scope_supported_probability', 'raw_learned_scope_supported', 'candidate_id'])
def test_raw_scope_invariance_does_not_hide_behind_abstention(field):
    generation = {'rows': [{'candidate_id': 'a', 'source_sha256': 'b'*64,
        'scope_logits': [0.2, 0.3], 'scope_supported_probability': 0.525,
        'raw_learned_scope_supported': True, 'status': 'abstained'}]}
    assert runner.assert_raw_scope_identity(generation, deepcopy(generation))
    candidate = deepcopy(generation)
    candidate['rows'][0][field] = {'scope_logits': [0.2, 0.4], 'scope_supported_probability': 0.55,
                                  'raw_learned_scope_supported': False, 'candidate_id': 'other'}[field]
    with pytest.raises(ValueError): runner.assert_raw_scope_identity(candidate, generation)
