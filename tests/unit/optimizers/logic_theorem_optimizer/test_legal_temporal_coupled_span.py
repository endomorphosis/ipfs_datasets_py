"""Coupled span gradients, source-bound negatives, parity, and exact resume."""
from copy import deepcopy
import hashlib
import math
import os
os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
import pytest
import torch
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_temporal_coupled_span as own


def query(text, index=0):
    needle = 'within 10 days'; points = [i for i in range(len(text)) if text.startswith(needle, i)]; a = points[index]
    return {'id': hashlib.sha256((text+':'+str(a)).encode()).hexdigest(), 'source_text': text,
            'source_sha256': hashlib.sha256(text.encode()).hexdigest(), 'proposed_time_span': {'char_start': a, 'char_end': a+len(needle)}}


def singles(prefix, count=6):
    return [{**query(f'{prefix}{g} {label} Registry shall file within 10 days.'), 'label': label, 'group_id': f'{prefix}-{g}'}
            for g in range(count) for label in own.CLASSES]


def multiples(prefix):
    rows = []; ids = []
    for group, labels in enumerate([(0, 0), (1, 1), (2, 2), (3, 3, 0), (3, 1, 2)]):
        text = '; '.join(f'{prefix}_{group}_{i} Registry files within 10 days' for i in range(len(labels)))+'.'
        for i, label in enumerate(labels):
            row = {**query(text, i), 'label': own.CLASSES[label], 'group_id': f'{prefix}-{group}'}
            ids.append(row['id']); rows.append(row)
    return rows, [{'unit_id': prefix, 'query_ids': ids}]


def targets(prefix, count=6):
    rows, contrasts = [], {}
    for group in range(count):
        for label in own.CLASSES:
            text = f'{prefix}{group} {label}: Board archives notice; Registry shall file within 10 days.'
            row = {**query(text), 'label': label, 'group_id': f'{prefix}-{group}'}
            a = text.index('Registry'); b = text.index('Board')
            row['owner_anchor_span'] = None if label == 'ambiguous' else {'char_start': a, 'char_end': a+len('Registry shall file')}
            rows.append(row); contrasts[row['id']] = {'id': row['id'], 'source_sha256': row['source_sha256'],
                'proposed_time_span': row['proposed_time_span'], 'negative_owner_spans': [] if label == 'ambiguous' else
                [{'char_start': b, 'char_end': b+len('Board archives notice')}]}
    return rows, contrasts


@pytest.fixture(scope='module')
def setup():
    patch = pytest.MonkeyPatch(); earlier = own.parent.previous.previous
    patch.setattr(earlier.parent_runtime, 'validate_checkpoint', lambda _: None)
    cfg = {'seed': 1730, 'hidden_size': 32, 'embedding_dim': 16, 'latent_dimension': 0, 'trigger_enabled': True}
    base = earlier.mixed._model(torch, cfg)
    source = {'model_config': cfg, 'model_state': {k: v.detach().tolist() for k, v in base.state_dict().items()}}
    old_train, old_tune = singles('old'), singles('old-tune', 2)
    first = earlier.build_checkpoint(source, old_train, old_tune, arm='finetune_occurrence', seed=1730, parent_file_sha256='1'*64)
    first, _ = earlier.train(first, old_train, old_tune, additional_steps=1); first['optimizer_steps'] = 200
    for value in first['optimizer_state']['parameters'].values(): value['step'] = 200
    paired, units = multiples('paired'); paired_tune, _ = multiples('paired-tune')
    second = own.parent.previous.build_checkpoint(first, old_train, paired, units, old_tune, paired_tune,
        arm='mixed_occurrences', seed=1730, parent_file_sha256='2'*64)
    second, _ = own.parent.previous.train(second, old_train, paired, units, old_tune, paired_tune, additional_steps=1)
    second['optimizer_steps'] = 200; second['cumulative_owner_head_updates'] = 400
    for value in second['optimizer_state']['parameters'].values(): value['step'] = 200
    train, contrasts = targets('current'); tune, _ = targets('current-tune', 2)
    warm = own.parent.build_checkpoint(second, train, tune, arm='finetune_encoder', seed=1730, parent_file_sha256='3'*64)
    warm, _ = own.parent.train(warm, train, tune, additional_steps=1)
    warm['optimizer_steps'] = 300; warm['cumulative_owner_head_updates'] = 700
    for value in warm['optimizer_state']['parameters'].values(): value['step'] = 300
    yield warm, train, tune, contrasts
    patch.undo()


