from copy import deepcopy
import pytest

from scripts.ops.legal_ir import summarize_legal_temporal_curriculum_experiment as subject


def stages(a=(95, 50, 80), b=(95, 50, 80)):
    return [{'steps': step, 'earlier_exact': values[0], 'prior_new_exact': values[1], 'temporal_exact': values[2]}
            for step, values in zip((400, 800), (a, b))]


def test_retention_uses_temporal_then_prior_new_then_earlier_then_earliest():
    assert subject.retention_choice(stages(), 96)['steps'] == 400
    assert subject.retention_choice(stages(b=(96, 50, 80)), 96)['steps'] == 800
    assert subject.retention_choice(stages(a=(96, 50, 80), b=(95, 51, 80)), 96)['steps'] == 800
    assert subject.retention_choice(stages(a=(96, 96, 80), b=(95, 0, 81)), 96)['steps'] == 800
    assert subject.retention_choice(stages(b=(94, 96, 120)), 96)['steps'] == 400
    assert subject.retention_choice(stages(a=(94, 96, 120), b=(93, 96, 120)), 96) is None


@pytest.mark.parametrize('mutation', ['challenge', 'bool_metric', 'oversize', 'duplicate_stage'])
def test_retention_rejects_reference_or_invalid_tuning_inputs(mutation):
    rows = stages()
    if mutation == 'challenge': rows[0]['fresh_exact'] = 180
    elif mutation == 'bool_metric': rows[0]['temporal_exact'] = True
    elif mutation == 'oversize': rows[0]['temporal_exact'] = 121
    else: rows[1]['steps'] = 400
    with pytest.raises(ValueError): subject.retention_choice(rows, 96)


def inventory():
    items = [{'name': f'{arm}-{seed}', 'decoder_kind': 'mixed', 'enabled': config['enabled']}
             for arm, config in subject.ARMS.items() for seed in subject.SEEDS]
    items += [{'name': f'parent-{seed}', 'decoder_kind': 'parent', 'enabled': False} for seed in subject.SEEDS]
    files = {r['name']: {panel: {} for panel in subject.PANEL_COUNTS} for r in items}
    for row in items:
        if row['enabled']: files[row['name']]['fresh_disabled'] = {}
    return items, files


def test_complete_inventory_and_parent_fallback_aliases_keep_all_slots():
    items, files = inventory()
    assert subject.verify_panel_inventory(items, files) == 15750
    for item in items:
        if item['enabled']:
            item.update(decoder_kind='parent', enabled=False)
            files[item['name']].pop('fresh_disabled')
    assert subject.verify_panel_inventory(items, files) == 14670
    assert len(items) == 15


@pytest.mark.parametrize('mutation', ['control', 'regression', 'parent', 'candidate_challenge', 'duplicate_slot'])
def test_inventory_rejects_dropped_or_unplanned_work(mutation):
    items, files = inventory()
    if mutation == 'control': files['temporal_augmented_grounding-1729'].pop('fresh_disabled')
    elif mutation == 'regression': files['baseline_continuation-1729'].pop('mixed_regression')
    elif mutation == 'parent': files.pop('parent-1731')
    elif mutation == 'candidate_challenge': files['unselected-400'] = {}
    else: items[-1] = items[-2]
    with pytest.raises(ValueError): subject.verify_panel_inventory(items, files)


@pytest.mark.parametrize('field', ['model_state', 'optimizer_state', 'progress'])
def test_numeric_baseline_identity_detects_optimizer_and_sampler_drift(field):
    historical = {'model_state': {'weights': [1.]}, 'optimizer_state': {'exp_avg': [0.5]}, 'progress': {'step': 400}, 'tuning_count': 192}
    current = deepcopy(historical); current['tuning_count'] = 312
    result = subject.compare_baseline_stage(current, historical)
    assert set(result) == {key + '_sha256' for key in ('model_state', 'optimizer_state', 'progress')}
    current[field] = {'changed': True}
    with pytest.raises(ValueError, match='numeric checkpoint'): subject.compare_baseline_stage(current, historical)


def test_exposure_distinguishes_old_new_training_examples_from_temporal_additions():
    rows = [{'id': 'old', 'domain': 'earlier'}, {'id': 'prior', 'domain': 'new'}, {'id': 'temporal', 'domain': 'new'}]
    report = {'batch_exposures': [{'indices_by_domain': {'new': [0, 0, 0, 1, 1, 1]}} for _ in range(400)]}
    assert subject.subgroup_exposure(report, rows, ['old', 'prior']) == {'prior_new': 1200, 'temporal_additions': 1200}
    report['batch_exposures'].pop()
    with pytest.raises(ValueError, match='exposure'): subject.subgroup_exposure(report, rows, ['old', 'prior'])


def provenance_fixture(tmp_path):
    baseline = [{'id': 'earlier', 'domain': 'earlier', 'trigger_span': None, 'trigger_supervised': False},
                {'id': 'prior-new', 'domain': 'new', 'trigger_span': [1, 2], 'trigger_supervised': True}]
    temporal = [{'id': f'temporal-{i}', 'domain': 'new', 'trigger_span': [1, 2], 'trigger_supervised': True} for i in range(600)]
    earlier, newer = [dict(baseline[0], id='earlier-tune')], [dict(baseline[1], id='prior-new-tune')]
    old = subject.write(tmp_path / 'mixed.json', {'artifacts': {
        'train': subject.write(tmp_path / 'train.json', baseline),
        'tuning_earlier': subject.write(tmp_path / 'earlier.json', earlier),
        'tuning_new': subject.write(tmp_path / 'newer.json', newer)}})
    added = subject.write(tmp_path / 'temporal.json', temporal)
    return {'manifest': {'inputs': {'mixed_corpus': old}, 'artifacts': {'temporal_training': added}},
            'training': {'baseline': baseline, 'temporal_augmented': deepcopy(baseline) + temporal},
            'tuning': {'earlier': earlier, 'prior_new': newer, 'temporal': [{'id': 'temporal-tune'}]}}


def test_provenance_rejoins_order_and_calls_inherited_coordinate_audit(tmp_path, monkeypatch):
    inputs = provenance_fixture(tmp_path)
    calls = []
    monkeypatch.setattr(subject.prior, 'verify_fitting_provenance', lambda payload: calls.append(payload) or {'verified': True})
    result = subject.verify_fitting_provenance(inputs)
    assert result['appended_temporal_rows'] == 600 and result['earlier_trigger_labels_synthesized'] is False
    assert calls[0]['training'] == inputs['training']['baseline']
    assert calls[0]['tuning']['new'] == inputs['tuning']['prior_new']


@pytest.mark.parametrize('mutation', ['old_trigger', 'baseline_order', 'append_omitted', 'append_reordered', 'prior_tune'])
def test_provenance_rejects_changed_inherited_rows_or_augmented_composition(tmp_path, monkeypatch, mutation):
    inputs = provenance_fixture(tmp_path)
    monkeypatch.setattr(subject.prior, 'verify_fitting_provenance', lambda payload: {'verified': True})
    if mutation == 'old_trigger': inputs['training']['baseline'][0]['trigger_span'] = [0, 1]
    elif mutation == 'baseline_order': inputs['training']['baseline'].reverse()
    elif mutation == 'append_omitted': inputs['training']['temporal_augmented'].pop()
    elif mutation == 'append_reordered': inputs['training']['temporal_augmented'][-2:] = inputs['training']['temporal_augmented'][-2:][::-1]
    else: inputs['tuning']['prior_new'][0]['id'] = 'different'
    with pytest.raises(ValueError): subject.verify_fitting_provenance(inputs)
