"""Fictional eligibility fixtures; no corpus, authored challenge or real training.

Most checkpoint tests substitute an explicit deterministic toy source carrier;
its byte/GRU execution is real, but its parent is not an experimental checkpoint.
The production carrier validator is separately tested by delegated-call checks.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_temporal_event_eligibility as m


def query(text, phrase, identity='q'):
    start = text.index(phrase)
    return {'id': identity, 'source_text': text, 'source_sha256': hashlib.sha256(text.encode()).hexdigest(),
            'proposed_time_span': {'char_start': start, 'char_end': start + len(phrase)}}


def rows(prefix, count=16, mixed=False):
    output = []
    for i in range(count):
        text = f'{prefix}{i} shall file after issuance; Office{i} shall wait until notice; Clerk{i} shall write after receipt.'
        phrases = ('after issuance', 'until notice', 'after receipt') if mixed else ('after issuance',)
        for j, phrase in enumerate(phrases):
            label = (j % 2) if mixed else i % 2
            output.append({**query(text, phrase, f'{prefix}-{i}-{j}'), 'label': m.CLASSES[label],
                           'group_id': f'{prefix}-siblings-{i//2}'})
    return output


@pytest.fixture
def toy(monkeypatch):
    torch = m._torch()
    config = {'embedding_dim': 16, 'hidden_size': 32, 'latent_dimension': 0, 'projection_width': 16,
              'residual_scale': .1, 'seed': 914, 'latent_enabled': False}
    parent = {'schema': m.carrier.SCHEMA, 'config': {'arm': 'relative_position', 'seed': 1730},
              'optimizer_steps': 200, 'model_config': config, 'fictional_test_carrier': True}
    calls = []
    def restore(value):
        assert value == parent
        calls.append(value)
        return torch, SimpleNamespace(source=m.span._model(torch, config)), None
    monkeypatch.setattr(m.carrier, '_restore', restore)
    return parent, calls


def checkpoint(toy, arm='frozen_encoder_eligibility', seed=1730):
    return m.build_checkpoint(toy[0], rows('Train'), rows('Tune', 4), arm=arm, seed=seed, parent_file_sha256='a'*64)


def test_class_source_balanced_loss_has_independent_numerical_oracle():
    torch = m._torch()
    # Source A contributes three negative candidates; B one. C and D positive.
    probabilities = [.8, .4, .2, .9, .7, .3]
    labels = [0, 0, 0, 0, 1, 1]
    sources = ['A', 'A', 'A', 'B', 'C', 'D']
    values = [[math.log(p), math.log(1-p)] if label == 0 else [math.log(1-p), math.log(p)]
              for p, label in zip(probabilities, labels)]
    logits = torch.tensor(values, dtype=torch.float64, requires_grad=True)
    records = [{'label': label, 'query': {'source_sha256': source}} for label, source in zip(labels, sources)]
    loss, detail = m.objective(torch, logits, records)
    expected = .5 * ((sum(-math.log(p) for p in probabilities[:3])/3 - math.log(.9))/2
                     + (-math.log(.7)-math.log(.3))/2)
    assert float(loss) == pytest.approx(expected, abs=1e-12)
    assert detail['class_source_counts'] == [2, 2]
    assert detail['class_candidate_counts'] == [4, 2]
    assert float(loss) != pytest.approx(sum(-math.log(p) for p in probabilities)/6)
    loss.backward()
    assert torch.isfinite(logits.grad).all() and logits.grad.abs().sum() > 0


def test_repeating_within_source_loss_does_not_change_source_weight():
    torch = m._torch()
    records = [{'label': 0, 'query': {'source_sha256': 'A'}}, {'label': 1, 'query': {'source_sha256': 'B'}}]
    logits = torch.tensor([[2., 0.], [0., 1.]])
    first, _ = m.objective(torch, logits, records)
    repeated, _ = m.objective(torch, torch.cat([logits[:1].repeat(3, 1), logits[1:]]), [records[0]]*3+[records[1]])
    assert float(first) == float(repeated)


@pytest.mark.parametrize('mixed', [False, True])
def test_sampler_keeps_complete_unique_sources_and_resumes_by_step(mixed):
    records = m._records(rows('Sample', 20, mixed=mixed))
    groups = m._source_groups(records)
    first = m.batch_indices(records, 1730, 9)
    assert first == m.batch_indices(records, 1730, 9)
    indices, selected = first
    assert len(selected) == len(set(selected)) == 16
    assert len(indices) == (48 if mixed else 16)
    for source in selected:
        assert set(groups[source]) <= set(indices)
    assert {records[i]['label'] for i in indices} == {0, 1}
    assert m.batch_indices(records, 1731, 9) != first


def test_provenance_groups_can_cover_multiple_distinct_sources():
    training, tuning = rows('Train'), rows('Tune', 4)
    records, _ = m._splits(training, tuning)
    assert len(m._source_groups(records)) == 16
    assert len({r['group_id'] for r in records}) == 8


@pytest.mark.parametrize('mutation', ['source_overlap', 'group_overlap', 'duplicate_id', 'duplicate_occurrence', 'extra_target', 'mixed_source_group', 'too_many_candidates'])
def test_training_inventory_and_split_fail_closed(mutation):
    training, tuning = rows('Train', mixed=True), rows('Tune', 4)
    if mutation == 'source_overlap': tuning[0] = deepcopy(training[0]); tuning[0]['id'] = 'new'; tuning[0]['group_id'] = 'new'
    elif mutation == 'group_overlap': tuning[0]['group_id'] = training[0]['group_id']
    elif mutation == 'duplicate_id': training[1]['id'] = training[0]['id']
    elif mutation == 'duplicate_occurrence': training.append({**deepcopy(training[0]), 'id': 'duplicate'})
    elif mutation == 'extra_target': training[0]['owner_anchor_span'] = None
    elif mutation == 'mixed_source_group': training[1]['group_id'] = 'other'
    else:
        row = deepcopy(training[0]); row['id'] = 'fourth'; row['proposed_time_span'] = {'char_start': 0, 'char_end': len('Train0')}; training.append(row)
    with pytest.raises(ValueError): m._splits(training, tuning)


@pytest.mark.parametrize('mutation', [
    lambda q:q.update(label='eligible_surface'),
    lambda q:q.update(reason_codes=['unsupported_event_shape']),
    lambda q:q.update(source_sha256='0'*64),
    lambda q:q['proposed_time_span'].update(char_start=True),
    lambda q:q['proposed_time_span'].update(char_end=3),
    lambda q:q.update(source_text='x'*4097),
])
def test_query_requires_only_authentic_complete_source_coordinates(mutation):
    value = query('Board shall file after receipt.', 'after receipt')
    mutation(value)
    with pytest.raises(ValueError): m._query(value)


@pytest.mark.parametrize('arm', m.ARMS)
def test_frozen_and_trainable_tensor_boundaries_and_fresh_optimizer(toy, arm):
    cp = checkpoint(toy, arm)
    assert toy[1] and cp['optimizer_state']['parameters'] == {}
    trained, receipt = m.train(cp, rows('Train'), rows('Tune', 4), additional_steps=1)
    changed = {key for key in cp['model_state'] if cp['model_state'][key] != trained['model_state'][key]}
    assert any(key.startswith('head.') for key in changed)
    if arm == 'frozen_encoder_eligibility':
        assert all(key.startswith('head.') for key in changed)
    else:
        assert any(key.startswith('source.encoder.') for key in changed)
        assert all(key.startswith(('head.', 'source.encoder.')) for key in changed)
    assert receipt['steps_executed'] == receipt['encoder_batch_forwards'] == 1
    assert receipt['encoder_source_evaluations'] == 16
    assert receipt['trace'][0]['objective_components']['source_count'] == 16
    assert all(moment['step'] == 1 for moment in trained['optimizer_state']['parameters'].values())
    assert cp['optimizer_steps'] == 0


def test_chunked_resume_matches_uninterrupted_parameters_and_adam_exactly(toy):
    cp = checkpoint(toy, 'finetuned_gru_eligibility')
    whole, full_trace = m.train(cp, rows('Train'), rows('Tune', 4), additional_steps=4)
    first, first_trace = m.train(cp, rows('Train'), rows('Tune', 4), additional_steps=2)
    resumed, second_trace = m.train(first, rows('Train'), rows('Tune', 4), additional_steps=2)
    assert whole['model_state'] == resumed['model_state']
    assert whole['optimizer_state'] == resumed['optimizer_state']
    assert full_trace['trace'] == first_trace['trace'] + second_trace['trace']
    assert resumed['preceding_checkpoint_sha256'] == m.digest(first)


def test_prediction_has_closed_raw_schema_and_no_label_or_id_features(toy):
    cp = checkpoint(toy)
    model = m.TemporalEventEligibility(cp)
    q = query('Élan shall file after receipt.', 'after receipt', 'one')
    p = model.predict_many([q])[0]
    renamed = deepcopy(q); renamed['id'] = 'two'
    other = model.predict_many([renamed])[0]
    assert p['logits'] == other['logits'] and p['probabilities'] == other['probabilities']
    assert p['query'] == q and other['query'] == renamed
    assert set(p) == {'schema', 'query', 'checkpoint_sha256', 'class_order', 'logits', 'probabilities',
                      'predicted_label', 'confidence', 'authority', 'formula_admission'}
    assert p['checkpoint_sha256'] == m.digest(cp)
    assert p['class_order'] == list(m.CLASSES)
    assert sum(p['probabilities']) == pytest.approx(1., abs=1e-7)
    assert p['confidence'] == max(p['probabilities'])
    assert all(v is False for v in p['authority'].values()) and p['formula_admission'] is False
    assert model.encoder_batch_forwards == 2 and model.encoder_source_evaluations == 2


@pytest.mark.parametrize('mutation', ['authority', 'source_weights', 'zero_head_weights', 'parent_payload', 'config', 'extra_key', 'optimizer_inventory'])
def test_checkpoint_tampering_fails_closed(toy, mutation):
    cp = checkpoint(toy)
    if mutation == 'authority': cp['authority']['owner_assigned'] = True
    elif mutation == 'source_weights': cp['model_state']['source.encoder.weight_ih_l0'][0][0] += .1
    elif mutation == 'zero_head_weights': cp['model_state']['head.0.weight'][0][0] += .1
    elif mutation == 'parent_payload': cp['parent']['fictional_test_carrier'] = False
    elif mutation == 'config': cp['config']['head_learning_rate'] = .5
    elif mutation == 'extra_key': cp['owner_targets'] = {}
    else: cp['optimizer_state']['parameters']['unknown'] = {}
    with pytest.raises(ValueError): m.validate_checkpoint(cp)


@pytest.mark.parametrize('mutation', ['step', 'negative_square', 'missing_moment', 'frozen_encoder'])
def test_trained_checkpoint_adam_and_frozen_parameter_contract(toy, mutation):
    cp, _ = m.train(checkpoint(toy), rows('Train'), rows('Tune', 4), additional_steps=1)
    name = next(iter(cp['optimizer_state']['parameters']))
    if mutation == 'step': cp['optimizer_state']['parameters'][name]['step'] = 2
    elif mutation == 'negative_square': cp['optimizer_state']['parameters']['head.0.bias']['exp_avg_sq'][0] = -.1
    elif mutation == 'missing_moment': cp['optimizer_state']['parameters'].pop(name)
    else: cp['model_state']['source.encoder.weight_ih_l0'][0][0] += .1
    with pytest.raises(ValueError): m.validate_checkpoint(cp)


def test_training_rejects_manifest_change_and_update_overflow(toy):
    cp = checkpoint(toy)
    changed = rows('Train'); changed[0]['label'] = m.CLASSES[1]
    with pytest.raises(ValueError): m.train(cp, changed, rows('Tune', 4), additional_steps=1)
    with pytest.raises(ValueError): m.train(cp, rows('Train'), rows('Tune', 4), additional_steps=201)


def test_save_load_file_binding_and_exclusive_output(toy, tmp_path):
    cp = checkpoint(toy)
    path = tmp_path/'eligibility.json'
    pin = m.save_checkpoint(cp, path)
    assert m.load_checkpoint(path, expected_sha256=pin['sha256']) == cp
    assert set(pin) == {'path', 'sha256', 'bytes'}
    with pytest.raises(FileExistsError): m.save_checkpoint(cp, path)
    with pytest.raises(ValueError): m.load_checkpoint(path, expected_sha256='0'*64)


def test_authenticated_actual_carrier_fictional_one_update_and_forward():
    """Actual frozen source weights, only fictional input; no study corpus reads."""
    base = Path('/home/barberb/lift_coding/artifacts/legal-temporal-event-eligibility-20261004')
    parent_path = Path('/home/barberb/lift_coding/artifacts/legal-decoder-relative-owner-20261004/run-01/relative_position-1730/checkpoint-200.json')
    expected = '7558bb022501920efd1069384384894e1079ed858588784b8b253c0a7c258cd2'
    raw = parent_path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == expected
    parent = json.loads(raw)
    training, tuning = rows('SmokeTrain'), rows('SmokeTune', 2)
    cp = m.build_checkpoint(parent, training, tuning, arm='finetuned_gru_eligibility', seed=1730, parent_file_sha256=expected)
    trained, evidence = m.train(cp, training, tuning, additional_steps=1)
    model = m.TemporalEventEligibility(trained)
    predictions = model.predict_many(m.source_queries(tuning[:1]))
    assert len(predictions) == 1 and evidence['steps_executed'] == 1
    assert evidence['encoder_batch_forwards'] == model.encoder_batch_forwards == 1
    changed = [key for key in cp['model_state'] if cp['model_state'][key] != trained['model_state'][key]]
    assert any(key.startswith('source.encoder.') for key in changed)
    assert any(key.startswith('head.') for key in changed)
    assert all(key.startswith(('source.encoder.', 'head.')) for key in changed)
    assert all(v is False for v in predictions[0]['authority'].values())
    version = str(m._torch().__version__)
    assert parent['model_config']['torch_version'] == version
    receipt = {'schema': 'eligibility-actual-carrier-fictional-smoke/v1',
               'carrier': {'path': str(parent_path), 'sha256': expected, 'bytes': len(raw)},
               'carrier_payload_sha256': m.digest(parent), 'torch_version': version,
               'training_sources': 16, 'tuning_sources': 2, 'fixture': 'fictional source strings only',
               'train_manifest_sha256': m.digest(training), 'tuning_manifest_sha256': m.digest(tuning),
               'test_optimizer_updates': 1, 'test_training_encoder_batch_forwards': 1,
               'test_inference_encoder_batch_forwards': 1, 'test_encoder_source_evaluations': 17,
               'experiment_optimizer_updates': 0, 'experiment_corpus_reads': 0,
               'trained_test_checkpoint_saved': False, 'changed_tensor_names': changed,
               'prediction_digest': m.digest(predictions), 'formula_admission': False}
    # A runner-specific evidence filename avoids clobbering earlier smoke receipts.
    import os
    label = os.environ.get('ELIGIBILITY_TEST_RECEIPT_LABEL', 'runtime-smoke-ad-hoc')
    with (base/(label+'.json')).open('x') as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True); stream.write('\n')