def cp(setup, arm='joint_contrast'):
    return own.build_checkpoint(*setup, arm=arm, seed=1730, parent_file_sha256='4'*64)


def test_all_initial_tensors_match_and_all_old_pointer_outputs_exact(setup):
    initial = [cp(setup, arm) for arm in own.ARMS]
    assert all(c['model_state'] == initial[0]['model_state'] and c['optimizer_state']['parameters'] == {} for c in initial)
    assert all(initial[0]['model_state'][k] == v for k, v in setup[0]['model_state'].items())
    sources = own.source_queries(setup[1][:4]); original = own.parent.TemporalOwnerPointer(setup[0]).predict_many(sources)
    for checkpoint in initial:
        predictions = own.CoupledTemporalOwnerPointer(checkpoint).predict_many(sources)
        assert [{k: r[k] for k in original[0]} for r in predictions] == original
        assert all(all(v == 0 for token in row['pointer_start_factors'] for v in token) for row in predictions)
    assert initial[0]['parent_owner_head_updates'] == initial[0]['cumulative_owner_head_updates'] == 700


@pytest.mark.parametrize('arm,parameters', [('endpoint', 41638), ('joint_span', 46774), ('joint_contrast', 46774)])
def test_exact_resume_and_frozen_parameter_inventory(setup, arm, parameters):
    initial = cp(setup, arm); args = setup[1:]
    first, r1 = own.train(initial, *args, additional_steps=1)
    split, r2 = own.train(first, *args, additional_steps=1)
    whole, report = own.train(initial, *args, additional_steps=2)
    assert split['model_state'] == whole['model_state'] and split['optimizer_state'] == whole['optimizer_state']
    assert r1['trace']+r2['trace'] == report['trace']
    assert sum(report['trainable_parameters'].values()) == parameters
    assert report['encoder_batch_forwards'] == 2 and report['encoder_source_evaluations'] == 48
    for name, value in initial['model_state'].items():
        if (name.startswith('source.') and not name.startswith('source.encoder.')) or (arm == 'endpoint' and name.startswith('interaction_')):
            assert whole['model_state'][name] == value
    if arm != 'endpoint':
        assert whole['model_state']['interaction_start.weight'] != initial['model_state']['interaction_start.weight']
        assert whole['model_state']['interaction_end.weight'] != initial['model_state']['interaction_end.weight']
    assert whole['model_state']['source.encoder.weight_ih_l0'] != initial['model_state']['source.encoder.weight_ih_l0']


def oracle(logits, starts, ends, left, right, records, arm):
    type_terms, start_terms, end_terms, joint_terms, contrast_terms = [], [], [], [], []
    for row_index, row in enumerate(records):
        type_terms.append(torch.logsumexp(logits[row_index], 0)-logits[row_index, row['label']])
        if row['label'] == 3: continue
        n = len(row['tokens']); qa, qb = row['time_tokens']; a, b = row['owner_tokens']
        tokens = [i for i in range(n) if i < qa or i > qb]
        start_terms.append(torch.logsumexp(starts[row_index, tokens], 0)-starts[row_index, a])
        end_terms.append(torch.logsumexp(ends[row_index, tokens], 0)-ends[row_index, b])
        def score(i, j):
            x = starts[row_index, i]+ends[row_index, j]
            if arm != 'endpoint': x = x+sum(left[row_index, i, k]*right[row_index, j, k] for k in range(8))/math.sqrt(8)
            return x
        scores = [score(i, j) for i in range(n) for j in range(i, n) if j < qa or i > qb]
        gold = score(a, b); joint_terms.append(torch.logsumexp(torch.stack(scores), 0)-gold)
        negatives = row['negative_owner_tokens']
        if negatives: contrast_terms.append(torch.logsumexp(torch.stack([gold]+[score(i, j) for i, j in negatives]), 0)-gold)
    zero = starts[0, 0]*0+ends[0, 0]*0+left[0, 0, 0]*0+right[0, 0, 0]*0
    type_ce = torch.stack(type_terms).mean(); joint = torch.stack(joint_terms).mean() if joint_terms else zero
    contrast = torch.stack(contrast_terms).mean() if contrast_terms else zero
    if arm == 'endpoint': loss = type_ce+.5*(torch.stack(start_terms).mean()+torch.stack(end_terms).mean())
    else: loss = type_ce+.5*joint+(.25*contrast if arm == 'joint_contrast' else 0.)
    return loss, joint, contrast


