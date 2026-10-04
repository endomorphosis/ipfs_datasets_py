"""Pointer supervision, full span search, inherited graph and resume contracts."""
from copy import deepcopy
import hashlib
import math
import os
os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
import pytest
import torch
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_temporal_owner_pointer as own


def query(text, index=0):
    needle = 'within 10 days'; positions = [i for i in range(len(text)) if text.startswith(needle, i)]; a = positions[index]
    return {'id': hashlib.sha256((text + ':' + str(a)).encode()).hexdigest(), 'source_text': text,
            'source_sha256': hashlib.sha256(text.encode()).hexdigest(), 'proposed_time_span': {'char_start': a, 'char_end': a+len(needle)}}


def singles(prefix, count=6):
    return [{**query(f'{prefix}{g} {label} Registry shall file within 10 days.'), 'label': label, 'group_id': f'{prefix}-{g}'}
            for g in range(count) for label in own.CLASSES]


def multiples(prefix, count=1):
    rows, units = [], []
    for unit in range(count):
        ids = []
        for group, labels in enumerate([(0, 0), (1, 1), (2, 2), (3, 3, 0), (3, 1, 2)]):
            text = '; '.join(f'{prefix}{unit}_{group}_{i} Registry files within 10 days' for i in range(len(labels)))+'.'
            for i, label in enumerate(labels):
                row = {**query(text, i), 'label': own.CLASSES[label], 'group_id': f'{prefix}-{unit}-{group}'}
                ids.append(row['id']); rows.append(row)
        units.append({'unit_id': f'{prefix}-{unit}', 'query_ids': ids})
    return rows, units


def targets(prefix, count=6):
    rows = singles(prefix, count)
    for row in rows:
        start = row['source_text'].index('Registry')
        row['owner_anchor_span'] = None if row['label'] == 'ambiguous' else {'char_start': start, 'char_end': start+len('Registry shall file')}
    return rows


@pytest.fixture(scope='module')
def setup():
    patch = pytest.MonkeyPatch(); earlier = own.previous.previous
    patch.setattr(earlier.parent_runtime, 'validate_checkpoint', lambda _: None)
    cfg = {'seed': 1730, 'hidden_size': 32, 'embedding_dim': 16, 'latent_dimension': 0, 'trigger_enabled': True}
    model = earlier.mixed._model(torch, cfg)
    source = {'model_config': cfg, 'model_state': {k: v.detach().tolist() for k, v in model.state_dict().items()}}
    train, tune = singles('earlier'), singles('earlier-tune', 2)
    old = earlier.build_checkpoint(source, train, tune, arm='finetune_occurrence', seed=1730, parent_file_sha256='1'*64)
    old, _ = earlier.train(old, train, tune, additional_steps=1)
    old['optimizer_steps'] = 200
    for value in old['optimizer_state']['parameters'].values(): value['step'] = 200
    pairs, units = multiples('paired'); new_tune, _ = multiples('paired-tune')
    parent = own.previous.build_checkpoint(old, train, pairs, units, tune, new_tune, arm='mixed_occurrences', seed=1730, parent_file_sha256='2'*64)
    parent, _ = own.previous.train(parent, train, pairs, units, tune, new_tune, additional_steps=1)
    parent['optimizer_steps'] = 200; parent['cumulative_owner_head_updates'] = 400
    for value in parent['optimizer_state']['parameters'].values(): value['step'] = 200
    yield parent, targets('pointer'), targets('pointer-tune', 2)
    patch.undo()


def cp(setup, arm='frozen_encoder'):
    return own.build_checkpoint(*setup, arm=arm, seed=1730, parent_file_sha256='3'*64)


def test_initial_inherited_tensors_and_pointer_initialization_match(setup):
    a, b = [cp(setup, arm) for arm in own.ARMS]
    assert a['model_state'] == b['model_state'] and a['initial_state_sha256'] == b['initial_state_sha256']
    assert all(a['model_state'][k] == v for k, v in setup[0]['model_state'].items())
    assert a['optimizer_state']['parameters'] == b['optimizer_state']['parameters'] == {}
    assert a['parent_owner_head_updates'] == a['cumulative_owner_head_updates'] == 400


