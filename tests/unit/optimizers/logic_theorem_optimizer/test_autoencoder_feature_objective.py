"""Opt-in raw residual feature learning; synthetic vectors are not legal admits."""
from dataclasses import replace
import json
import math

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as ma
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_patch_codec import encode_patch, replay_patch


@pytest.fixture
def rows():
    train = build_us_code_sample(title='5', section='1', text='The agency shall retain records.', embedding_vector=[1., .5])
    tune = build_us_code_sample(title='5', section='2', text='The department shall keep records.', embedding_vector=[1., .5])
    return [train], [tune]


def feature_model(monkeypatch):
    model = ma.AdaptiveModalAutoencoder(compute_device='python', embedding_head_update_normalization=1.)
    for name in vars(model):
        if name.endswith('_embedding_weight_scale'):
            setattr(model, name, 0.)
    model.feature_embedding_weight_scale = 1.
    model.embedding_cosine_loss_weight = 0.
    monkeypatch.setattr(model, '_base_decoded_for', lambda row: [0. for _ in row.embedding_vector])
    monkeypatch.setattr(model, '_feature_keys_for', lambda row: ['shared'])
    monkeypatch.setattr(model, '_feature_update_groups_for', lambda row, step: [(['shared'], step)])
    return model


def train(model, rows, **kwargs):
    training, validation = rows
    options = dict(validation_samples=validation, epochs=3, learning_rate=.4,
                   max_seconds=60., max_line_search_attempts=1,
                   projection_candidate_update_order=('decoded_embedding',),
                   projection_update_backend='python_sparse_batch',
                   projection_reconstruction_objective='raw_decoder')
    options.update(kwargs)
    return model.train_generalizable_projection(training, **options)


def test_raw_metrics_bypass_projection_and_never_use_memory(monkeypatch, rows):
    model = feature_model(monkeypatch)
    sample = rows[1][0]
    model.state.feature_embedding_weights['shared'] = [.2, .1]
    model.state.decoded_embeddings[sample.sample_id] = [99., 99.]
    projected = model.evaluate([sample], use_sample_memory=False)
    raw = model.evaluate([sample], reconstruction_objective='raw_decoder', use_sample_memory=False)
    assert projected.reconstruction_loss == 0.
    assert raw.decoded_embeddings[sample.sample_id] == [.2, .1]
    assert raw.reconstruction_loss == pytest.approx(.4)
    with pytest.raises(ValueError, match='use_sample_memory=False'):
        model.evaluate([sample], reconstruction_objective='raw_decoder')
    with pytest.raises(ValueError, match='safety_projected or raw_decoder'):
        model.evaluate([sample], reconstruction_objective='invalid')


@pytest.mark.parametrize("optimizer", ["fixed", "guarded_adaptive", "productive_adaptive"])
def test_raw_updates_continue_after_projected_gradient_disappears(monkeypatch, rows, optimizer):
    model = feature_model(monkeypatch)
    model.state.feature_embedding_weights['shared'] = [.1, .05]
    initial = model.state.to_json()
    model._nudge_decoded_embedding(rows[0][0], learning_rate=.2, update_sample_memory=False)
    assert model.state.to_json() == initial
    # Match a worker loading the archived parent; JSON load starts revision zero.
    model.state = ma.ModalAutoencoderTrainingState.from_dict(json.loads(initial))
    patches = []
    report = train(model, rows, projection_optimizer_mode=optimizer, max_line_search_attempts=2,
                   accepted_patch_sink=lambda patch, metadata: patches.append((patch, metadata)))
    assert report['accepted_epochs'] >= 2
    assert len(patches) == report['accepted_epochs']
    assert report['after']['reconstruction_loss'] < report['before']['reconstruction_loss']
    assert all(epoch['committed_objective_delta'] > 0 for epoch in report['epoch_reports'] if epoch['accepted'])
    assert report['projection_reconstruction_objective'] == 'raw_decoder'
    assert report['formalization_qualification'] is False
    assert report['sample_memory_used'] is False
    observation = report['decoder_preprojection_observation']
    assert observation['changes_acceptance'] is True and observation['sample_scope'] == 'tuning'
    for phase in ('before', 'after'):
        metric = observation[phase]
        assert metric['complete'] and metric['finite'] and metric['used_for_acceptance']
        assert metric['observed_sample_count'] == 1
        assert metric['reconstruction_loss_mean'] == pytest.approx(report[phase]['reconstruction_loss'])
    replay = ma.ModalAutoencoderTrainingState.from_dict(json.loads(initial))
    for sequence, (patch, metadata) in enumerate(patches):
        encoded = encode_patch(patch, base_state_identity=metadata['base_state_identity'],
            result_state_identity=metadata['result_state_identity'], base_version_id='synthetic-feature-parent', sequence=sequence)
        replay_patch(replay, encoded, expected_base_version_id='synthetic-feature-parent', expected_sequence=sequence)
    assert replay.to_json() == model.state.to_json()
    assert model.state.decoded_embeddings == {}


