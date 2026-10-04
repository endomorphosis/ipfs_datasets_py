"""Joint generated-field trainer contracts; synthetic checks grant no admission."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core
from .test_ordered_clause_recurrent_training_runner import real_fixture
from .test_context_boundary_training_runner import fake_context_boundary

ROOT = Path(__file__).resolve().parents[5]
SPEC = importlib.util.spec_from_file_location('_generated_field_runner_tests',
    ROOT/'scripts/ops/autoencoder/benchmark_generated_field_training.py')
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)


@pytest.mark.parametrize('field,value', [
    ('generated_field_names', ['actor', 'action']), ('generated_field_site_cap_per_row', 1),
    ('generated_field_policy', 'first_wrong_overall'), ('joint_generated_prefix_replay', False),
    ('generated_field_labels_after_source_only_rollout', False), ('fit_count', 12),
    ('fixed_encoder_context_tokens', 1024), ('fixed_decoder_output_limit', 1024),
    ('temperature', .1), ('full_vocabulary_retained', False), ('syntax_forced', True),
    ('closure_forced', True), ('generation_reference_count_access', True),
    ('fresh_initialization', False), ('selection_unchanged', False),
    ('generated_fields_max_memory_bytes', 1073741824), ('boundary_max_memory_bytes', 2147483648),
    ('baseline_equivalence_exclusions', ['elapsed_seconds', 'history']),
    ('generated_replay_strategy', 'bulk_with_relaxed_tolerance'),
    ('generated_replay_retry_limit_per_original_batch', 2),
    ('generated_replay_atol', 1e-4), ('generated_replay_rtol', 1e-4),
])
def test_fixed_plan_preserves_fields_limits_and_original_gates(field, value):
    plan = deepcopy(subject.FIXED)
    subject.validate_plan(plan)
    plan[field] = value
    with pytest.raises(ValueError, match='fixed generated-field'):
        subject.validate_plan(plan)


def test_eighteen_jobs_keep_boundary_objective_and_vary_only_field_loss_or_cadence():
    jobs = subject.jobs()
    assert [(dimension, seed, arm['name']) for dimension, seed, arm in jobs] == [
        (dimension, seed, name) for dimension in (8, 384, 768) for seed in (1729, 2718)
        for name in ('boundary-first-last', 'generated-fields', 'generated-fields-every2')]
    assert [(arm['generated_field_weight'], arm['generated_site_interval']) for _, _, arm in jobs[:3]] == [
        (0., 1), (.05, 1), (.05, 2)]
    assert all(arm['generated_boundary_weight'] == .05 and arm['generated_boundary_site_policy'] == 'first_last'
        and arm['action_contrastive_weight'] == .05 and arm['recurrent'] for _, _, arm in jobs)
    jobs[0][2]['generated_field_weight'] = .9
    assert subject.jobs()[0][2]['generated_field_weight'] == 0.


def replay_fixture():
    boundary = dict(elapsed_seconds=1., collection_sha256='time-dependent',
        generation=dict(elapsed_seconds=2., rows=[dict(id='t', consumed_prefix=[1, 3],
            available_sites=[dict(position=1, actual_next_token_id=4, collection_logits=[.2, .4])])]),
        events=[dict(target_token_id=4, cross_entropy=.5)], mean_loss=.5,
        source_contexts_sha256='source')
    report = dict(elapsed_seconds=3., committed_updates=[dict(generated_boundary=boundary, objective=.75)],
        selected_weights_sha256='selected', last_complete_attempt_weights_sha256='final',
        history=[dict(accepted=False, selected_epoch=0)], config=dict(max_memory_bytes=1073741824))
    panels = {role: {label: dict(predictions=[dict(id='v', token_ids=[3])])
        for label in [*[row[0] for row in subject.CONTROLS], 'recurrent-residual-off']}
        for role in ('selected', 'last-attempt')}
    context = dict(core=core, dimension=8,
        baseline_runs={'8-boundary-first-last-1729': dict(training=deepcopy(report), postfit=deepcopy(panels))})
    return context, report, panels


def test_baseline_replay_excludes_only_declared_timing_and_its_digest():
    context, report, panels = replay_fixture()
    original = deepcopy(report)
    report['elapsed_seconds'] = 99.
    receipt = report['committed_updates'][0]['generated_boundary']
    receipt['elapsed_seconds'] = 100.
    receipt['generation']['elapsed_seconds'] = 101.
    receipt['collection_sha256'] = 'changed-time-digest'
    expected = deepcopy(report)
    assert subject.validate_baseline(context, report, panels, 1729)['complete']
    assert report == expected
    assert context['baseline_runs']['8-boundary-first-last-1729']['training'] == original


@pytest.mark.parametrize('change', [
    lambda report: report.update(selected_weights_sha256='changed'),
    lambda report: report['history'][0].update(accepted=True),
    lambda report: report['config'].update(max_memory_bytes=2147483648),
    lambda report: report['committed_updates'][0].update(objective=.7),
    lambda report: report['committed_updates'][0]['generated_boundary'].update(mean_loss=.6),
    lambda report: report['committed_updates'][0]['generated_boundary'].update(source_contexts_sha256='changed'),
    lambda report: report['committed_updates'][0]['generated_boundary']['events'][0].update(target_token_id=3),
    lambda report: report['committed_updates'][0]['generated_boundary']['generation']['rows'][0].update(consumed_prefix=[1, 5]),
    lambda report: report['committed_updates'][0]['generated_boundary']['generation']['rows'][0]['available_sites'][0].update(collection_logits=[.1, .4]),
])
def test_baseline_replay_cannot_hide_numerical_or_source_changes(change):
    context, report, panels = replay_fixture()
    change(report)
    with pytest.raises(ValueError, match='numerical report replay differs'):
        subject.validate_baseline(context, report, panels, 1729)


@pytest.mark.parametrize('role', ['selected', 'last-attempt'])
def test_baseline_replay_still_compares_residual_off_predictions(role):
    context, report, panels = replay_fixture()
    panels[role]['recurrent-residual-off']['predictions'][0]['token_ids'] = [8]
    with pytest.raises(ValueError, match='control predictions'):
        subject.validate_baseline(context, report, panels, 1729)


def test_runner_preserves_baseline_memory_and_caps_positive_arms():
    calls = []
    context = dict(owners={'long_span_source_value_training': SimpleNamespace(
        train=lambda *args, **kwargs: calls.append((args, kwargs)))}, rows=dict(train=[], validation=[]),
        references=dict(train=[], validation=[]), donor=dict(codec={}, input_transform={}), lineage={},
        source_contexts={}, stages=[], validate_rule=lambda rule: rule, validator_id='test')
    model = object()
    for recipe in subject.ARMS:
        subject.train_candidate(context, model, 1729, recipe)
    assert [kwargs['config']['max_memory_bytes'] for _, kwargs in calls] == [1073741824, 2147483648, 2147483648]
    common = []
    for _, kwargs in calls:
        clean = deepcopy(kwargs)
        clean.pop('generated_field_weight')
        clean.pop('generated_site_interval')
        clean['config'].pop('max_memory_bytes')
        common.append(clean)
    assert common[0] == common[1] == common[2]
    assert common[0]['config']['max_seconds'] == 180 and common[0]['config']['max_target_tokens'] == 512
    assert common[0]['generated_boundary_weight'] == .05


@pytest.fixture
def one_cpu():
    torch = pytest.importorskip('torch')
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def fit(model, train, tune, options, contexts, **extra):
    from ipfs_datasets_py.logic.formalization.autoencoder import long_span_source_value_training as trainer
    return trainer.train(model, train, tune, source_contexts=contexts,
        source_value_weight=.25, cardinality_weight=.25, count_exposure='balanced_all',
        action_contrastive_weight=.05, **options, **extra)


def fake_joint(monkeypatch, *, empty=False, expired=None):
    from ipfs_datasets_py.logic.formalization.autoencoder import generated_field_training as owner
    observed = dict(preparations=[], collections=[], losses=[])

    def prepare(rows, references, **kwargs):
        assert all(row['id'].startswith('train-') for row in rows)
        assert {row['id'] for row in references} == {row['id'] for row in rows}
        assert set(kwargs['contexts']) == {row['id'] for row in rows}
        observed['preparations'].append(deepcopy((rows, references, kwargs)))
        return dict(synthetic=True, row_ids=[row['id'] for row in rows],
            references=deepcopy(references), source_contexts=deepcopy(kwargs['contexts']))

    def collect(model, rows, **kwargs):
        assert all(set(row) == {'id', 'input', 'source_text'} and row['id'].startswith('train-') for row in rows)
        assert set(kwargs['source_contexts']) == {row['id'] for row in rows}
        assert not ({'inventory', 'references', 'training_references', 'field_policy', 'boundary_site_policy'} & set(kwargs))
        observed['collections'].append(dict(model=model, rows=deepcopy(rows), contexts=deepcopy(kwargs['source_contexts'])))
        if expired == 'collection':
            raise TimeoutError('synthetic joint collection deadline')
        return dict(rows=rows)

    def losses(torch, model, collection, inventory, **kwargs):
        assert all(row['id'] in inventory['row_ids'] for row in collection['rows'])
        assert kwargs['boundary_site_policy'] == 'first_last'
        assert set(kwargs['source_contexts']) == {row['id'] for row in collection['rows']}
        observed['losses'].append(deepcopy(kwargs))
        parameter = next(parameter for parameter in model.parameters() if parameter.requires_grad)
        if expired in ('loss', 'incremental_retry'):
            parameter.grad = torch.ones_like(parameter)
            raise TimeoutError('synthetic joint '+expired+' deadline')
        boundary = parameter.square().mean() + .125
        field = parameter.square().mean() + .375
        return dict(boundary_loss=None if empty else boundary, field_loss=None if empty else field,
            receipt=dict(synthetic=True, boundary=dict(mean_loss=None if empty else float(boundary.detach())),
                field=dict(mean_loss=None if empty else float(field.detach()), selection_policy='first_wrong_per_scalar_field'),
                row_ids=[row['id'] for row in collection['rows']]))

    monkeypatch.setattr(owner, 'prepare_training_inventory', prepare)
    monkeypatch.setattr(owner, 'collect_source_generated_sites', collect)
    monkeypatch.setattr(owner, 'generated_site_losses', losses)
    return observed


def test_zero_field_weight_preserves_existing_boundary_training(monkeypatch, one_cpu):
    from ipfs_datasets_py.logic.formalization.autoencoder import generated_field_training as owner
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    fake_context_boundary(monkeypatch)
    for function in ('prepare_training_inventory', 'collect_source_generated_sites', 'generated_site_losses'):
        monkeypatch.setattr(owner, function, lambda *args, **kwargs: pytest.fail('disabled joint helper executed'))
    plain = fit(model, train, tune, options, contexts, generated_boundary_weight=.05)
    explicit = fit(model, train, tune, options, contexts, generated_boundary_weight=.05,
        generated_field_weight=0., generated_site_interval=1)
    fields = set(plain['report']) - {'elapsed_seconds'}
    assert fields == set(explicit['report']) - {'elapsed_seconds'}
    assert all(core.digest(plain['report'][field]) == core.digest(explicit['report'][field]) for field in fields)
    assert not any(key.startswith(('generated_field_', 'generated_site_')) for key in explicit['report'])
    assert all('generated_sites' not in update for update in explicit['report']['committed_updates'])
    for role in ('state_dict', 'last_complete_attempt_state_dict'):
        assert all(value.equal(explicit[role][key]) for key, value in plain[role].items())


@pytest.mark.parametrize('bad', [True, -.1, 1.1, float('nan'), float('inf'), '.05', None])
def test_invalid_field_weight_fails_before_private_copy(monkeypatch, one_cpu, bad):
    from ipfs_datasets_py.logic.formalization.autoencoder import long_span_source_value_training as trainer
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    monkeypatch.setattr(trainer, 'deepcopy', lambda value: pytest.fail('copied before weight validation'))
    with pytest.raises(ValueError, match='generated-field weight'):
        fit(model, train, tune, options, contexts, generated_boundary_weight=.05, generated_field_weight=bad)


@pytest.mark.parametrize('bad', [True, False, 0, 33, 1.5, '2', None])
def test_invalid_cadence_fails_before_private_copy(monkeypatch, one_cpu, bad):
    from ipfs_datasets_py.logic.formalization.autoencoder import long_span_source_value_training as trainer
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    monkeypatch.setattr(trainer, 'deepcopy', lambda value: pytest.fail('copied before interval validation'))
    with pytest.raises(ValueError, match='interval'):
        fit(model, train, tune, options, contexts, generated_boundary_weight=.05,
            generated_field_weight=.05, generated_site_interval=bad)


def test_cadence_cannot_change_existing_zero_field_path(monkeypatch, one_cpu):
    from ipfs_datasets_py.logic.formalization.autoencoder import long_span_source_value_training as trainer
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    monkeypatch.setattr(trainer, 'deepcopy', lambda value: pytest.fail('copied before disabled cadence validation'))
    with pytest.raises(ValueError, match='positive field weight'):
        fit(model, train, tune, options, contexts, generated_boundary_weight=.05, generated_site_interval=2)


def test_positive_fields_require_positive_paired_boundary_loss(monkeypatch, one_cpu):
    from ipfs_datasets_py.logic.formalization.autoencoder import long_span_source_value_training as trainer
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    monkeypatch.setattr(trainer, 'deepcopy', lambda value: pytest.fail('copied before field/boundary pairing validation'))
    with pytest.raises(ValueError, match='positive all-trainable boundary loss'):
        fit(model, train, tune, options, contexts, generated_field_weight=.05)


@pytest.mark.parametrize('interval', [1, 2, 3])
def test_scheduled_joint_loss_uses_one_source_rollout_without_reweighting(monkeypatch, one_cpu, interval):
    from ipfs_datasets_py.logic.formalization.autoencoder import contextual_generated_boundary_training as prior
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    options = deepcopy(options)
    options['config'].update(max_optimizer_steps=4, validation_interval=4, epochs=4)
    options['curriculum'] = [dict(name='first', training_ids=[row['id'] for row in train], epochs=1),
        dict(name='second', training_ids=[row['id'] for row in train], epochs=3)]
    before = core.tensor_digest(model)
    original = deepcopy((train, tune, options, contexts))
    observed = fake_joint(monkeypatch)
    monkeypatch.setattr(prior, 'collect_source_boundary_prefixes',
        lambda *args, **kwargs: pytest.fail('joint update performed an extra boundary rollout'))
    result = fit(model, train, tune, options, contexts, generated_boundary_weight=.05,
        generated_field_weight=.07, generated_site_interval=interval)
    report = result['report']
    assert report['optimizer_steps'] == 4 and len(observed['preparations']) == 1
    scheduled = [index % interval == 0 for index in range(4)]
    assert len(observed['collections']) == len(observed['losses']) == sum(scheduled)
    assert report['generated_site_scheduled_updates'] == sum(scheduled)
    assert report['generated_site_skipped_updates'] == 4 - sum(scheduled)
    assert report['generated_field_policy'] == 'first_wrong_per_scalar_field'
    assert report['generated_field_used_for_selection'] is False
    assert report['generated_boundary_used_for_selection'] is False
    assert core.tensor_digest(model) == before and (train, tune, options, contexts) == original
    assert report['selection'] == 'per_length_nonregression_then_fidelity_progress_then_reference_ce'
    for index, update in enumerate(report['committed_updates']):
        envelope = update['generated_sites']
        assert envelope['zero_based_committed_step'] == index
        assert envelope['interval'] == interval and envelope['scheduled'] == scheduled[index]
        expected = update['weighted_token_ce'] + report['config']['reconstruction_weight']*update['raw_reconstruction_mse']
        expected += .25*update['count_ce'] + .25*update['source_value_ce'] + .05*update['action_contrastive']['loss']
        if scheduled[index]:
            assert envelope['skip_reason'] is None
            expected += .05*envelope['receipt']['boundary']['mean_loss'] + .07*envelope['receipt']['field']['mean_loss']
            assert envelope['receipt']['row_ids'] == update['decoder_row_ids']
        else:
            assert envelope['receipt'] is None and envelope['skip_reason'] == 'explicit_auxiliary_cadence'
        assert 'generated_boundary' not in update
        assert update['objective'] == pytest.approx(expected, abs=1e-6)


def test_empty_joint_losses_preserve_ordinary_parameter_updates(monkeypatch, one_cpu):
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    plain = fit(model, train, tune, options, contexts)
    fake_joint(monkeypatch, empty=True)
    result = fit(model, train, tune, options, contexts, generated_boundary_weight=.05,
        generated_field_weight=.05, generated_site_interval=2)
    for role in ('state_dict', 'last_complete_attempt_state_dict'):
        assert all(value.equal(result[role][key]) for key, value in plain[role].items())
    assert result['predictions'] == plain['predictions']
    assert result['last_complete_attempt_predictions'] == plain['last_complete_attempt_predictions']


def test_joint_auxiliary_objectives_cannot_override_generated_actor_regression(monkeypatch, one_cpu):
    from ipfs_datasets_py.logic.formalization.autoencoder import long_span_source_value_training as trainer
    from .test_long_span_cardinality_training import evaluated
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    fake_joint(monkeypatch)
    baseline = evaluated(options, ce=2.)
    regressed = evaluated(options, ce=.1, mutate=lambda target: target['rules'][0].update(actor='agency'))
    for panel in (baseline, regressed):
        panel['source_values'] = dict(cross_entropy=.01, predictions=[])
    panels = iter([baseline, regressed])
    monkeypatch.setattr(trainer, '_evaluate', lambda *args, **kwargs: next(panels))
    result = fit(model, train, tune, options, contexts, generated_boundary_weight=.05,
        generated_field_weight=.05)
    assert result['report']['optimizer_steps'] == 2
    assert result['report']['selected_epoch'] == 0
    assert any('actor' in reason for reason in result['report']['history'][-1]['rejection_reasons'])


@pytest.mark.parametrize('phase', ['collection', 'loss', 'incremental_retry'])
def test_joint_deadline_does_not_commit_update_or_change_cadence(monkeypatch, one_cpu, phase):
    torch = pytest.importorskip('torch')
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    observed = fake_joint(monkeypatch, expired=phase)
    monkeypatch.setattr(torch.optim.AdamW, 'step', lambda *args, **kwargs: pytest.fail('expired joint update stepped'))
    result = fit(model, train, tune, options, contexts, generated_boundary_weight=.05,
        generated_field_weight=.05, generated_site_interval=2)
    report = result['report']
    assert report['stopped_reason'] == 'deadline_during_generated_sites'
    assert report['optimizer_steps'] == report['row_presentations'] == report['count_training_row_presentations'] == 0
    assert report['generated_site_scheduled_updates'] == report['generated_site_skipped_updates'] == 0
    assert report['committed_updates'] == [] and report['selected_epoch'] == 0
    assert all(parameter.grad is None for parameter in observed['collections'][0]['model'].parameters())
    assert all(value.equal(result['state_dict'][key]) for key, value in model.state_dict().items())


def test_joint_deadline_after_backward_clears_private_gradients_without_advancing_schedule(monkeypatch, one_cpu):
    torch = pytest.importorskip('torch')
    from ipfs_datasets_py.logic.formalization.autoencoder import long_span_source_value_training as trainer
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    observed = fake_joint(monkeypatch)
    expired = [False]
    clock, clip = trainer.time.monotonic, torch.nn.utils.clip_grad_norm_

    def expire_after_clip(*args, **kwargs):
        norm = clip(*args, **kwargs)
        expired[0] = True
        return norm

    monkeypatch.setattr(trainer, 'time', SimpleNamespace(monotonic=lambda: clock() + (1000. if expired[0] else 0.)))
    monkeypatch.setattr(torch.nn.utils, 'clip_grad_norm_', expire_after_clip)
    monkeypatch.setattr(torch.optim.AdamW, 'step', lambda *args, **kwargs: pytest.fail('expired joint graph stepped'))
    result = fit(model, train, tune, options, contexts, generated_boundary_weight=.05,
        generated_field_weight=.05, generated_site_interval=2)
    report = result['report']
    assert expired[0] and report['stopped_reason'] == 'deadline'
    assert report['optimizer_steps'] == report['generated_site_scheduled_updates'] == report['generated_site_skipped_updates'] == 0
    assert report['committed_updates'] == [] and report['row_presentations'] == 0
    assert all(parameter.grad is None for parameter in observed['collections'][0]['model'].parameters())
    assert all(value.equal(result['state_dict'][key]) for key, value in model.state_dict().items())


@pytest.mark.parametrize('interval', [1, 2])
def test_tiny_real_joint_training_keeps_training_labels_out_of_rollout(monkeypatch, one_cpu, interval):
    from ipfs_datasets_py.logic.formalization.autoencoder import generated_field_training as owner
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    before = core.tensor_digest(model)
    prepare, collect, losses = owner.prepare_training_inventory, owner.collect_source_generated_sites, owner.generated_site_losses
    seen = dict(preparations=0, collections=0, receipts=[])

    def prepared(rows, references, **kwargs):
        assert {row['id'] for row in rows} == {row['id'] for row in references} == set(contexts['train'])
        assert set(kwargs['contexts']) == set(contexts['train'])
        seen['preparations'] += 1
        return prepare(rows, references, **kwargs)

    def collected(working, rows, **kwargs):
        assert all(set(row) == {'id', 'input', 'source_text'} and row['id'].startswith('train-') for row in rows)
        assert set(kwargs['source_contexts']) == {row['id'] for row in rows}
        assert not ({'inventory', 'references', 'training_references', 'boundary_site_policy'} & set(kwargs))
        seen['collections'] += 1
        return collect(working, rows, **kwargs)

    def calculated(*args, **kwargs):
        value = losses(*args, **kwargs)
        seen['receipts'].append(value['receipt'])
        return value

    monkeypatch.setattr(owner, 'prepare_training_inventory', prepared)
    monkeypatch.setattr(owner, 'collect_source_generated_sites', collected)
    monkeypatch.setattr(owner, 'generated_site_losses', calculated)
    result = fit(model, train, tune, options, contexts, generated_boundary_weight=.05,
        generated_field_weight=.05, generated_site_interval=interval)
    report = result['report']
    assert report['optimizer_steps'] == 2 and seen['preparations'] == 1
    assert seen['collections'] == len(seen['receipts']) == (2 if interval == 1 else 1)
    assert core.tensor_digest(model) == before
    for receipt in seen['receipts']:
        assert receipt['field']['fields'] == ['actor', 'action', 'modality', 'object']
        assert receipt['field']['selection_policy'] == 'first_wrong_per_scalar_field'
        assert receipt['field']['site_cap_per_row'] == 4
        assert receipt['one_union_gradient_replay_per_active_row'] and receipt['generation']['rollout_count'] == 1
        assert receipt['replay_logits_atol'] == receipt['replay_logits_rtol'] == 2e-5
        assert receipt['reference_labels_used_only_after_rollout'] and receipt['full_vocabulary_cross_entropy']
        assert not receipt['reference_documents_passed_to_model'] and not receipt['target_prefixes_used']
        assert not receipt['validation_rows_used']
        assert all(row['id'].startswith('train-') for row in receipt['generation']['rows'])
        assert all(event['actual_next_token_id'] != event['target_token_id'] for event in receipt['field']['events'])
        pairs = [(event['id'], event['field']) for event in receipt['field']['events']]
        assert len(pairs) == len(set(pairs))


def test_strict_retry_receipt_is_retained_without_second_optimizer_update(monkeypatch, one_cpu):
    from ipfs_datasets_py.logic.formalization.autoencoder import generated_field_training as owner
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    observed = fake_joint(monkeypatch)
    original_losses = owner.generated_site_losses
    retry = dict(synthetic=True, one_union_replay_per_active_row=False,
        one_union_gradient_replay_per_active_row=True, replay_logits_atol=2e-5, replay_logits_rtol=2e-5,
        bulk_replay_batch_count=1, discarded_bulk_batch_count=1, incremental_retry_batch_count=1,
        incremental_retry_forward_steps=3, bulk_attempted_row_tokens=6, retry_attempted_row_tokens=6,
        physical_replay_forward_calls=4, physical_replay_row_tokens=12,
        additional_optimizer_steps=0, replay_attempts=[
            dict(kind='bulk', parity_passed=False, used_for_loss=False),
            dict(kind='incremental_retry', parity_passed=True, used_for_loss=True)])

    def retried(*args, **kwargs):
        result = original_losses(*args, **kwargs)
        result['receipt'].update(deepcopy(retry))
        return result

    monkeypatch.setattr(owner, 'generated_site_losses', retried)
    result = fit(model, train, tune, options, contexts, generated_boundary_weight=.05,
        generated_field_weight=.07, generated_site_interval=2)
    report = result['report']
    assert report['optimizer_steps'] == 2 and len(observed['collections']) == 1
    assert report['generated_site_scheduled_updates'] == report['generated_site_skipped_updates'] == 1
    first, second = report['committed_updates']
    receipt = first['generated_sites']['receipt']
    assert all(receipt[key] == value for key, value in retry.items())
    expected = first['weighted_token_ce'] + report['config']['reconstruction_weight']*first['raw_reconstruction_mse']
    expected += .25*first['count_ce'] + .25*first['source_value_ce'] + .05*first['action_contrastive']['loss']
    expected += .05*receipt['boundary']['mean_loss'] + .07*receipt['field']['mean_loss']
    assert first['objective'] == pytest.approx(expected, abs=1e-6)
    assert second['generated_sites']['receipt'] is None and second['generated_sites']['zero_based_committed_step'] == 1


def test_unresolved_retry_parity_error_aborts_before_optimizer_step(monkeypatch, one_cpu):
    torch = pytest.importorskip('torch')
    from ipfs_datasets_py.logic.formalization.autoencoder import generated_field_training as owner
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    before = core.tensor_digest(model)
    observed = fake_joint(monkeypatch)

    def still_mismatched(*args, **kwargs):
        raise ValueError('synthetic strict incremental retry logits differ from collection')

    monkeypatch.setattr(owner, 'generated_site_losses', still_mismatched)
    monkeypatch.setattr(torch.optim.AdamW, 'step', lambda *args, **kwargs: pytest.fail('unverified replay stepped'))
    with pytest.raises(ValueError, match='strict incremental retry'):
        fit(model, train, tune, options, contexts, generated_boundary_weight=.05,
            generated_field_weight=.05, generated_site_interval=2)
    assert len(observed['collections']) == 1 and core.tensor_digest(model) == before
    assert all(parameter.grad is None for parameter in model.parameters())
