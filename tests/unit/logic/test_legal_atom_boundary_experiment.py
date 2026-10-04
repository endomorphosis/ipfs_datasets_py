"""Matched supported-only fitting and boundary retention without hidden guards."""
from copy import deepcopy

import pytest
from scripts.ops.legal_ir import run_legal_atom_boundary_experiment as runner


def train_rows():
    atoms = [{'candidate_id': f'atom-{i}', 'supported': True} for i in range(14)]
    pairs = [{'pair_id': f'pair-{i}', 'forward_id': atoms[2*i]['candidate_id'],
              'rotated_id': atoms[2*i+1]['candidate_id']} for i in range(7)]
    return ([{'candidate_id': f'replay-{i}', 'supported': True} for i in range(17)],
            [{'candidate_id': f'heading-{i}', 'supported': True} for i in range(19)], atoms, pairs)


def score(raw=12, exact=10, guard=20):
    return {'documents': 96, 'supported_documents': 48, 'unsupported_documents': 48,
            'raw_boundary_document_exact': raw, 'raw_supported_scope_correct': 47,
            'exact_supported_segmentation': exact, 'raw_unsupported_accepted': 30,
            'unsupported_accepted': guard}


def panels():
    return {'atom_new': score(), 'historical': score()}


def improved():
    result = panels()
    result['atom_new']['raw_boundary_document_exact'] += 1
    return result


def churn(scores, parents):
    result = {}
    for panel, value in scores.items():
        old = [f'g-{i:03d}' for i in range(parents[panel]['unsupported_accepted'])]
        new = [f'g-{i:03d}' for i in range(value['unsupported_accepted'])]
        result[panel] = {'parent_unsupported_ids': old, 'candidate_unsupported_ids': new,
                         'new_unsupported_ids': sorted(set(new)-set(old)),
                         'removed_unsupported_ids': sorted(set(old)-set(new))}
    return result


def gate(scores, parents, identity):
    return runner.gates(scores, parents, identity, churn(scores, parents))


def test_matched_supported_batches_reproduce_all_identities_and_rotation_pairs():
    left, middle, right, pairs = train_rows()
    a = list(runner.batch_schedule(left, middle, right, pairs))
    assert a == list(runner.batch_schedule(left, middle, right, pairs)) and len(a) == 400
    seen = [set(), set(), set(), set()]
    lookup = {p['pair_id']: p for p in pairs}
    for step, (rows, receipt) in enumerate(a, 1):
        assert receipt['steps'] == step and len(rows) == 12
        assert receipt['supported_count'] == 12 and receipt['unsupported_count'] == 0
        for key, subset in [('common_replay_ids', rows[:4]), ('heading_ids', rows[4:8]), ('atom_ids', rows[8:])]:
            assert receipt[key] == [r['candidate_id'] for r in subset]
        assert receipt['atom_ids'] == [lookup[i][k] for i in receipt['atom_pair_ids'] for k in ('forward_id','rotated_id')]
        for values,key in zip(seen,('common_replay_ids','heading_ids','atom_ids','atom_pair_ids')): values.update(receipt[key])
    assert seen == [{r['candidate_id'] for r in rows} for rows in (left,middle,right)] + [{p['pair_id'] for p in pairs}]


@pytest.mark.parametrize('steps', [0, 401, True, 1.5])
def test_budget_must_be_bounded_integer(steps):
    with pytest.raises(ValueError): next(runner.batch_schedule(*train_rows(), steps=steps))


@pytest.mark.parametrize('invalid', ['unsupported', 'duplicate', 'empty'])
def test_no_unsupported_zero_boundary_supervision_or_duplicate_training(invalid):
    left, right, atoms, pairs = train_rows()
    if invalid == 'unsupported': left[0]['supported'] = False
    elif invalid == 'duplicate': right[0]['candidate_id'] = left[0]['candidate_id']
    else: left = []
    with pytest.raises(ValueError): next(runner.batch_schedule(left, right, atoms, pairs))


def test_component_improvement_can_retain_nonzero_parent_guard_errors():
    assert gate(improved(), panels(), True) == {'eligible': True, 'failures': []}
    assert not gate(panels(), panels(), True)['eligible']


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
    assert not gate(candidate, panels(), identity)['eligible']


@pytest.mark.parametrize('key,value', [('documents', 95), ('raw_boundary_document_exact', True),
    ('raw_boundary_document_exact', 49), ('raw_unsupported_accepted', -1),
    ('exact_supported_segmentation', float('nan')), ('unsupported_accepted', 49)])
