"""Exact chosen-parent continuation, balanced temporal loss and deterministic batches."""
from copy import deepcopy
from pathlib import Path
import runpy

import pytest
import torch

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_facet_retention as facet
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_temporal_presence as runtime

HELPERS = runpy.run_path(str(Path(__file__).with_name('test_legal_span_facet_retention.py')))


def rows_and_pairs(prefix='temporal-fit'):
    rows, pairs = HELPERS['rows_and_pairs'](prefix)
    removed = set(pairs[-1]); rows = [row for row in rows if row['id'] not in removed]; pairs = pairs[:-1]
    by_id = {r['id']: r for r in rows}
    for pair in pairs[:3]:
        for identifier in pair:
            row = by_id[identifier]; temporal = 'within 7 days'
            row['source_text'] = row['source_text'][:-1] + ' ' + temporal + '.'
            row['canonical_ir']['rules'][0]['temporal'] = [temporal]
            start = row['source_text'].index(temporal)
            row['facet_spans']['temporal'] = [start, start+len(temporal)]
    return rows, pairs


@pytest.fixture(scope='module', autouse=True)
def one_thread():
    before = torch.get_num_threads(); torch.set_num_threads(1)
    yield
    torch.set_num_threads(before)


@pytest.fixture(scope='module')
def parents():
    consistency = HELPERS['parents'].__wrapped__()
    rows, pairs = HELPERS['rows_and_pairs']('facet-parent')
    return {enabled: facet.train_decoder(facet.build_checkpoint(parent, rows, [], pairs,
        objective='facet_retention' if enabled else 'base', seed=1729), rows, [], pairs,
        max_steps=2, max_seconds=30)['checkpoint'] for enabled, parent in consistency.items()}


def child(parent, objective='temporal_presence'):
    rows, pairs = rows_and_pairs()
    return runtime.build_checkpoint(parent, rows, [], pairs, objective=objective, seed=1729)


@pytest.mark.parametrize('enabled', [False, True])
def test_exact_facet_parent_inference_weights_and_fresh_optimizer(parents, enabled):
    parent = parents[enabled]; cp = child(parent)
    assert cp['facet_parent_checkpoint'] == parent and cp['model_state'] == parent['model_state']
    assert cp['optimizer_state']['parameters'] == {} and cp['facet_parent_optimizer_steps'] == 2
    assert runtime.optimizer_steps(cp) == 0 and cp['training_config']['learning_rate'] == .0005
    texts = [row['source_text'] for row in rows_and_pairs('probe')[0][-6:]]
    actual = runtime.TemporalPresenceDecoder(cp)
    assert actual.decode_formal_logic(texts)['rows'] == facet.FacetRetentionDecoder(parent).decode_formal_logic(texts)['rows']
    cp['model_state'] = {}
    assert actual.checkpoint['model_state'] == parent['model_state']


@pytest.mark.parametrize('enabled', [False, True])
@pytest.mark.parametrize('objective', ['base', 'temporal_presence'])
def test_resume_preserves_losses_moments_and_stratified_pair_schedule(parents, enabled, objective):
    cp = child(parents[enabled], objective); rows, pairs = rows_and_pairs()
    full = runtime.train_decoder(cp, rows, [], pairs, max_steps=5, max_seconds=30)
    first = runtime.train_decoder(cp, rows, [], pairs, max_steps=2, max_seconds=30)
    resumed = runtime.train_decoder(first['checkpoint'], rows, [], pairs, max_steps=3, max_seconds=30)
    for key in ('model_state', 'optimizer_state', 'progress'):
        assert full['checkpoint'][key] == resumed['checkpoint'][key]
    for key in ('batch_losses', 'batch_loss_components', 'batch_exposures'):
        assert full['report'][key] == first['report'][key] + resumed['report'][key]
    for index, part in enumerate(full['report']['batch_loss_components']):
        assert part['temporal_positive_rows'] == (4 if index % 2 == 0 else 2)
        assert part['temporal_negative_rows'] == 6-part['temporal_positive_rows']
        assert part['total'] == pytest.approx(part['base_ce'] + .25*part['consistency_js'] + .5*part['teacher_kl']
            + .1*part['span_overlap'] + (.5 if objective == 'temporal_presence' else 0)*part['temporal_presence_ce'], abs=1e-6)
        assert 0 <= part['span_overlap'] <= 1
    assert full['report']['teacher_state_unchanged'] and full['report']['teacher_gradients_disabled']
    if not enabled:
        assert all(value == 0 for value in full['report']['auxiliary_gradient_norm_max'].values())