@pytest.mark.parametrize('arm', own.ARMS)
def test_independent_exhaustive_joint_contrast_values_and_gradients(arm):
    rows, contrasts = targets('oracle', 1); records = own._contrasts(rows, own._records(rows), contrasts)
    n = max(len(r['tokens']) for r in records)+2; generator = torch.Generator().manual_seed(731)
    for scale in (.1, 1., 10.):
        arrays = [(torch.randn(*shape, generator=generator, dtype=torch.float64)*scale).requires_grad_()
                  for shape in ((4, 4), (4, n), (4, n), (4, n, 8), (4, n, 8))]
        actual, parts = own.objective(torch, *arrays, records, arm)
        expected, joint, contrast = oracle(*arrays, records, arm)
        assert torch.allclose(actual, expected, atol=1e-11, rtol=1e-11)
        assert abs(parts['joint_ce']-float(joint.detach())) < 1e-11
        assert abs(parts['contrast_ce']-float(contrast.detach())) < 1e-11
        ga = torch.autograd.grad(actual, arrays, retain_graph=True, allow_unused=True)
        ge = torch.autograd.grad(expected, arrays, allow_unused=True)
        for a, b in zip(ga, ge):
            if a is None or b is None: assert a is b
            else: assert torch.allclose(a, b, atol=1e-11, rtol=1e-11)
        assert parts['contrast_count'] == 3 and parts['contrast_negative_counts'] == [1, 1, 1, 0]
        for gradient in ga[1:]:
            if gradient is None: continue
            assert torch.equal(gradient[3], torch.zeros_like(gradient[3]))
            assert torch.equal(gradient[:, -2:], torch.zeros_like(gradient[:, -2:]))
            for i, row in enumerate(records):
                a, b = row['time_tokens']; assert torch.equal(gradient[i, a:b+1], torch.zeros_like(gradient[i, a:b+1]))


def test_empty_contrasts_zero_auxiliary_finite_gradients():
    rows, contrasts = targets('no-negatives', 1)
    for value in contrasts.values(): value['negative_owner_spans'] = []
    records = own._contrasts(rows, own._records(rows), contrasts); n = len(records[0]['tokens'])
    arrays = [torch.randn(*shape, dtype=torch.float64, requires_grad=True) for shape in ((4, 4), (4, n), (4, n), (4, n, 8), (4, n, 8))]
    loss, parts = own.objective(torch, *arrays, records, 'joint_contrast')
    expected, _ = own.objective(torch, *arrays, records, 'joint_span')
    assert loss == expected and parts['contrast_count'] == 0 and parts['contrast_ce'] == 0
    assert all(torch.isfinite(g).all() for g in torch.autograd.grad(loss, arrays))


def test_all_ambiguous_batch_has_no_anchor_or_contrast_gradient():
    rows, contrasts = targets('ambiguous', 4); rows = [r for r in rows if r['label'] == 'ambiguous']
    contrasts = {r['id']: contrasts[r['id']] for r in rows}; records = own._contrasts(rows, own._records(rows), contrasts)
    n = len(records[0]['tokens']); arrays = [torch.randn(*shape, requires_grad=True) for shape in ((4, 4), (4, n), (4, n), (4, n, 8), (4, n, 8))]
    loss, parts = own.objective(torch, *arrays, records, 'joint_contrast'); grads = torch.autograd.grad(loss, arrays)
    assert parts['joint_ce'] == parts['contrast_ce'] == 0 and parts['unique_count'] == parts['contrast_count'] == 0
    assert all(torch.equal(g, torch.zeros_like(g)) for g in grads[1:])