def test_malformed_metrics_fail_closed(key, value):
    candidate = improved(); candidate['atom_new'][key] = value
    with pytest.raises(ValueError): gate(candidate, panels(), True)


def test_missing_panel_or_count_cannot_pass():
    candidate = improved(); del candidate['historical']
    with pytest.raises(ValueError): gate(candidate, panels(), True)
    candidate = improved(); del candidate['atom_new']['raw_boundary_document_exact']
    with pytest.raises(ValueError): gate(candidate, panels(), True)


def stages(eligible=True):
    return [{'steps': n, 'eligible': eligible, 'metrics': improved()} for n in runner.STEPS]


def test_ranking_uses_complete_raw_boundaries_before_delivered_exactness():
    values = stages()
    values[1]['metrics']['atom_new']['raw_boundary_document_exact'] += 1
    values[2]['metrics']['atom_new']['exact_supported_segmentation'] += 2
    assert runner.select_stage(values)['steps'] == 200
    assert runner.select_stage(stages())['steps'] == 100
    assert runner.select_stage(stages(False)) is None
    with pytest.raises(ValueError): runner.select_stage(values[:-1])


def test_primary_ties_favor_control_and_preserve_fallback():
    trials = [{'name': arm, 'stages': stages(False), 'selected_steps': 0} for arm in runner.ARMS]
    assert runner.select_primary(trials) == 'parent'
    for trial in trials: trial.update(stages=stages(), selected_steps=100)
    assert runner.select_primary(trials) == 'continuation'
    trials[1]['stages'][0]['metrics']['atom_new']['raw_boundary_document_exact'] += 1
    assert runner.select_primary(trials) == 'atom_rehearsal'
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


def test_equal_guard_count_cannot_hide_newly_accepted_source():
    candidate, parent = improved(), panels()
    changes = churn(candidate, parent)
    changes['historical']['candidate_unsupported_ids'][0] = 'new-guard'
    changes['historical']['candidate_unsupported_ids'].sort()
    changes['historical']['new_unsupported_ids'] = ['new-guard']
    changes['historical']['removed_unsupported_ids'] = ['g-000']
    result = runner.gates(candidate, parent, True, changes)
    assert not result['eligible']
    assert 'historical:new_unsupported_sources_accepted' in result['failures']


@pytest.mark.parametrize('change', ['missing_panel', 'missing_ids', 'duplicates', 'false_empty_additions', 'wrong_count'])
def test_guard_identity_receipts_fail_closed(change):
    candidate, parent = improved(), panels(); changes = churn(candidate, parent)
    if change == 'missing_panel': del changes['historical']
    elif change == 'missing_ids': del changes['historical']['new_unsupported_ids']
    elif change == 'duplicates': changes['historical']['parent_unsupported_ids'].append('g-000')
    elif change == 'false_empty_additions':
        changes['historical']['candidate_unsupported_ids'].append('new-guard')
        changes['historical']['candidate_unsupported_ids'].sort()
    else: changes['historical']['parent_unsupported_ids'].pop()
    with pytest.raises(ValueError): runner.gates(candidate, parent, True, changes)


@pytest.mark.parametrize('change', ['duplicate_pair', 'missing_member', 'duplicate_member'])
def test_atom_pair_schedule_has_exact_disjoint_membership(change):
    replay, headings, atoms, pairs = train_rows()
    if change == 'duplicate_pair': pairs[-1]['pair_id'] = pairs[0]['pair_id']
    elif change == 'missing_member': pairs[0]['forward_id'] = 'missing'
    else: pairs[0]['rotated_id'] = pairs[0]['forward_id']
    with pytest.raises(ValueError): next(runner.batch_schedule(replay, headings, atoms, pairs))


def test_source_churn_uses_actual_unsupported_plan_decisions():
    source = 'Agency must file.'
    sha = runner.boundary.text_sha(source)
    reference = {'candidate_id':'a','source_sha256':sha,'source_text':source,'supported':False,'clauses':[]}
    parent = {'rows':[{'candidate_id':'a','source_sha256':sha,'status':'abstained'}]}
    candidate = {'rows':[{'candidate_id':'a','source_sha256':sha,'status':'segmented'}]}
    change = runner.source_churn(candidate,parent,[reference])
    assert change['parent_unsupported_ids'] == [] and change['candidate_unsupported_ids'] == ['a']
    assert change['new_unsupported_ids'] == ['a'] and change['removed_unsupported_ids'] == []
    bad = deepcopy(candidate); bad['rows'][0]['source_sha256'] = '0'*64
    with pytest.raises(ValueError): runner.source_churn(bad,parent,[reference])
