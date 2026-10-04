"""Matched exposure, fail-closed scope gates and loss accounting."""
from copy import deepcopy
import math

import pytest
from scripts.ops.legal_ir import run_legal_scope_preservation_experiment as runner


@pytest.fixture(scope='module')
def training():
    rows, pairs = [], []
    for i in range(12):
        pair_rows, pair, _ = runner.corpus.make_pair('tuning', i)
        rows.extend(pair_rows); pairs.append(pair)
    replay = deepcopy(rows)
    for row in replay: row['candidate_id'] = 'replay-' + row['candidate_id']
    return replay, rows, pairs


def score(supported=48, exact=36, raw_guard=0, accepted=0):
    return {'documents': 96, 'supported_documents': 48, 'unsupported_documents': 48,
            'raw_supported_scope_correct': supported, 'exact_supported_segmentation': exact,
            'raw_unsupported_accepted': raw_guard, 'unsupported_accepted': accepted}


def test_identical_schedule_balanced_pairs_complete_exposure_and_wrap(training):
    a = list(runner.batch_schedule(*training)); b = list(runner.batch_schedule(*training))
    assert a == b and len(a) == 400
    observed_replay, observed_extra, observed_pairs = set(), set(), set()
    for step, (rows, receipt) in enumerate(a, 1):
        assert receipt['steps'] == step and len(rows) == 12
        assert receipt['supported_count'] + receipt['unsupported_count'] == 12
        assert sum(r['supported'] for r in rows[6:]) == 3
        assert [r['candidate_id'] for r in rows[:6]] == receipt['common_replay_ids']
        assert [r['candidate_id'] for r in rows[6:]] == receipt['extra_ids']
        observed_replay.update(receipt['common_replay_ids'])
        observed_extra.update(receipt['extra_ids']); observed_pairs.update(receipt['pair_ids'])
    assert observed_replay == {r['candidate_id'] for r in training[0]}
    assert observed_extra == {r['candidate_id'] for r in training[1]}
    assert observed_pairs == {r['pair_id'] for r in training[2]}


@pytest.mark.parametrize('steps', [0, 401, True, 3.5])
def test_unplanned_budgets_rejected(training, steps):
    with pytest.raises(ValueError): next(runner.batch_schedule(*training, steps=steps))


@pytest.mark.parametrize('change', ['raw_guard', 'final_guard', 'supported', 'segmentation', 'token', 'all_reject'])
def test_gates_do_not_hide_scope_errors(change):
    parent = {'scope_new': score(), 'old': score()}; candidate = deepcopy(parent); identity = True
    if change == 'raw_guard': candidate['old']['raw_unsupported_accepted'] = 1
    elif change == 'final_guard': candidate['old']['unsupported_accepted'] = 1
    elif change == 'supported': candidate['old']['raw_supported_scope_correct'] -= 1
    elif change == 'segmentation': candidate['old']['exact_supported_segmentation'] -= 1
    elif change == 'all_reject': candidate['old'] = score(supported=0, exact=0)
    else: identity = False
    assert not runner.gates(candidate, parent, identity)['eligible']


@pytest.mark.parametrize('key,value', [('documents',95),('raw_supported_scope_correct',True),
    ('raw_unsupported_accepted',-1),('exact_supported_segmentation',49),
    ('unsupported_accepted',49),('raw_supported_scope_correct',float('nan'))])
def test_malformed_metrics_rejected(key, value):
    parent = {'scope_new': score()}; candidate = deepcopy(parent); candidate['scope_new'][key] = value
    with pytest.raises(ValueError): runner.gates(candidate, parent, True)


def test_missing_historical_panel_or_metric_rejected():
    parent = {'scope_new': score(), 'old': score()}
    with pytest.raises(ValueError): runner.gates({'scope_new': score()}, parent, True)
    candidate = deepcopy(parent); del candidate['old']['unsupported_accepted']
    with pytest.raises(ValueError): runner.gates(candidate, parent, True)


def test_guard_repair_without_supported_regression_passes():
    assert runner.gates({'scope_new': score()}, {'scope_new': score(raw_guard=10)}, True)['eligible']


def stages(eligible=True):
    return [{'steps': n, 'eligible': eligible, 'metrics': {'scope_new': score(), 'old': score()}} for n in runner.STEPS]


def test_stage_ranking_fallback_and_earlier_update_tie():
    assert runner.select_stage(stages(False)) is None
    assert runner.select_stage(stages())['steps'] == 100
    values = stages(); values[-1]['metrics']['scope_new']['exact_supported_segmentation'] += 1
    assert runner.select_stage(values)['steps'] == 400
    with pytest.raises(ValueError): runner.select_stage(values[:-1])


