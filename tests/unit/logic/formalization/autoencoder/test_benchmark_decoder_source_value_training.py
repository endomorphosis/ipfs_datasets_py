"""Experiment boundary, source authentication and unchanged-control guards."""
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
SPEC = importlib.util.spec_from_file_location(
    'source_value_benchmark_test',
    ROOT / 'scripts/ops/autoencoder/benchmark_decoder_source_value_training.py')
driver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(driver)


@pytest.mark.parametrize('key,value', [
    ('fixed_encoder_context_tokens', 1024), ('fixed_decoder_output_limit', 1024),
    ('selection_unchanged', False), ('projection_frozen', False),
    ('source_value_max_rules', 16), ('source_value_full_vocabulary', False),
    ('generation_reference_count_access', True), ('generation_reference_prefix_access', True),
    ('expected_optimizer_steps_per_arm', 341), ('temperature', 1),
    ('expected_source_value_presentations_per_candidate', 24960),
    ('expected_optimizer_steps_per_arm', True), ('seed_order', [1729]),
    ('postfit_controls', driver.CONTROLS[:-1]), ('native_qualification', True),
])
def test_fixed_experiment_rejects_changed_semantics_and_budget(key, value):
    plan = deepcopy(driver.FIXED)
    driver.validate_plan(plan)
    plan[key] = value
    with pytest.raises(ValueError, match='unsupported fixed'):
        driver.validate_plan(plan)


def prior_report():
    return dict(optimizer_steps=340, row_presentations=2440,
        valid_target_token_presentations=225840, selected_epoch=0,
        initial_weights_sha256='initial', selected_weights_sha256='initial',
        last_complete_attempt_weights_sha256='last', count_training_row_presentations=2440,
        count_training_presentations_by_class={'1':610, '2':610, '4':610, '8':610},
        count_mean_loss_exposure_by_class={'1':76.25, '2':76.25, '4':76.25, '8':76.25},
        committed_count_batch_ids_sha256='batches', stopped_reason='epochs_completed',
        history=[dict(epoch=4, stage='short', stage_epoch=4, optimizer_steps=8,
            learning_rate=.001, numerical={'cross_entropy':.3}, source_count={'correct':12},
            source_fidelity={'exact':0}, accepted=False,
            rejection_reasons=['source fidelity regressed'], selected_epoch=0)])


def test_historical_parity_ignores_timing_and_auxiliary_diagnostics_only():
    prior = prior_report()
    actual = deepcopy(prior)
    actual.update(elapsed_seconds=99, source_values={'correct':500})
    actual['history'][0]['source_values'] = {'correct':500}
    assert driver.historical_parity(actual, prior)['complete']


@pytest.mark.parametrize('key,value', [
    ('selected_epoch', 4), ('last_complete_attempt_weights_sha256', 'changed'),
    ('committed_count_batch_ids_sha256', 'different-batches'), ('optimizer_steps', 339),
    ('valid_target_token_presentations', 225839), ('stopped_reason', 'deadline'),
])
def test_historical_parity_rejects_state_exposure_and_completion_drift(key, value):
    prior = prior_report(); actual = deepcopy(prior); actual[key] = value
    with pytest.raises(ValueError, match='differs from historical control'):
        driver.historical_parity(actual, prior)


@pytest.mark.parametrize('key,value', [
    ('accepted', True), ('rejection_reasons', []), ('source_count', {'correct':13}),
    ('source_fidelity', {'exact':1}), ('learning_rate', .0005),
])
def test_historical_parity_rejects_gate_and_metric_history_drift(key, value):
    prior = prior_report(); actual = deepcopy(prior); actual['history'][0][key] = value
    with pytest.raises(ValueError, match='validation_and_selection_history'):
        driver.historical_parity(actual, prior)


def test_helper_authentication_precedes_code_execution(tmp_path):
    source = tmp_path / 'helper.py'
    marker = tmp_path / 'executed'
    source.write_text('from pathlib import Path\nPath(' + repr(str(marker)) + ').touch()\n')
    with pytest.raises(ValueError, match='frozen benchmark helper differs'):
        driver.load_helper(tmp_path, {'helper.py':'incorrect'}, 'helper.py', 'bad_helper')
    assert not marker.exists()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    driver.load_helper(tmp_path, {'helper.py':digest}, 'helper.py', 'good_helper')
    assert marker.exists()