def test_default_objective_keeps_existing_projection_and_report_shape(monkeypatch, rows):
    model = feature_model(monkeypatch)
    model.state.feature_embedding_weights['shared'] = [.1, .05]
    initial = model.state.to_json()
    report = train(model, rows, projection_reconstruction_objective='safety_projected')
    assert report['after']['reconstruction_loss'] == 0.
    assert report['accepted_epochs'] == 0
    assert model.state.to_json() == initial
    assert 'projection_reconstruction_objective' not in report
    assert 'decoder_preprojection_observation' not in report


@pytest.mark.parametrize('failure', ['missing', 'same_id', 'same_text', 'whitespace_text', 'duplicate_id', 'precomputed', 'cuda', 'invalid_mode'])
def test_reject_invalid_raw_configuration_before_state_mutation(monkeypatch, rows, failure):
    model = feature_model(monkeypatch)
    training, tuning = rows
    options = {}
    if failure == 'missing': options['validation_samples'] = []
    elif failure == 'same_id': options['validation_samples'] = [replace(tuning[0], sample_id=training[0].sample_id)]
    elif failure == 'same_text': options['validation_samples'] = [replace(tuning[0], normalized_text=training[0].normalized_text)]
    elif failure == 'whitespace_text': options['validation_samples'] = [replace(tuning[0], normalized_text='  '+training[0].normalized_text+'\n')]
    elif failure == 'duplicate_id': options['validation_samples'] = tuning * 2
    elif failure == 'precomputed': options['precomputed_holdout_evaluation'] = object()
    elif failure == 'cuda': options['projection_update_backend'] = 'cuda_resident'
    elif failure == 'invalid_mode': options['projection_reconstruction_objective'] = 'unknown'
    before = model.state.to_json()
    with pytest.raises(ValueError): train(model, rows, **options)
    assert model.state.to_json() == before


@pytest.mark.parametrize('vector', [[], [math.nan, .5], [math.inf, .5]])
def test_nonfinite_or_empty_targets_rejected_before_learning(monkeypatch, rows, vector):
    model = feature_model(monkeypatch)
    before = model.state.to_json()
    with pytest.raises(ValueError, match='nonempty finite target'):
        train(model, ([replace(rows[0][0], embedding_vector=vector)], rows[1]))
    assert model.state.to_json() == before


@pytest.mark.parametrize('decoded', [[1.], [math.nan, .5], []])
def test_raw_decoder_requires_finite_matching_dimensions(monkeypatch, rows, decoded):
    model = feature_model(monkeypatch)
    monkeypatch.setattr(model, '_decoded_for', lambda *args, **kwargs: decoded)
    with pytest.raises(ValueError):
        model.evaluate(rows[1], reconstruction_objective='raw_decoder', use_sample_memory=False)


def test_hard_example_selection_uses_raw_error(monkeypatch, rows):
    model = feature_model(monkeypatch)
    first = rows[0][0]
    second = replace(rows[1][0], embedding_vector=[2., 1.])
    model.state.feature_embedding_weights['shared'] = [.2, .1]
    weights = dict(cross_entropy=0., reconstruction=1., cosine_gap=0., legal_ir=0.)
    assert model._sample_training_objective(first, objective_weights=weights) == 0.
    assert model._sample_training_objective(second, objective_weights=weights) == 0.
    picked = model._select_hard_examples_for_projection([first, second], hard_example_fraction=.5,
        objective_weights=weights, raw_decoder_objective=True)
    assert picked == [second]