def test_primary_is_fixed_rank_with_control_tie_and_honest_fallback():
    trials = [{'name': arm, 'stages': stages(False), 'selected_steps': 0} for arm in runner.ARMS]
    assert runner.select_primary(trials) == 'parent'
    for t in trials: t.update(stages=stages(), selected_steps=100)
    assert runner.select_primary(trials) == 'control'
    trials[1]['stages'][0]['metrics']['scope_new']['exact_supported_segmentation'] += 1
    assert runner.select_primary(trials) == 'freeze_readout'
    trials[1]['selected_steps'] = 400
    with pytest.raises(ValueError): runner.select_primary(trials)


@pytest.mark.parametrize('labels', [[0,0,0,1],[1,1,1,0],[0,0,0,0],[1,1,1,1]])
def test_weighted_loss_denominator_is_class_weight_sum(labels):
    torch = pytest.importorskip('torch')
    logits = torch.tensor([[.7,-.2],[-1.,.3],[2.,-.4],[.1,1.1]], dtype=torch.float64, requires_grad=True)
    target = torch.tensor(labels)
    receipt = runner.class_loss_receipt(torch, logits, target)
    expected = sum((3 if y == 0 else 1) * (math.log(math.exp(float(x[0])) + math.exp(float(x[1]))) - float(x[y]))
                   for x,y in zip(logits.detach(), labels)) / sum(3 if y == 0 else 1 for y in labels)
    actual = (3*receipt['unsupported_nll_sum'] + receipt['supported_nll_sum']) / receipt['weighted_denominator']
    assert actual == pytest.approx(expected, abs=1e-12)
    assert receipt['weighted_denominator'] == sum(3 if y == 0 else 1 for y in labels)
    assert torch.nn.functional.cross_entropy(logits,target,weight=torch.tensor([3.,1.],dtype=logits.dtype)).item() == pytest.approx(actual,abs=1e-12)


def test_raw_boundary_change_rejected_even_if_both_abstain():
    parent = {'rows': [{'candidate_id':'x','source_sha256':'a'*64,'boundary_logits':[1.,-1.], 'boundary_token_indices':[0]}]}
    candidate = deepcopy(parent); candidate['rows'][0]['boundary_logits'][1] = -.5
    with pytest.raises(ValueError): runner.assert_raw_token_identity(candidate,parent)


@pytest.mark.parametrize('winner', ['control', 'freeze_readout', 'distill', 'freeze_distill'])
def test_four_arm_primary_rank_is_complete_and_simplicity_ordered(winner):
    trials = [{'name': arm, 'stages': stages(), 'selected_steps': 100} for arm in runner.ARMS]
    index = runner.ARMS.index(winner)
    for trial in trials[:index]:
        trial['stages'] = stages(False); trial['selected_steps'] = 0
    assert runner.select_primary(trials) == winner
    with pytest.raises(ValueError): runner.select_primary(trials[:-1])


def test_teacher_and_candidate_receipts_support_independent_objective_reconstruction():
    torch = pytest.importorskip('torch')
    labels = torch.tensor([0, 1, 1, 0])
    teacher = torch.tensor([[2., -1.], [-1., 2.], [3., -2.], [0., 0.]], dtype=torch.float64)
    logits = torch.tensor([[.7, -.2], [-1., .3], [2., -.4], [.1, 1.1]], dtype=torch.float64, requires_grad=True)
    candidate_losses, weights = [], []
    for candidate, truth, parent in zip(logits.detach().tolist(), labels.tolist(), teacher.tolist()):
        log_z = math.log(sum(math.exp(x) for x in candidate))
        weight = 3 if truth == 0 else 1
        candidate_losses.append(weight * (log_z-candidate[truth])); weights.append(weight)
    expected_ce = sum(candidate_losses) / sum(weights)
    expected_kl_rows = []
    for candidate, parent, truth in zip(logits.detach().tolist(), teacher.tolist(), labels.tolist()):
        prediction = 0 if parent[0] >= parent[1] else 1
        if prediction != truth: continue
        norm = sum(math.exp(x) for x in parent); z = math.log(sum(math.exp(x) for x in candidate))
        expected_kl_rows.append(sum((math.exp(x)/norm) * (x-math.log(norm)-candidate[i]+z) for i,x in enumerate(parent)))
    expected_kl = sum(expected_kl_rows) / len(expected_kl_rows)
    for arm in runner.ARMS:
        loss, parts = runner.runtime.objective_loss(torch, logits, labels, teacher_logits=teacher, arm=arm)
        assert parts['teacher_correct_mask'] == [True, True, False, True]
        assert parts['teacher_correct_count'] == 3
        assert parts['cross_entropy'] == pytest.approx(expected_ce, abs=1e-12)
        assert parts['teacher_kl'] == pytest.approx(expected_kl, abs=1e-12)
        assert loss.item() == pytest.approx(expected_ce + (expected_kl if arm in ('distill','freeze_distill') else 0), abs=1e-12)