@pytest.mark.parametrize('arm', own.ARMS)
def test_initial_type_predictions_exactly_parent(setup, arm):
    sources = own.source_queries(setup[1][:8])
    parent = own.previous.PairedTemporalOwnershipHead(setup[0]).predict_many(sources)
    pointer = own.TemporalOwnerPointer(cp(setup, arm)).predict_many(sources)
    for left, right in zip(parent, pointer):
        assert left == {key: right[key] for key in left}
        assert len(right['pointer_start_logits']) == len(own.span.tokenize_source(sources[0]['source_text']))
        assert right['owner_occurrence_resolved'] is False


@pytest.mark.parametrize('arm,expected', [('frozen_encoder', 28966), ('finetune_encoder', 41638)])
def test_resume_trace_moments_and_frozen_weights_exact(setup, arm, expected):
    initial = cp(setup, arm)
    one, first = own.train(initial, *setup[1:], additional_steps=1)
    resumed, second = own.train(one, *setup[1:], additional_steps=1)
    whole, report = own.train(initial, *setup[1:], additional_steps=2)
    assert resumed['model_state'] == whole['model_state'] and resumed['optimizer_state'] == whole['optimizer_state']
    assert first['trace'] + second['trace'] == report['trace']
    assert sum(report['trainable_parameters'].values()) == expected
    assert report['encoder_batch_forwards'] == 2 and report['encoder_source_evaluations'] == 48
    for key, value in initial['model_state'].items():
        if key.startswith('source.') and not (arm == 'finetune_encoder' and key.startswith('source.encoder.')):
            assert whole['model_state'][key] == value
    assert whole['model_state']['pointer_start.0.weight'] != initial['model_state']['pointer_start.0.weight']
    assert whole['model_state']['head.0.weight'] != initial['model_state']['head.0.weight']


def test_independent_loss_and_gradients_mask_ambiguous_query_padding():
    records = own._records(targets('loss', 1))
    width = max(len(r['tokens']) for r in records) + 3
    generator = torch.Generator().manual_seed(42)
    for scale in (.1, 1., 100.):
        values = [(torch.randn(4, size, generator=generator, dtype=torch.float64)*scale).requires_grad_() for size in (4, width, width)]
        logits, starts, ends = values
        type_terms, s_terms, e_terms = [], [], []
        for i, row in enumerate(records):
            type_terms.append(torch.logsumexp(logits[i], 0)-logits[i, row['label']])
            if row['owner_tokens'] is None: continue
            qa, qb = row['time_tokens']; allowed = [j for j in range(len(row['tokens'])) if j < qa or j > qb]
            s_terms.append(torch.logsumexp(starts[i, allowed], 0)-starts[i, row['owner_tokens'][0]])
            e_terms.append(torch.logsumexp(ends[i, allowed], 0)-ends[i, row['owner_tokens'][1]])
        oracle = torch.stack(type_terms).mean()+.5*(torch.stack(s_terms).mean()+torch.stack(e_terms).mean())
        loss, parts = own.objective(torch, logits, starts, ends, records)
        assert torch.allclose(loss, oracle, atol=1e-12, rtol=1e-12)
        actual = torch.autograd.grad(loss, values, retain_graph=True); expected = torch.autograd.grad(oracle, values)
        assert all(torch.allclose(a, b, atol=1e-12, rtol=1e-12) for a, b in zip(actual, expected))
        assert parts['unique_count'] == 3 and parts['class_counts'] == [1]*4
        for gradient in actual[1:]:
            assert torch.equal(gradient[3], torch.zeros_like(gradient[3]))
            assert torch.equal(gradient[:, -3:], torch.zeros_like(gradient[:, -3:]))
            for i, row in enumerate(records):
                qa, qb = row['time_tokens']; assert torch.equal(gradient[i, qa:qb+1], torch.zeros_like(gradient[i, qa:qb+1]))


def test_all_ambiguous_batch_has_zero_pointer_loss_and_gradient():
    records = [r for r in own._records(targets('ambiguous', 4)) if r['label'] == 3]
    logits = torch.randn(4, 4, requires_grad=True); starts = torch.randn(4, 12, requires_grad=True); ends = torch.randn(4, 12, requires_grad=True)
    loss, parts = own.objective(torch, logits, starts, ends, records); loss.backward()
    assert parts['start_ce'] == parts['end_ce'] == 0 and parts['unique_count'] == 0
    assert torch.equal(starts.grad, torch.zeros_like(starts)) and torch.equal(ends.grad, torch.zeros_like(ends))