@pytest.mark.parametrize('enabled', [False, True])
def test_arms_share_schedule_initial_state_and_control_common_retention_loss(parents, enabled):
    rows, pairs = rows_and_pairs(); base = child(parents[enabled], 'base'); target = child(parents[enabled])
    assert base['model_state'] == target['model_state']
    a = runtime.train_decoder(base, rows, [], pairs, max_steps=2, max_seconds=30)
    b = runtime.train_decoder(target, rows, [], pairs, max_steps=2, max_seconds=30)
    assert a['report']['batch_exposures'] == b['report']['batch_exposures']
    records, _ = runtime.mixed._splits(rows, []); by_id = {r['id']: r for r in records}
    batch = [by_id[i] for i in a['report']['batch_exposures'][0]['ids']]
    _, model, _ = runtime._restore(base); _, teacher, _ = facet._restore(parents[enabled])
    actual, parts = runtime._loss(torch, model, teacher, batch, base['model_config'], 'base')
    expected, _ = facet._loss(torch, model, teacher, batch, base['model_config'], 'facet_retention')
    assert torch.equal(actual, expected) and parts['weighted_temporal_presence'] == 0
    ga = torch.autograd.grad(actual, tuple(model.parameters()), retain_graph=True)
    gb = torch.autograd.grad(expected, tuple(model.parameters()))
    assert all(torch.equal(left, right) for left, right in zip(ga, gb))


def test_pool_epoch_progress_reconstructs_even_and_odd_wraps():
    rows, pairs = rows_and_pairs(); pools = runtime._pairs_and_pools(rows, pairs)
    counts = {k: len(v) for k,v in pools.items()}; progress = runtime._progress(counts, 1730)
    seen = {k: [] for k in counts}
    for step in range(400):
        indices, progress = runtime.next_batch_indices(progress, counts, 1730)
        assert progress == runtime._progress(counts, 1730, step+1)
        for key, values in indices.items(): seen[key].extend(values)
    assert {k:len(v) for k,v in seen.items()} == {'earlier':1200,'historical_new':1200,'positive_pairs':600,'negative_pairs':600}
    assert all(set(values) == set(range(counts[key])) for key,values in seen.items())


def temporal_fixture(positive_rows=4):
    output = HELPERS['fake_output'](12)
    records = [{'labels': {'presence': [True,True,True,False,False,i >= 6 and i < 6+positive_rows]}} for i in range(12)]
    with torch.no_grad():
        output['presence'][:,3] = torch.tensor([1.2,-.7])
        output['presence'][6:6+positive_rows,3] = torch.tensor([-.4,.6])
    return output, records


def test_temporal_loss_equal_class_mass_independent_of_four_two_row_ratio():
    a, ar = temporal_fixture(4); b, br = temporal_fixture(2)
    av, ac = runtime._temporal_presence_loss(torch, a, ar); bv, bc = runtime._temporal_presence_loss(torch, b, br)
    assert torch.equal(av, bv)
    positive = torch.nn.functional.cross_entropy(torch.tensor([-.4,.6]), torch.tensor(1))
    negative = torch.nn.functional.cross_entropy(torch.tensor([1.2,-.7]), torch.tensor(0))
    assert torch.equal(av, (positive+negative)*.5)
    assert ac['temporal_positive_rows'] == 4 and bc['temporal_positive_rows'] == 2
    av.backward()
    grad = a['presence'].grad
    assert torch.count_nonzero(grad[:6]) == torch.count_nonzero(grad[:,:3]) == 0
    assert grad[6:10,3].abs().sum() > 0 and grad[10:,3].abs().sum() > 0
    assert a['start'].grad is None and a['end'].grad is None


