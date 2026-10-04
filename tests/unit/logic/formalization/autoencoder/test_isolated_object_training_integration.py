"""Bounded synthetic integration; no corpus fits, local encoders or teachers."""
from copy import deepcopy
import time

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import isolated_object_clause_decoder_experiment as isolated
from ipfs_datasets_py.logic.formalization.autoencoder import long_span_source_value_training as subject
from ipfs_datasets_py.logic.formalization.autoencoder import contextual_generated_boundary_training as boundary
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core
from .test_ordered_clause_recurrent_training_runner import real_fixture


@pytest.fixture(autouse=True)
def one_cpu():
    old = torch.get_num_threads(); torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


def trial(monkeypatch):
    old, _, train, tune, options, contexts = real_fixture(monkeypatch)
    return isolated.bind_isolated_object_model(old, codec=options['codec']), train, tune, options, contexts


def fit(model, train, tune, options, contexts, **kwargs):
    return subject.train(model, train, tune, source_contexts=contexts,
        source_value_weight=.25, cardinality_weight=.25, count_exposure='balanced_all',
        action_contrastive_weight=.05, **options, **kwargs)


@pytest.mark.parametrize('multiplier', [1., 10.])
def test_real_optimizer_updates_private_projection_with_same_targets_losses_and_selection(monkeypatch, multiplier):
    model, train, tune, options, contexts = trial(monkeypatch)
    before = core.tensor_digest(model); rng = torch.get_rng_state().clone()
    inputs = deepcopy((train, tune, options, contexts))
    result = fit(model, train, tune, options, contexts, non_action_learning_rate_multiplier=multiplier)
    report = result['report']
    assert report['optimizer_steps'] == report['action_contrastive_active_updates'] == 2
    assert report['source_value_presentations'] == 24
    assert report['selection'] == 'per_length_nonregression_then_fidelity_progress_then_reference_ce'
    assert report['source_value_head']['schema'] == isolated.SCHEMA
    assert report['isolated_object_additional_parameters'] == 576
    assert not report['isolated_object_auxiliary_objective_added']
    assert report['isolated_object_existing_loss_reductions_unchanged']
    assert not report['isolated_object_recurrent_features_extended']
    assert not report['isolated_object_historical_teacher_modified']
    initial = model.state_dict(); last = result['last_complete_attempt_state_dict']
    assert any(not torch.equal(initial[name], last[name]) for name in isolated.EXTRA_NAMES)
    for name in report['frozen_parameter_names']: assert torch.equal(initial[name], last[name])
    for update in report['committed_updates']:
        expected = update['weighted_token_ce'] + report['config']['reconstruction_weight'] * update['raw_reconstruction_mse']
        expected += .25 * update['count_ce'] + .25 * update['source_value_ce'] + .05 * update['action_contrastive']['loss']
        assert update['objective'] == pytest.approx(expected, abs=1e-6)
    if multiplier == 10.:
        groups = report['optimizer_parameter_groups']
        assert len(groups) == 2 and len(groups[1]['parameter_names']) == 6
        assert set(isolated.EXTRA_NAMES) <= set(groups[1]['parameter_names'])
        assert groups[1]['initial_learning_rate'] == .01
        assert groups[0]['initial_learning_rate'] == .001
    else:
        assert 'optimizer_parameter_groups' not in report
    assert core.tensor_digest(model) == before and torch.equal(rng, torch.get_rng_state())
    assert inputs == (train, tune, options, contexts)
    assert all(report[k] is False for k in ('qualified', 'admitted', 'lake_executed', 'convergence_proven'))


@pytest.mark.parametrize('retry', [False, True])
def test_original_contextual_boundary_path_accepts_new_checked_schema(monkeypatch, retry):
    model, train, tune, options, contexts = trial(monkeypatch)
    assert boundary._specification(model, options['codec'])[1:] == (True, 7)
    collected_schemas = []
    original_collect = boundary.collect_source_boundary_prefixes
    def collect(*args, **kwargs):
        result = original_collect(*args, **kwargs)
        collected_schemas.append(result['model_schema'])
        return result
    monkeypatch.setattr(boundary, 'collect_source_boundary_prefixes', collect)
    result = fit(model, train, tune, options, contexts, generated_boundary_weight=.05,
                 generated_boundary_retry_on_mismatch=retry, non_action_learning_rate_multiplier=10.)
    report = result['report']; assert report['optimizer_steps'] == 2
    assert collected_schemas == [isolated.SCHEMA] * 2
    for update in report['committed_updates']:
        receipt = update['generated_boundary']
        assert not receipt['target_prefixes_used'] and receipt['full_vocabulary_cross_entropy']
        assert receipt['replay_logits_atol'] == receipt['replay_logits_rtol'] == 2e-5
        assert receipt['qualified'] is False and receipt['admitted'] is False
    assert report['selection'] == 'per_length_nonregression_then_fidelity_progress_then_reference_ce'


def test_new_memory_estimate_accounts_for_private_graph_without_changing_old_defaults(monkeypatch):
    old, _, train, tune, options, contexts = real_fixture(monkeypatch)
    model = isolated.bind_isolated_object_model(old, codec=options['codec'])
    before = fit(old, train, tune, options, contexts)['report']
    after = fit(model, train, tune, options, contexts)['report']
    expected = 576 * 4 * 24 + 16 * after['config']['batch_size'] * 8 * (64 + 3 * len(options['codec']['target_vocabulary'])) * 4
    assert after['tensor_work_estimate_bytes'] - before['tensor_work_estimate_bytes'] == expected
    assert not any(k.startswith('isolated_object_') for k in before)


def test_deadline_after_clipping_aborts_update_and_keeps_caller_unchanged(monkeypatch):
    model, train, tune, options, contexts = trial(monkeypatch)
    before = core.tensor_digest(model); original = torch.nn.utils.clip_grad_norm_
    calls = []
    def clip(parameters, *args, **kwargs):
        parameters = list(parameters); result = original(parameters, *args, **kwargs)
        calls.append(parameters)
        future = time.monotonic() + 100000
        monkeypatch.setattr(subject.time, 'monotonic', lambda: future)
        return result
    monkeypatch.setattr(torch.nn.utils, 'clip_grad_norm_', clip)
    monkeypatch.setattr(torch.optim.AdamW, 'step', lambda *a, **kw: pytest.fail('expired trial updated parameters'))
    result = fit(model, train, tune, options, contexts)
    assert calls and all(p.grad is None for p in calls[0])
    assert result['report']['optimizer_steps'] == result['report']['row_presentations'] == 0
    assert core.tensor_digest(model) == before


def test_mutated_actual_context_binding_fails_before_training(monkeypatch):
    model, train, tune, options, contexts = trial(monkeypatch)
    contexts = deepcopy(contexts)
    contexts['train'].pop(train[0]['id'])
    monkeypatch.setattr(torch.optim.AdamW, 'step', lambda *a, **kw: pytest.fail('invalid source context trained'))
    with pytest.raises(ValueError): fit(model, train, tune, options, contexts)


def test_unreviewed_source_margin_whitelist_does_not_silently_accept_new_architecture(monkeypatch):
    model, train, tune, options, contexts = trial(monkeypatch)
    with pytest.raises(ValueError, match='source-margin replay requires ordered'):
        fit(model, train, tune, options, contexts, generated_boundary_weight=.05, generated_source_margin_weight=.01)
