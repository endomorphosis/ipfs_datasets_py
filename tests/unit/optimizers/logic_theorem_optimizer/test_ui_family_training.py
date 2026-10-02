"""Actual UI family gradients, masked native targets and source split lineage."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import ui_family_training as api


@pytest.fixture
def row():
    path = Path(__file__).resolve().parents[4] / 'tests/unit/logic/formalization/autoencoder/test_ui_training_inputs.py'
    spec = importlib.util.spec_from_file_location('ui_family_native_examples', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module.native_row


def _rows(row):
    return ([row(1, 'application:one'), row(2, 'application:two'), row(5, 'application:five')],
            [row(3, 'application:three', 'validation'), row(4, 'application:four', 'validation')])


def _train(row, path, **kwargs):
    training, validation = _rows(row)
    return api.train_ui_family_autoencoder(training, validation, output_dir=path,
        epochs=3, latent_width=4, minibatch_size=2, max_seconds=30, **kwargs)


def test_real_native_ui_family_training_and_frozen_inference(row, tmp_path):
    result = _train(row, tmp_path/'ui')
    audit, descriptor = result['report'], result['descriptor']
    numerical = audit['training']
    assert numerical['training_executed'] and numerical['optimizer_steps'] > 0
    assert max(epoch['gradient_norm_max'] for epoch in numerical['history']) > 0
    assert numerical['initialization'] == 'training_only_deterministic_svd'
    assert numerical['trained_logic_families']
    assert audit['test_rows_used'] is False
    assert audit['source_text_decoder_trained'] is False
    assert audit['validation_used_for_selection'] is True
    assert len(audit['training_history']['groups']) == 3
    before = Path(descriptor['model_descriptor']['path']).read_bytes()
    inference = api.infer_ui_family_autoencoder(descriptor, [row(7, 'application:seven', 'test')])
    assert len(inference['native_inference']['latent']) == 1
    assert inference['native_inference']['formulas_generated'] is False
    assert inference['formulas_generated'] is False and inference['training_steps'] == 0
    assert Path(descriptor['model_descriptor']['path']).read_bytes() == before
    targets = json.loads((tmp_path/'ui/targets.json').read_bytes())
    assert all(report['frontier'] for report in targets['training'])
    assert all(report['ready_for_training'] for report in targets['training'])
    assert all('ui_ux_ir:interface_bindings' in {projection['projection_id'] for projection in report['projections']} for report in targets['training'])


def test_continuation_preserves_parent_and_historical_groups(row, tmp_path):
    first = _train(row, tmp_path/'parent')
    descriptor = first['descriptor']
    before = {str(path.relative_to(tmp_path/'parent')): path.read_bytes() for path in (tmp_path/'parent').rglob('*') if path.is_file()}
    _, validation = _rows(row)
    result = api.train_ui_family_autoencoder([row(6, 'application:six')], validation,
        output_dir=tmp_path/'child', parent_descriptor=descriptor, epochs=1, latent_width=4, max_seconds=30)
    assert result['report']['training']['initialization'] == 'complete_parent_structural_head'
    assert len(result['report']['training_history']['groups']) == 4
    assert before == {str(path.relative_to(tmp_path/'parent')): path.read_bytes() for path in (tmp_path/'parent').rglob('*') if path.is_file()}


@pytest.mark.parametrize('kind', ['group', 'source'])
def test_current_group_and_source_leakage_rejected_before_training(row, tmp_path, monkeypatch, kind):
    train, validation = _rows(row)
    if kind == 'group': validation[0]['provenance']['group_id'] = train[0]['provenance']['group_id']
    else: validation[0]['provenance']['row_id'] = train[0]['provenance']['row_id']
    monkeypatch.setattr(api.numerical, 'train_family_projection_autoencoder', lambda *a, **kw: pytest.fail('leak reached optimizer'))
    with pytest.raises(ValueError, match='leakage'):
        api.train_ui_family_autoencoder(train, validation, output_dir=tmp_path/'bad')
    assert not (tmp_path/'bad').exists()


def test_historical_validation_cannot_become_training(row, tmp_path):
    first = _train(row, tmp_path/'parent')
    _, validation = _rows(row)
    disguised = row(8, 'application:three')
    with pytest.raises(ValueError, match='leakage'):
        api.train_ui_family_autoencoder([disguised], validation, output_dir=tmp_path/'bad', parent_descriptor=first['descriptor'])


def test_fixed_validation_panel_required(row, tmp_path):
    first = _train(row, tmp_path/'parent')
    with pytest.raises(ValueError, match='original validation'):
        api.train_ui_family_autoencoder([row(6, 'application:six')], [row(8, 'application:eight', 'validation')],
            output_dir=tmp_path/'bad', parent_descriptor=first['descriptor'])


@pytest.mark.parametrize('role', ['test', 'canary'])
def test_non_training_roles_never_fit(row, tmp_path, role):
    train, validation = _rows(row); train[0]['provenance']['split'] = role
    with pytest.raises(ValueError, match='split|test/canary'):
        api.train_ui_family_autoencoder(train, validation, output_dir=tmp_path/'bad')


def test_requested_native_family_subset_is_real_training(row, tmp_path):
    result = _train(row, tmp_path/'subset', requested_families=['frame_logic'])
    assert result['report']['training']['trained_logic_families'] == ['frame_logic']
    assert api.infer_ui_family_autoencoder(result['descriptor'], [row(9)])['native_inference']['families'].keys() == {'frame_logic'}


def test_unavailable_family_cannot_be_a_fake_label(row, tmp_path):
    with pytest.raises(ValueError, match='no validated native projection'):
        _train(row, tmp_path/'missing', requested_families=['separation_logic'])


def test_parent_artifact_and_target_tampering_rejected(row, tmp_path):
    first = _train(row, tmp_path/'parent')
    path = tmp_path/'parent/targets.json'; path.write_bytes(path.read_bytes() + b' ')
    with pytest.raises(ValueError, match='target receipt drift'):
        api.infer_ui_family_autoencoder(first['descriptor'], [row(8)])


def test_unverified_interface_join_cannot_reach_numerical_training(row, tmp_path, monkeypatch):
    training, validation = _rows(row)
    training[0]['bindings'][0]['method_name'] = 'invented_method'
    monkeypatch.setattr(api.numerical, 'train_family_projection_autoencoder', lambda *a, **kw: pytest.fail('invalid UI reached optimizer'))
    with pytest.raises(ValueError, match='unknown interface method'):
        api.train_ui_family_autoencoder(training, validation, output_dir=tmp_path/'bad')