def test_zero_start_projection_has_live_first_gradient_and_later_end_learning(setup):
    checkpoint = cp(setup); torch_, model, _ = own._restore(checkpoint)
    records, _ = own._splits(*setup[1:]); batch = [records[i] for i in own.batch_indices(records, 1730, 0)]
    loss, _ = own.objective(torch_, *model(batch), batch, 'joint_contrast'); loss.backward()
    assert torch.count_nonzero(model.interaction_start.weight.grad) > 0
    assert torch.equal(model.interaction_end.weight.grad, torch.zeros_like(model.interaction_end.weight))
    after, _ = own.train(checkpoint, *setup[1:], additional_steps=2)
    assert after['model_state']['interaction_end.weight'] != checkpoint['model_state']['interaction_end.weight']


def test_independent_scalar_decode_full_inventory_and_zero_parity():
    generator = torch.Generator().manual_seed(34)
    for n in range(1, 10):
        starts, ends = [torch.randn(n, generator=generator).tolist() for _ in range(2)]
        left, right = [torch.randn(n, 8, generator=generator).tolist() for _ in range(2)]
        qa, qb = n//2, min(n-1, n//2+1)
        for enabled in (False, True):
            result = own.decode_span(starts, ends, left, right, (qa, qb), enabled=enabled)
            pairs = [(i, j) for i in range(n) for j in range(i, n) if j < qa or i > qb]
            if not pairs:
                assert result['raw_owner_token_span'] is result['span_confidence'] is None; continue
            values = [(starts[i]+ends[j])+(math.fsum(left[i][k]*right[j][k] for k in range(8))/math.sqrt(8) if enabled else 0.) for i, j in pairs]
            chosen = max(range(len(pairs)), key=values.__getitem__); top = values[chosen]
            assert result['raw_owner_token_span'] == list(pairs[chosen]) and result['valid_span_count'] == len(pairs)
            assert abs(result['span_confidence']-1/math.fsum(math.exp(v-top) for v in values)) < 1e-14
        zero = [[0.]*8 for _ in range(n)]
        assert own.decode_span(starts, ends, zero, right, (qa, qb), enabled=True) == own.parent.decode_span(starts, ends, (qa, qb))


def test_query_mask_removes_crossing_spans_and_no_anchor_width_cap():
    starts, ends = [-100.]*60, [-100.]*60; starts[0] = ends[55] = 100.
    factors = [[0.]*8 for _ in starts]
    assert own.decode_span(starts, ends, factors, factors, (58, 59), enabled=True)['raw_owner_token_span'] == [0, 55]
    result = own.decode_span(starts, ends, factors, factors, (20, 21), enabled=True)
    a, b = result['raw_owner_token_span']; assert b < 20 or a > 21


@pytest.mark.parametrize('mutation', ['missing', 'id', 'source', 'query', 'gold', 'overlap', 'partial', 'duplicates', 'unsorted', 'ambiguous', 'extra', 'boolean'])
def test_contrast_binding_exclusion_and_uniqueness(mutation):
    rows, contrasts = targets('mutation', 1); identity = rows[0]['id']; item = contrasts[identity]
    if mutation == 'missing': contrasts.pop(identity)
    if mutation == 'id': item['id'] = 'different'
    if mutation == 'source': item['source_sha256'] = '0'*64
    if mutation == 'query': item['proposed_time_span'] = {'char_start': 0, 'char_end': 1}
    if mutation == 'gold': item['negative_owner_spans'] = [rows[0]['owner_anchor_span']]
    if mutation == 'overlap': item['negative_owner_spans'] = [rows[0]['proposed_time_span']]
    if mutation == 'partial': item['negative_owner_spans'][0]['char_start'] += 1
    if mutation == 'duplicates': item['negative_owner_spans'] *= 2
    if mutation == 'unsorted': item['negative_owner_spans'] += [{'char_start': 0, 'char_end': len('mutation0')}]
    if mutation == 'ambiguous': contrasts[rows[3]['id']]['negative_owner_spans'] = item['negative_owner_spans']
    if mutation == 'extra': item['owner_type'] = 'norm'
    if mutation == 'boolean': item['negative_owner_spans'][0]['char_start'] = True
    with pytest.raises(ValueError): own._contrasts(rows, own._records(rows), contrasts)