def test_full_ordered_span_inventory_and_independent_probability():
    generator = torch.Generator().manual_seed(99)
    for n in range(1, 11):
        for a in range(n):
            b = min(n-1, a+1)
            start = torch.randn(n, generator=generator, dtype=torch.float32).tolist()
            end = torch.randn(n, generator=generator, dtype=torch.float32).tolist()
            candidates = [(i, j, start[i]+end[j]) for i in range(n) for j in range(i, n) if j < a or i > b]
            result = own.decode_span(start, end, (a, b))
            assert result['valid_span_count'] == len(candidates)
            if not candidates:
                assert result['raw_owner_token_span'] is result['span_confidence'] is None
            else:
                chosen = max(candidates, key=lambda x: x[2]); maximum = chosen[2]
                expected = math.exp(chosen[2]-maximum)/sum(math.exp(c[2]-maximum) for c in candidates)
                assert result['raw_owner_token_span'] == list(chosen[:2])
                assert abs(result['span_confidence']-expected) < 1e-15


def test_long_spans_have_no_gold_derived_width_cap_and_ties_are_lexicographic():
    starts, ends = [-100.]*60, [-100.]*60; starts[0] = 100.; ends[55] = 100.
    assert own.decode_span(starts, ends, (58, 59))['raw_owner_token_span'] == [0, 55]
    result = own.decode_span([0.]*6, [0.]*6, (2, 3))
    assert result['raw_owner_token_span'] == [0, 0] and result['valid_span_count'] == 6 and result['span_confidence'] == 1/6


def test_sampler_is_balanced_reproducible_and_covers_every_class_epoch():
    records = own._records(targets('sampler', 18)); shuffled = list(reversed(records))
    draws = [own.batch_indices(records, 1730, step) for step in range(3)]
    assert set(i for batch in draws for i in batch) == set(range(len(records)))
    for step, indices in enumerate(draws):
        assert [records[i]['label'] for i in indices] == [c for c in range(4) for _ in range(6)]
        actual = [shuffled[i]['query']['id'] for i in own.batch_indices(shuffled, 1730, step)]
        assert actual == [records[i]['query']['id'] for i in indices]


def test_ids_are_not_features_and_queries_are_occurrence_sensitive(setup):
    decoder = own.TemporalOwnerPointer(cp(setup)); source = query('Registry files within 10 days; Board archives within 10 days.', 0)
    changed = {**deepcopy(source), 'id': 'opaque-new-id'}
    other = query(source['source_text'], 1)
    a, b, c = decoder.predict_many([source, changed, other])
    assert {k: v for k, v in a.items() if k != 'id'} == {k: v for k, v in b.items() if k != 'id'}
    assert a['pointer_start_logits'] != c['pointer_start_logits']
    with pytest.raises(ValueError): decoder.predict_many([{**source, 'owner_anchor_span': {'char_start': 0, 'char_end': 8}}])


@pytest.mark.parametrize('case,reason', [('accepted', None), ('ambiguous', 'predicted_ambiguous'),
    ('low_type', 'below_fixed_type_confidence'), ('low_span', 'below_fixed_span_confidence'),
    ('no_span', 'no_valid_owner_span')])
def test_fixed_joint_policy_and_source_intervals(setup, monkeypatch, case, reason):
    decoder = own.TemporalOwnerPointer(cp(setup))
    source = query('within 10 days' if case == 'no_span' else 'Registry files within 10 days.')
    record = own._query(source); width = len(record['tokens'])
    type_logits = torch.tensor([[0., 0., 0., 20.] if case == 'ambiguous' else [20., 0., 0., 0.]])
    if case in ('low_type', 'no_span'): type_logits = torch.zeros(1, 4)
    starts, ends = torch.full((1, width), -20.), torch.full((1, width), -20.)
    starts[0, 0] = 20.; ends[0, min(1, width-1)] = 20.
    if case == 'low_span': starts.zero_(); ends.zero_()
    monkeypatch.setattr(decoder.model, 'forward', lambda _: (type_logits, starts, ends))
    row = decoder.predict_many([source])[0]
    assert row['joint_reason'] == reason and row['joint_status'] == ('accepted' if reason is None else 'deferred')
    if case == 'accepted':
        assert row['raw_owner_token_span'] == [0, 1]
        assert row['proposed_owner_anchor_span'] == {'char_start': 0, 'char_end': len('Registry files')}
    else: assert row['proposed_owner_anchor_span'] is None
    if case == 'no_span':
        assert row['raw_owner_token_span'] is row['raw_owner_anchor_span'] is row['span_confidence'] is None
        assert row['valid_span_count'] == 0
    assert row['owner_occurrence_resolved'] is False and row['pipeline_promotion'] is False