def test_raw_learning_preserves_ir_regression_guard(monkeypatch, rows):
    model = feature_model(monkeypatch)
    original = model.evaluate
    def evaluate(samples, **kwargs):
        result = original(samples, **kwargs)
        x = model.state.feature_embedding_weights.get('shared', [0.])[0]
        return replace(result, legal_ir_target_count=len(samples),
                       legal_ir_losses={'legal_ir_multiview_total_loss': 100.*x})
    monkeypatch.setattr(model, 'evaluate', evaluate)
    before = model.state.to_json()
    report = train(model, rows, max_legal_ir_loss_regression=0., objective_legal_ir_weight=0.)
    assert report['accepted_epochs'] == 0
    assert model.state.to_json() == before
    assert report['before']['legal_ir_target_count'] == report['after']['legal_ir_target_count'] == 1
    assert report['epoch_reports'][0]['candidate_reports'][0]['pareto_regressions']


def test_timeout_rolls_back_raw_candidate_and_reuses_complete_baseline(monkeypatch, rows):
    model = feature_model(monkeypatch)
    original = model._apply_projection_update_batch
    clock = [0.]
    monkeypatch.setattr(ma.time, 'time', lambda: clock[0])
    monkeypatch.setattr(ma.time, 'perf_counter', lambda: clock[0])
    def update(*args, **kwargs):
        result = original(*args, **kwargs)
        clock[0] = 61.
        return result
    monkeypatch.setattr(model, '_apply_projection_update_batch', update)
    before = model.state.to_json()
    report = train(model, rows)
    assert report['accepted_epochs'] == 0 and report['stopped_reason'] == 'projection_timeout'
    assert model.state.to_json() == before
    assert report['decoder_preprojection_observation']['after']['complete'] is True
    assert report['after'] == report['before']


def test_raw_evaluation_preserves_real_ir_metric_terms(monkeypatch, rows):
    model = feature_model(monkeypatch)
    model.state.feature_embedding_weights['shared'] = [.2, .1]
    original_payload = ma._legal_ir_target_payload
    def payload(samples, **kwargs):
        result = original_payload(samples, bridge_names=(), evaluate_provers=False)
        result.update(target_count=len(samples), losses={'legal_ir_multiview_total_loss': .4},
            target_view_distributions_by_sample={row.sample_id: {'deontic_norms': 1.} for row in samples},
            target_losses_by_sample={row.sample_id: {'deontic_ir_cross_entropy_loss': .3} for row in samples},
            target_hashes=['synthetic-controlled-target'])
        return result
    monkeypatch.setattr(ma, '_legal_ir_target_payload', payload)
    projected = model.evaluate(rows[1], use_sample_memory=False)
    raw = model.evaluate(rows[1], use_sample_memory=False, reconstruction_objective='raw_decoder')
    assert raw.legal_ir_target_count == projected.legal_ir_target_count == 1
    assert raw.legal_ir_losses == projected.legal_ir_losses
    assert raw.legal_ir_target_hashes == projected.legal_ir_target_hashes
    assert raw.legal_ir_predicted_view_distribution == projected.legal_ir_predicted_view_distribution
    assert raw.reconstruction_loss > projected.reconstruction_loss


def test_nonfinite_candidate_exception_rolls_back_sparse_update(monkeypatch, rows):
    model = feature_model(monkeypatch)
    original = model._decoded_for
    def decoded(row, **kwargs):
        if model.state.feature_embedding_weights:
            return [math.nan, 0.]
        return original(row, **kwargs)
    monkeypatch.setattr(model, '_decoded_for', decoded)
    initial = model.state.to_json()
    with pytest.raises(ValueError, match='nonempty finite decoded'):
        train(model, rows)
    assert model.state.to_json() == initial
    assert model.state._active_state_transaction is None


def test_raw_composed_refinement_uses_same_objective(monkeypatch, rows):
    model = feature_model(monkeypatch)
    evaluations = []
    original = model.evaluate
    def evaluate(samples, **kwargs):
        evaluations.append(dict(kwargs))
        return original(samples, **kwargs)
    monkeypatch.setattr(model, 'evaluate', evaluate)
    report = train(model, rows, epochs=1, projection_max_composed_refinement_attempts=1)
    assert report['accepted_epochs'] == 1
    assert report['projection_composed_refinement']['enabled'] is True
    assert all(kwargs['reconstruction_objective'] == 'raw_decoder' and kwargs['use_sample_memory'] is False
               for kwargs in evaluations)
    assert report['after']['reconstruction_loss'] < report['before']['reconstruction_loss']