def test_inference_rejects_reference_features_and_is_ID_invariant(setup):
    decoder = own.CoupledTemporalOwnerPointer(cp(setup)); source = own.source_queries(setup[1][:1])[0]
    changed = {**deepcopy(source), 'id': 'opaque'}
    a, b = decoder.predict_many([source, changed])
    assert {k: v for k, v in a.items() if k != 'id'} == {k: v for k, v in b.items() if k != 'id'}
    with pytest.raises(ValueError): decoder.predict_many([{**source, 'negative_owner_spans': []}])


@pytest.mark.parametrize('mutation', ['parent', 'producer', 'config_alias', 'initial', 'count', 'frozen', 'nonfinite', 'authority', 'cumulative', 'predecessor'])
def test_checkpoint_mutations_rejected(setup, mutation):
    value = cp(setup)
    if mutation == 'parent': value['parent_payload_sha256'] = '0'*64
    if mutation == 'producer': value['implementation'] = {}
    if mutation == 'config_alias': value['config']['interaction_rank'] = 8.
    if mutation == 'initial': value['initial_state_sha256'] = '0'*64
    if mutation == 'count': value['manifests']['training_contrasts']['count'] += 1
    if mutation == 'frozen': value['model_state']['source.byte_embedding.weight'][1][0] += 1
    if mutation == 'nonfinite': value['model_state']['interaction_end.weight'][0][0] = float('nan')
    if mutation == 'authority': value['owner_occurrence_resolved'] = True
    if mutation == 'cumulative': value['cumulative_owner_head_updates'] = 701
    if mutation == 'predecessor': value['preceding_checkpoint_sha256'] = '0'*64
    with pytest.raises(ValueError): own._restore(value)


def test_endpoint_interaction_cannot_change_after_training(setup):
    value, _ = own.train(cp(setup, 'endpoint'), *setup[1:], additional_steps=1)
    value['model_state']['interaction_start.weight'][0][0] = .1
    with pytest.raises(ValueError): own._restore(value)


def test_changed_contrast_manifest_cannot_resume(setup):
    contrasts = deepcopy(setup[3]); contrasts[setup[1][0]['id']]['negative_owner_spans'] = []
    with pytest.raises(ValueError): own.train(cp(setup), setup[1], setup[2], contrasts, additional_steps=1)


@pytest.mark.parametrize('step', [-1, 200, True, 1.])
def test_sampler_rejects_wrong_step_domain(step):
    rows, _ = targets('sampler')
    with pytest.raises(ValueError): own.batch_indices(own._records(rows), 1730, step)


def test_all_arms_share_ordered_class_balanced_schedule():
    rows, _ = targets('schedule', 18); records = own._records(rows)
    ids = [own.batch_indices(records, 1730, step) for step in range(3)]
    assert set(i for batch in ids for i in batch) == set(range(72))
    assert all([records[i]['label'] for i in batch] == [c for c in range(4) for _ in range(6)] for batch in ids)


def test_checkpoint_exact_file_hash_roundtrip(setup, tmp_path):
    checkpoint = cp(setup); pin = own.save_checkpoint(checkpoint, tmp_path/'model.json')
    assert own.load_checkpoint(pin['path'], expected_sha256=pin['sha256']) == checkpoint
    with pytest.raises(ValueError): own.load_checkpoint(pin['path'], expected_sha256='0'*64)