def test_token_padding_does_not_change_pointer_predictions_beyond_float_tolerance(setup):
    decoder = own.TemporalOwnerPointer(cp(setup)); short = query('Registry files within 10 days.')
    long = query('If the application is valid, the large Registry shall carefully file the complete notice within 10 days unless a waiver is active.')
    alone = decoder.predict_many([short])[0]; batched = decoder.predict_many([short, long])[0]
    for field in ('logits', 'pointer_start_logits', 'pointer_end_logits'):
        assert torch.allclose(torch.tensor(alone[field]), torch.tensor(batched[field]), atol=1e-6, rtol=1e-6)
    assert alone['valid_span_count'] == batched['valid_span_count']


@pytest.mark.parametrize('mutation', ['ambiguous_anchor', 'missing_anchor', 'overlap', 'partial_token', 'bool_offset', 'duplicate', 'extra_gold'])
def test_supervised_anchor_contract_fails_closed(mutation):
    rows = targets('validation', 2)
    if mutation == 'ambiguous_anchor': rows[3]['owner_anchor_span'] = rows[0]['owner_anchor_span']
    if mutation == 'missing_anchor': rows[0]['owner_anchor_span'] = None
    if mutation == 'overlap': rows[0]['owner_anchor_span'] = rows[0]['proposed_time_span']
    if mutation == 'partial_token': rows[0]['owner_anchor_span']['char_start'] += 1
    if mutation == 'bool_offset': rows[0]['owner_anchor_span']['char_start'] = True
    if mutation == 'duplicate': rows[1] = deepcopy(rows[0])
    if mutation == 'extra_gold': rows[0]['gold_owner_type'] = 'norm'
    with pytest.raises(ValueError): own._records(rows)


@pytest.mark.parametrize('mutation', ['numeric_alias', 'bool_alias', 'producer', 'initial', 'frozen_tensor', 'nonfinite', 'count', 'predecessor', 'cumulative', 'authority', 'parent'])
def test_checkpoint_mutations_rejected(setup, mutation):
    value = cp(setup)
    if mutation == 'numeric_alias': value['config']['max_steps'] = 300.
    if mutation == 'bool_alias': value['config']['head_learning_rate'] = True
    if mutation == 'producer': value['implementation'] = {}
    if mutation == 'initial': value['initial_state_sha256'] = '0'*64
    if mutation == 'frozen_tensor': value['model_state']['source.encoder.weight_ih_l0'][0][0] += 1
    if mutation == 'nonfinite': value['model_state']['pointer_start.0.weight'][0][0] = math.inf
    if mutation == 'count': value['manifests']['training']['count'] = True
    if mutation == 'predecessor': value['preceding_checkpoint_sha256'] = '0'*64
    if mutation == 'cumulative': value['cumulative_owner_head_updates'] = 401
    if mutation == 'authority': value['owner_occurrence_resolved'] = True
    if mutation == 'parent': value['parent_payload_sha256'] = '0'*64
    with pytest.raises(ValueError): own._restore(value)


def test_trained_frozen_encoder_mutation_rejected_even_with_repaired_hash(setup):
    value, _ = own.train(cp(setup), *setup[1:], additional_steps=1)
    value['model_state']['source.encoder.weight_ih_l0'][0][0] += .1
    with pytest.raises(ValueError): own._restore(value)


def test_manifest_mutation_prevents_resume(setup):
    rows = deepcopy(setup[1]); rows[0]['group_id'] = 'revised'
    with pytest.raises(ValueError): own.train(cp(setup), rows, setup[2], additional_steps=1)


@pytest.mark.parametrize('step', [-1, 300, True, 1.])
def test_sampler_invalid_steps_rejected(step):
    with pytest.raises(ValueError): own.batch_indices(own._records(targets('badstep')), 1730, step)


def test_split_overlap_rejected():
    rows = targets('shared')
    with pytest.raises(ValueError): own._splits(rows, rows)


def test_checkpoint_file_exact_hash_roundtrip(setup, tmp_path):
    value = cp(setup); ref = own.save_checkpoint(value, tmp_path/'model.json')
    assert own.load_checkpoint(ref['path'], expected_sha256=ref['sha256']) == value
    with pytest.raises(ValueError): own.load_checkpoint(ref['path'], expected_sha256='0'*64)
