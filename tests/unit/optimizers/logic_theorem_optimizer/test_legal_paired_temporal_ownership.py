"""Warm-state, source-complete sampler, objective and resume invariants."""
from copy import deepcopy
import hashlib
import os
os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
import pytest
import torch
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_paired_temporal_ownership as own


def query(source, index=0):
    needle = 'within 10 days'
    starts = [position for position in range(len(source)) if source.startswith(needle, position)]
    start = starts[index]
    return {'id': hashlib.sha256((source + ':' + str(start)).encode()).hexdigest(),
            'source_text': source, 'source_sha256': hashlib.sha256(source.encode()).hexdigest(),
            'proposed_time_span': {'char_start': start, 'char_end': start + len(needle)}}


def singles(prefix, groups):
    return [{**query(f'{prefix}{group} {label} Registry shall file within 10 days.'),
             'label': label, 'group_id': f'{prefix}-{group}'}
            for group in range(groups) for label in own.CLASSES]


def multiples(prefix, count=1):
    rows, units = [], []
    # Three doubles and two triples, including repeated and distinct labels.
    patterns = [('norm', 'norm'), ('condition', 'condition'), ('exception', 'exception'),
                ('ambiguous', 'ambiguous', 'norm'), ('ambiguous', 'condition', 'exception')]
    for unit in range(count):
        ids = []
        for group, labels in enumerate(patterns):
            source = '; '.join(f'{prefix}{unit}_{group}_{index} Registry shall file within 10 days' for index in range(len(labels))) + '.'
            for index, label in enumerate(labels):
                row = {**query(source, index), 'label': label, 'group_id': f'{prefix}-source-{unit}-{group}'}
                rows.append(row); ids.append(row['id'])
        units.append({'unit_id': f'{prefix}-unit-{unit}', 'query_ids': ids})
    return rows, units


@pytest.fixture
def setup(monkeypatch):
    # Synthetic legal-shaped parent fixture; production loader separately pins
    # the exact externally authenticated six-seed-study checkpoint files.
    previous = own.previous
    monkeypatch.setattr(previous.parent_runtime, 'validate_checkpoint', lambda _: None)
    config = {'seed': 1730, 'hidden_size': 32, 'embedding_dim': 16, 'latent_dimension': 0, 'trigger_enabled': True}
    base = previous.mixed._model(torch, config)
    source_parent = {'model_config': config, 'model_state': {key: value.detach().tolist() for key, value in base.state_dict().items()}}
    old_train, old_tune = singles('oldfit', 8), singles('oldtune', 2)
    parent = previous.build_checkpoint(source_parent, old_train, old_tune, arm='finetune_occurrence', seed=1730, parent_file_sha256='1' * 64)
    parent, _ = previous.train(parent, old_train, old_tune, additional_steps=1)
    parent['optimizer_steps'] = 200
    for moment in parent['optimizer_state']['parameters'].values(): moment['step'] = 200
    previous._restore(parent)
    paired, units = multiples('newfit', 2); paired_tune, _ = multiples('newtune')
    return parent, (old_train, paired, units, old_tune, paired_tune)


def checkpoint(setup, arm='mixed_occurrences'):
    parent, args = setup
    return own.build_checkpoint(parent, *args, arm=arm, seed=1730, parent_file_sha256='2' * 64)


def test_three_arms_copy_entire_warm_state_without_optimizer_moments(setup):
    parent, _ = setup
    cps = [checkpoint(setup, arm) for arm in own.ARMS]
    assert all(cp['model_state'] == parent['model_state'] for cp in cps)
    assert all(cp['optimizer_state']['parameters'] == {} and cp['optimizer_steps'] == 0 for cp in cps)
    assert all(cp['cumulative_owner_head_updates'] == 200 for cp in cps)
    assert len({cp['initial_state_sha256'] for cp in cps}) == 1
    assert parent['optimizer_state']['parameters']  # Existing moments were present and deliberately discarded.


def test_zero_update_predictions_exactly_reuse_predecessor_graph_and_wire(setup):
    queries = own.source_queries(setup[1][1][:5])
    expected = own.previous.TemporalOwnershipHead(setup[0]).predict_many(queries)
    for arm in own.ARMS:
        assert own.PairedTemporalOwnershipHead(checkpoint(setup, arm)).predict_many(queries) == expected


def test_trainable_inventory_and_frozen_decoder_tensors(setup):
    cp = checkpoint(setup); _, model, _ = own._restore(cp)
    names = {name for name, parameter in model.named_parameters() if parameter.requires_grad}
    assert sum(parameter.numel() for parameter in model.parameters() if parameter.requires_grad) == 21028
    assert all(name.startswith(('head.', 'source.encoder.')) for name in names)
    result, report = own.train(cp, *setup[1], additional_steps=1)
    for name in cp['model_state']:
        if name not in names: assert result['model_state'][name] == cp['model_state'][name]
    assert set(result['optimizer_state']['parameters']) == names == set(report['trainable_parameters'])


