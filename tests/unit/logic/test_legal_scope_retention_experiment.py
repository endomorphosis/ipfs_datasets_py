"""Raw scope gates and frozen token-boundary preservation are independent."""
from copy import deepcopy

import pytest

from scripts.ops.legal_ir import run_legal_scope_retention_experiment as runner
from scripts.ops.legal_ir import prepare_legal_scope_retention_corpus as corpus


@pytest.fixture(scope='module')
def data():
    panels, pairs, _ = corpus.make_panels()
    return panels, pairs


def test_matched_batches_share_replay_ids_and_scope_class_counts(data):
    panels, pairs = data
    replay = panels['tuning'] + panels['fresh']
    left = list(runner.batch_schedule(replay, panels['train'], pairs['train'], 'control'))
    right = list(runner.batch_schedule(replay, panels['train'], pairs['train'], 'target'))
    assert len(left) == len(right) == 400
    for (a, ar), (b, br) in zip(left, right):
        assert a[:6] == b[:6] and ar['common_replay_ids'] == br['common_replay_ids']
        assert len(a) == len(b) == 12 and ar['supported_count'] == br['supported_count']
        assert ar['unsupported_count'] == br['unsupported_count'] and not ar['pair_ids'] and len(br['pair_ids']) == 3
    assert set(x for _, receipt in right for x in receipt['extra_ids']) == {r['candidate_id'] for r in panels['train']}


def test_only_130_scope_parameters_change_and_token_outputs_stay_exact(data):
    torch = pytest.importorskip('torch'); torch.set_num_threads(1); torch.manual_seed(61)
    network = runner.boundary.model(torch)
    before = deepcopy(network.state_dict())
    parameters = runner.configure_trainable(network)
    assert sum(p.numel() for p in parameters) == 130
    optimizer = torch.optim.Adam(parameters, lr=.004)
    packed = runner.boundary.tensor_batch(torch, data[0]['train'][:4], labels=True)
    with torch.no_grad(): before_logits = network(*packed[:3])[0].clone()
    _, logits = network(*packed[:3]); loss = torch.nn.functional.cross_entropy(logits, packed[4], weight=torch.tensor([3., 1.]))
    loss.backward(); optimizer.step()
    after = network.state_dict()
    for name in before:
        if name in runner.SCOPE_PARAMETERS: assert not torch.equal(before[name], after[name])
        else:
            assert torch.equal(before[name], after[name])
            assert dict(network.named_parameters())[name].grad is None
    with torch.no_grad(): assert torch.equal(before_logits, network(*packed[:3])[0])
    assert runner.assert_frozen_state({k: v.tolist() for k, v in before.items()}, {k: v.tolist() for k, v in after.items()})


def score(supported=48, exact=36, raw_guard=0, accepted=0):
    return {'documents': 96, 'supported_documents': 48, 'unsupported_documents': 48,
            'raw_supported_scope_correct': supported, 'exact_supported_segmentation': exact,
            'raw_unsupported_accepted': raw_guard, 'unsupported_accepted': accepted}


@pytest.mark.parametrize('change', ['raw_guard_hidden_by_abstention', 'all_reject', 'supported_scope_loss', 'supported_interval_loss', 'token_changed', 'denominator'])
def test_scope_gates_reject_hidden_errors_and_all_reject_shortcuts(change):
    parent = {'scope_new': score(), 'historical': score()}; stage = deepcopy(parent); identity = True
    if change == 'raw_guard_hidden_by_abstention': stage['historical']['raw_unsupported_accepted'] = 1
    elif change == 'all_reject': stage['scope_new'] = score(0, 0)
    elif change == 'supported_scope_loss': stage['historical']['raw_supported_scope_correct'] -= 1
    elif change == 'supported_interval_loss': stage['historical']['exact_supported_segmentation'] -= 1
    elif change == 'token_changed': identity = False
    else:
        stage['historical']['documents'] -= 1
        with pytest.raises(ValueError): runner.gates(stage, parent, identity)
        return
    assert runner.gates(stage, parent, identity)['eligible'] is False


def test_clean_scope_repair_eligible_despite_parent_guard_error():
    parent = {'scope_new': score(raw_guard=4)}; stage = {'scope_new': score()}
    assert runner.gates(stage, parent, True) == {'eligible': True, 'failures': []}


def test_stage_selection_honest_fallback_and_earliest_tie():
    stages = [{'steps': n, 'eligible': False, 'metrics': {'scope_new': score()}} for n in runner.STEPS]
    assert runner.select_stage(stages) is None
    for stage in stages: stage['eligible'] = True
    assert runner.select_stage(stages)['steps'] == 100
    stages[-1]['metrics']['scope_new']['exact_supported_segmentation'] += 1
    assert runner.select_stage(stages)['steps'] == 400


@pytest.mark.parametrize('change', ['id', 'hash', 'logits', 'indices', 'missing_row'])
def test_raw_boundary_preservation_checked_beyond_accepted_plans(change):
    parent = {'rows': [{'candidate_id': 'x', 'source_sha256': 'a' * 64, 'boundary_logits': [1., -1., 1.], 'boundary_token_indices': [0, 2]}]}
    generated = deepcopy(parent)
    if change == 'missing_row': generated['rows'] = []
    else:
        key = {'id': 'candidate_id', 'hash': 'source_sha256', 'logits': 'boundary_logits', 'indices': 'boundary_token_indices'}[change]
        generated['rows'][0][key] = 'bad' if change in ('id', 'hash') else [0]
    with pytest.raises(ValueError): runner.assert_raw_token_identity(generated, parent)


def test_non_scope_checkpoint_mutation_rejected():
    with pytest.raises(ValueError, match='frozen'):
        runner.assert_frozen_state({'scope.weight': [1], 'encoder.weight': [2]}, {'scope.weight': [3], 'encoder.weight': [4]})


def test_pinned_historical_reference_without_optional_byte_count(tmp_path):
    reference = corpus.write_new(tmp_path / 'old.json', {'historic': True})
    reference.pop('bytes')
    assert runner.read_ref(reference) == {'historic': True}
    reference['sha256'] = '0' * 64
    with pytest.raises(ValueError): runner.read_ref(reference)


@pytest.mark.parametrize('steps', [0, 401, True])
def test_unplanned_training_budget_rejected(data, steps):
    with pytest.raises(ValueError): next(runner.batch_schedule(data[0]['tuning'], data[0]['train'], data[1]['train'], 'target', steps))
