from copy import deepcopy
import hashlib
import random

import pytest

from scripts.ops.legal_ir import summarize_legal_mixed_replay_experiment as subject


def stages(old0=95, new0=50, old1=95, new1=50):
    return [{'steps': 400, 'earlier_exact': old0, 'new_exact': new0},
            {'steps': 800, 'earlier_exact': old1, 'new_exact': new1}]


def test_retention_rejects_new_only_win_and_prefers_earliest_exact_tie():
    assert subject.retention_choice(stages(old1=94, new1=96), 96)['steps'] == 400
    assert subject.retention_choice(stages(), 96)['steps'] == 400
    assert subject.retention_choice(stages(old1=96), 96)['steps'] == 800
    assert subject.retention_choice(stages(new1=51), 96)['steps'] == 800
    assert subject.retention_choice(stages(old0=94, old1=93), 96) is None


@pytest.mark.parametrize('mutation', ['test_metric', 'duplicate_stage', 'wrong_tolerance', 'bool_metric'])
def test_retention_closed_tuning_only_contract(mutation):
    rows = stages()
    tolerance = 1
    if mutation == 'test_metric': rows[0]['fresh_exact'] = 144
    if mutation == 'duplicate_stage': rows[1]['steps'] = 400
    if mutation == 'wrong_tolerance': tolerance = 2
    if mutation == 'bool_metric': rows[0]['new_exact'] = True
    with pytest.raises(ValueError):
        subject.retention_choice(rows, 96, tolerance=tolerance)


def inventory():
    items = [{'name': f'{arm}-{seed}', 'decoder_kind': 'mixed', 'enabled': enabled}
             for arm, enabled in subject.ARMS.items() for seed in subject.SEEDS]
    items += [{'name': f'parent-{seed}', 'decoder_kind': 'parent', 'enabled': False} for seed in subject.SEEDS]
    files = {r['name']: {panel: {} for panel in subject.PANEL_COUNTS} for r in items}
    for row in items:
        if row['enabled']: files[row['name']]['fresh_disabled'] = {}
    return items, files


def test_inventory_counts_parent_and_fallback_as_separate_slots():
    items, files = inventory()
    assert subject.verify_panel_inventory(items, files) == 6534
    for row in items:
        if row['name'].startswith('mixed_grounding'):
            row.update(decoder_kind='parent', enabled=False)
            files[row['name']].pop('fresh_disabled')
    assert subject.verify_panel_inventory(items, files) == 6102


@pytest.mark.parametrize('mutation', ['control', 'parent', 'candidate_test', 'duplicate_slot'])
def test_inventory_rejects_missing_or_unplanned_generation(mutation):
    items, files = inventory()
    if mutation == 'control': files['mixed_grounding-1729'].pop('fresh_disabled')
    if mutation == 'parent': files.pop('parent-1730')
    if mutation == 'candidate_test': files['unselected-stage-400'] = {}
    if mutation == 'duplicate_slot': items[-1] = items[-2]
    with pytest.raises(ValueError): subject.verify_panel_inventory(items, files)