def test_units_allow_same_owner_queries_and_are_source_complete():
    rows, units = multiples('complete')
    records = own._records(rows); lookup = own._units(rows, records, units)
    assert len(lookup[units[0]['unit_id']]) == 12
    assert rows[0]['label'] == rows[1]['label'] and rows[0]['source_sha256'] == rows[1]['source_sha256']
    assert rows[0]['proposed_time_span'] != rows[1]['proposed_time_span']


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'split_source', 'class_imbalance', 'extra', 'one_occurrence'])
def test_invalid_paired_unit_or_source_inventory_rejected(mutation):
    rows, units = multiples('invalid', 2)
    if mutation == 'missing': units.pop()
    if mutation == 'duplicate': units[1] = deepcopy(units[0])
    if mutation == 'split_source':
        units[0]['query_ids'][0], units[1]['query_ids'][0] = units[1]['query_ids'][0], units[0]['query_ids'][0]
    if mutation == 'class_imbalance': rows[0]['label'] = 'condition'
    if mutation == 'extra': units[0]['owner_type'] = 'norm'
    if mutation == 'one_occurrence':
        rows[0] = {**query('A unique single Registry files within 10 days.'), 'label': rows[0]['label'], 'group_id': rows[0]['group_id']}
        units[0]['query_ids'][0] = rows[0]['id']
    with pytest.raises(ValueError): own._units(rows, own._records(rows), units)


def test_matched_sampler_balances_classes_and_preserves_common_prefix(setup):
    data = own._splits(*setup[1])
    for step in (0, 1, 49, 50, 99, 199):
        schedules = {arm: own.batch_indices(data['single_groups'], data['paired_units'], 1730, step, arm) for arm in own.ARMS}
        assert schedules['mixed_occurrences'] == schedules['ambiguity_weighted']
        old = schedules['single_replay']; mixed = schedules['mixed_occurrences']
        assert old['single_indices'][:12] == mixed['single_indices']
        assert old['single_group_ids'][:3] == mixed['single_group_ids']
        for arm, selected in schedules.items():
            records = [data['single_training'][i] for i in selected['single_indices']] + [data['paired_training'][i] for i in selected['paired_indices']]
            assert len(records) == 24 and [sum(row['label'] == c for row in records) for c in range(4)] == [6] * 4
            assert len(selected['paired_indices']) == (0 if arm == 'single_replay' else 12)


@pytest.mark.parametrize('arm', own.ARMS)
def test_objective_matches_independent_log_softmax_value_and_gradient(arm):
    generator = torch.Generator().manual_seed(401)
    for scale in (.1, 1., 20., 100.):
        logits = (torch.randn(24, 4, generator=generator, dtype=torch.float64) * scale).requires_grad_()
        labels = torch.arange(24) % 4
        observed, parts = own.objective(torch, logits, labels, arm)
        weights = torch.tensor([1., 1., 1., 2.] if arm == 'ambiguity_weighted' else [1.] * 4, dtype=torch.float64)[labels]
        wanted = -(torch.log_softmax(logits, -1)[torch.arange(24), labels] * weights).sum() / weights.sum()
        assert torch.allclose(observed, wanted, atol=2e-13, rtol=1e-13)
        a = torch.autograd.grad(observed, logits, retain_graph=True)[0]; b = torch.autograd.grad(wanted, logits)[0]
        assert torch.allclose(a, b, atol=2e-14, rtol=1e-12)
        assert parts['class_counts'] == [6] * 4 and parts['weighted_denominator'] == 30.


@pytest.mark.parametrize('arm', own.ARMS)
def test_two_update_resume_is_exact_and_all_steps_receipted(setup, arm):
    cp = checkpoint(setup, arm); args = setup[1]
    combined, report = own.train(cp, *args, additional_steps=2)
    first, _ = own.train(cp, *args, additional_steps=1)
    resumed, tail = own.train(first, *args, additional_steps=1)
    assert combined['model_state'] == resumed['model_state'] and combined['optimizer_state'] == resumed['optimizer_state']
    assert report['trace'][1] == tail['trace'][0]
    assert combined['cumulative_owner_head_updates'] == 202 and report['encoder_source_evaluations'] == 48
    assert all(moment['step'] == 2 for moment in combined['optimizer_state']['parameters'].values())