def test_temporal_loss_only_new_pairs_and_rejects_missing_class():
    output, records = temporal_fixture(); a,_ = runtime._temporal_presence_loss(torch, output, records)
    with torch.no_grad(): output['presence'][:6] += 500
    for r in records[:6]: r['labels']['presence'][5] = not r['labels']['presence'][5]
    b,_ = runtime._temporal_presence_loss(torch, output, records)
    assert torch.equal(a,b)
    for r in records[6:]: r['labels']['presence'][5] = False
    with pytest.raises(ValueError, match='both temporal presence classes'):
        runtime._temporal_presence_loss(torch, output, records)


def test_inherited_correct_teacher_masks_and_valid_span_overlap_are_exact_frozen_functions():
    assert runtime._teacher_loss is facet._teacher_loss and runtime._overlap_loss is facet._overlap_loss
    assert runtime._pair_overlap_probability is facet._pair_overlap_probability
    student, teacher, record = HELPERS['teacher_fixture']()
    loss, parts = runtime._teacher_loss(torch, student, teacher, [record], (0,))
    loss.backward()
    assert parts['teacher_presence_terms'] == 4 and parts['teacher_endpoint_terms'] == 2
    assert all(v.grad is None for v in teacher.values()) and student['presence'].grad.abs().sum() > 0


def test_pair_class_imbalance_is_rejected(parents):
    rows,pairs = rows_and_pairs()
    with pytest.raises(ValueError, match='equal temporal-present'):
        runtime.build_checkpoint(parents[True], rows, [], pairs[:-1], objective='base', seed=1729)


@pytest.mark.parametrize('mutation', ['parent_hash','initial_weights','trained_predecessor','progress','budget','objective'])
def test_checkpoint_mutations_fail_closed(parents, mutation):
    rows,pairs = rows_and_pairs(); cp = child(parents[True])
    if mutation == 'parent_hash': cp['facet_parent_checkpoint_sha256'] = '0'*64
    elif mutation == 'initial_weights': cp['initial_model_state_sha256'] = '0'*64
    elif mutation == 'trained_predecessor':
        cp = runtime.train_decoder(cp, rows, [], pairs, max_steps=1, max_seconds=30)['checkpoint']
        cp['parent_checkpoint_sha256'] = None
    elif mutation == 'progress': cp['progress']['optimizer_steps'] = 401
    elif mutation == 'budget': cp['training_config']['optimizer_step_budget'] = 800
    else: cp['training_config']['objective'] = 'facet_retention'
    with pytest.raises(ValueError): runtime.validate_checkpoint(cp)


def test_safe_roundtrip_and_resume_manifest_bound(parents, tmp_path):
    cp = child(parents[True]); reference = runtime.save_checkpoint(cp, tmp_path/'checkpoint.json')
    assert runtime.load_checkpoint(reference['path'],expected_sha256=reference['sha256']) == cp
    with pytest.raises(FileExistsError): runtime.save_checkpoint(cp, tmp_path/'checkpoint.json')
    rows,pairs = rows_and_pairs(); changed = deepcopy(pairs); changed[0].reverse()
    with pytest.raises(ValueError, match='manifest'):
        runtime.train_decoder(cp, rows, [], changed, max_steps=1, max_seconds=30)
    with pytest.raises(ValueError, match='max_steps'):
        runtime.train_decoder(cp, rows, [], pairs, max_steps=401, max_seconds=30)