def batch_fixture(enabled=False, start=400):
    training = [{'id': f'{domain}-{i}', 'domain': domain} for domain, count in [('earlier', 13), ('new', 7)] for i in range(count)]
    pools = {domain: [r for r in training if r['domain'] == domain] for domain in ('earlier', 'new')}
    before = {'progress': {'optimizer_steps': start}, 'model_state': {'source': [0.], 'actor_boundary.weight': [0.]}}
    finish = start + 400
    checkpoint = {'progress': {'optimizer_steps': finish, 'pools': {}}, 'model_state': {'source': [1.], 'actor_boundary.weight': [float(enabled)]},
                  'config': {'seed': 1729, 'trigger_loss_weight': .25, 'actor_loss_weight': .25}}
    for domain, rows in pools.items():
        epochs, cursor = divmod(finish * 6, len(rows))
        order = list(range(len(rows)))
        random.Random(f'mixed-replay/v1:1729:{domain}:{epochs}').shuffle(order)
        checkpoint['progress']['pools'][domain] = {'epochs_completed': epochs, 'row_cursor': cursor, 'shuffle_order': order}
    parts = {'semantic': 2., 'semantic_earlier': 1., 'semantic_new': 3.,
             'trigger': float(enabled), 'actor': float(enabled), 'actor_earlier': float(enabled), 'actor_new': float(enabled),
             'domain_rows': {'earlier': 6, 'new': 6}, 'supervised_trigger_rows': 6,
             'trigger_loss_rows': 6 if enabled else 0, 'actor_loss_rows_by_domain': {'earlier': 6 if enabled else 0, 'new': 6 if enabled else 0}}
    exposure = []
    # Independent test stream concatenates full shuffled epochs, then slices batches.
    streams = {}
    for domain, rows in pools.items():
        stream = []
        for epoch in range(finish * 6 // len(rows) + 1):
            order = list(range(len(rows)))
            random.Random(f'mixed-replay/v1:1729:{domain}:{epoch}').shuffle(order)
            stream.extend(order)
        streams[domain] = stream
    for step in range(start + 1, finish + 1):
        indices = {domain: stream[(step - 1) * 6:step * 6] for domain, stream in streams.items()}
        exposure.append({'optimizer_step': step, 'indices_by_domain': indices,
                         'ids_by_domain': {d: [pools[d][i]['id'] for i in ix] for d, ix in indices.items()}})
    report = {'optimizer_steps': 400, 'training_executed': True, 'new_optimizer_steps_total': finish,
              'stopped_reason': 'step_limit', 'checkpoint_sha256': subject.digest(checkpoint),
              'domain_exposures': {'earlier': 2400, 'new': 2400}, 'batch_exposures': exposure,
              'batch_loss_components': [deepcopy(parts) for _ in exposure], 'batch_losses': [2.5 if enabled else 2.] * 400,
              'changed_parameter_names': ['source', 'actor_boundary.weight'] if enabled else ['source'],
              'auxiliary_gradient_norm_max': {'actor_boundary': float(enabled)}}
    return report, before, checkpoint, training


@pytest.mark.parametrize('enabled', [False, True])
def test_exact_resumed_batch_stream_wrap_and_balanced_masks(enabled):
    report, before, cp, training = batch_fixture(enabled)
    result = subject.verify_batch_report(report, before, cp, training, enabled=enabled)
    assert result['unique_domain_rows_seen_this_stage'] == {'earlier': 13, 'new': 7}
    assert result['six_plus_six_and_missing_trigger_mask_verified'] is True
    assert result['optimizer_trajectory_replayed'] is False


@pytest.mark.parametrize('mutation', ['id', 'index', 'step', 'missing', 'old_trigger', 'unequal_weight', 'total', 'nan', 'duplicate_parameter', 'cursor', 'disabled_gradient'])
def test_batch_audit_rejects_exposure_mask_progress_and_objective_mutants(mutation):
    report, before, cp, training = batch_fixture()
    if mutation == 'id': report['batch_exposures'][0]['ids_by_domain']['earlier'][0] = 'new-0'
    if mutation == 'index': report['batch_exposures'][0]['indices_by_domain']['new'][0] = 999
    if mutation == 'step': report['batch_exposures'][0]['optimizer_step'] = 1
    if mutation == 'missing': report['batch_exposures'].pop()
    if mutation == 'old_trigger': report['batch_loss_components'][0]['supervised_trigger_rows'] = 12
    if mutation == 'unequal_weight': report['batch_loss_components'][0]['semantic'] = 1.5
    if mutation == 'total': report['batch_losses'][0] = 3.
    if mutation == 'nan': report['batch_loss_components'][0]['semantic_new'] = float('nan')
    if mutation == 'duplicate_parameter': report['changed_parameter_names'] *= 2
    if mutation == 'cursor':
        cp['progress']['pools']['new']['row_cursor'] += 1
        report['checkpoint_sha256'] = subject.digest(cp)
    if mutation == 'disabled_gradient': report['auxiliary_gradient_norm_max']['actor_boundary'] = .1
    with pytest.raises(ValueError): subject.verify_batch_report(report, before, cp, training, enabled=False)


def test_annotation_metrics_do_not_invent_missing_trigger_accuracy():
    source = {'id': 'a', 'source_text': 'Clerk must file.'}
    source['source_sha256'] = hashlib.sha256(source['source_text'].encode()).hexdigest()
    reference = {'id': 'a', 'canonical_ir': {'rules': [{'modality': 'O'}]}, 'facet_spans': {'actor': [0, 5]}, 'trigger_span': None}
    row = {'source_sha256': source['source_sha256'], 'status': 'abstained', 'canonical_ir': None,
           'target_access': False, 'teacher_forcing': False,
           'span_diagnostics': {'facets': {'actor': {'char_start': 0, 'char_end': 5}}}}
    result = subject.annotated_metrics({'rows': [row]}, [source], [reference], supervised_trigger=False)
    assert result['count'] == result['abstained'] == result['actor_span_exact'] == 1
    assert result['actor_span_exact_on_decoded'] == result['trigger_annotated_count'] == 0
    assert result['trigger_span_exact'] is None and result['modality_confusion'] == {'O->abstained': 1}
    reference['trigger_span'] = [6, 10]
    row['grounding_diagnostics'] = {'trigger': {'char_start': 6, 'char_end': 10}}
    result = subject.annotated_metrics({'rows': [row]}, [source], [reference], supervised_trigger=True)
    assert result['trigger_annotated_count'] == result['trigger_span_exact'] == 1


def test_fitting_provenance_rejects_relabelled_old_trigger_and_facet(tmp_path):
    old = {'id': 'old', 'source_text': 'A must file if active.', 'canonical_ir': {},
           'source_spans': {'actor': [0, 1], 'action': [7, 11], 'object': [], 'conditions': [[15, 21]], 'exceptions': [], 'temporal': []}}
    new = {'id': 'new', 'source_text': 'B may file.', 'canonical_ir': {}, 'trigger_span': [2, 5],
           'facet_spans': {'actor': [0, 1], 'action': [6, 10], 'object': None, 'conditions': None, 'exceptions': None, 'temporal': None}}
    oldref = subject.write(tmp_path / 'old.json', {'splits': {'train': [old], 'tuning': [old]}})
    newrows = subject.write(tmp_path / 'newrows.json', [new])
    newref = subject.write(tmp_path / 'new.json', {'artifacts': {'train': newrows, 'tuning': newrows}})
    expected = {k: old[k] for k in ('id', 'source_text', 'canonical_ir')}
    expected.update(domain='earlier', trigger_span=None, trigger_supervised=False,
        facet_spans={'actor': [0, 1], 'action': [7, 11], 'object': None, 'conditions': [15, 21], 'exceptions': None, 'temporal': None})
    mixednew = dict(new, domain='new', trigger_supervised=True)
    inputs = {'manifest': {'inputs': {'earlier_corpus': oldref, 'new_curriculum': newref}},
              'training': [expected, mixednew], 'tuning': {'earlier': [deepcopy(expected)], 'new': [mixednew]}}
    assert subject.verify_fitting_provenance(inputs)['earlier_trigger_labels_synthesized'] is False
    for key, value in [('trigger_span', [2, 6]), ('facet_spans', dict(expected['facet_spans'], actor=[0, 2]))]:
        changed = deepcopy(inputs); changed['training'][0][key] = value
        with pytest.raises(ValueError, match='original frozen'): subject.verify_fitting_provenance(changed)