def test_mixed_objectives_start_with_identical_logits_and_batches(setup):
    _, common = own.train(checkpoint(setup, 'mixed_occurrences'), *setup[1], additional_steps=1)
    _, weighted = own.train(checkpoint(setup, 'ambiguity_weighted'), *setup[1], additional_steps=1)
    a, b = common['trace'][0], weighted['trace'][0]
    assert a['query_ids'] == b['query_ids'] and a['labels'] == b['labels'] and a['logits'] == b['logits']
    assert a['objective_components']['standard_ce'] == b['objective_components']['standard_ce']
    assert a['objective_components']['ambiguity_weighted_ce'] == b['objective_components']['ambiguity_weighted_ce']
    assert a['loss'] == a['objective_components']['standard_ce'] and b['loss'] == b['objective_components']['ambiguity_weighted_ce']


@pytest.mark.parametrize('mutation', ['new_steps', 'old_steps', 'cumulative', 'moment', 'negative_moment', 'predecessor', 'config_float', 'config_bool', 'authority', 'manifest'])
def test_corrupt_checkpoint_and_resume_bindings_rejected(setup, mutation):
    cp, _ = own.train(checkpoint(setup), *setup[1], additional_steps=1)
    if mutation == 'new_steps': cp['optimizer_steps'] = 201
    if mutation == 'old_steps': cp['parent_owner_head_updates'] = 199
    if mutation == 'cumulative': cp['cumulative_owner_head_updates'] = 1
    if mutation == 'moment': cp['optimizer_state']['parameters']['head.0.weight']['step'] = 201
    if mutation == 'negative_moment': cp['optimizer_state']['parameters']['head.0.weight']['exp_avg_sq'][0][0] = -1
    if mutation == 'predecessor': cp['preceding_checkpoint_sha256'] = None
    if mutation == 'config_float': cp['config']['max_steps'] = 200.
    if mutation == 'config_bool': cp['config']['parent_optimizer_moments_transferred'] = 0
    if mutation == 'authority': cp['pipeline_promotion'] = True
    if mutation == 'manifest': cp['manifests']['paired_training']['sha256'] = '0' * 64
    with pytest.raises(ValueError):
        if mutation == 'manifest': own.train(cp, *setup[1], additional_steps=1)
        else: own._restore(cp)


@pytest.mark.parametrize('tensor', ['source.byte_embedding.weight', 'source.start.weight', 'source.actor_boundary.bias'])
def test_repaired_state_hash_cannot_modify_frozen_heads(setup, tensor):
    cp, _ = own.train(checkpoint(setup), *setup[1], additional_steps=1)
    if isinstance(cp['model_state'][tensor][0], list): cp['model_state'][tensor][0][0] += .25
    else: cp['model_state'][tensor][0] += .25
    with pytest.raises(ValueError, match='frozen'): own._restore(cp)


def test_query_ID_never_changes_features_and_reference_metadata_is_rejected(setup):
    model = own.PairedTemporalOwnershipHead(checkpoint(setup)); source = own.source_queries(setup[1][1])[0]
    a = model.predict_many([source])[0]; b = model.predict_many([{**source, 'id': 'ambiguous-condition-owner'}])[0]
    assert a['logits'] == b['logits'] and a['probabilities'] == b['probabilities']
    for key, value in [('label', 'norm'), ('group_id', 'gold-group'), ('owner_span', [0, 4])]:
        with pytest.raises(ValueError, match='four-field'): model.predict_many([{**source, key: value}])


def test_training_tuning_source_and_group_leakage_rejected(setup):
    args = list(deepcopy(setup[1])); args[4] = deepcopy(args[1])
    with pytest.raises(ValueError, match='overlap'): own._splits(*args)


def test_checkpoint_file_roundtrip_and_file_hash_rejection(setup, tmp_path):
    cp = checkpoint(setup); pin = own.save_checkpoint(cp, tmp_path / 'initial.json')
    assert own.load_checkpoint(pin['path'], expected_sha256=pin['sha256']) == cp
    with pytest.raises(ValueError, match='file binding'): own.load_checkpoint(pin['path'], expected_sha256='0' * 64)


def test_wrong_parent_seed_or_architecture_cannot_warm_start(setup):
    with pytest.raises(ValueError, match='seed-matched'): own.build_checkpoint(setup[0], *setup[1], arm='single_replay', seed=1731, parent_file_sha256='2' * 64)


@pytest.mark.parametrize('kind', ['nan', 'empty', 'invalid_label'])
def test_objective_invalid_logits_or_targets_rejected(kind):
    logits = torch.zeros(4, 4); labels = torch.arange(4)
    if kind == 'nan': logits[0, 0] = float('nan')
    if kind == 'empty': logits = logits[:0]; labels = labels[:0]
    if kind == 'invalid_label': labels[0] = 4
    with pytest.raises(ValueError): own.objective(torch, logits, labels, 'mixed_occurrences')
