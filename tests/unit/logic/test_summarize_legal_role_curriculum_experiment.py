from copy import deepcopy
import json
import hashlib
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.ops.legal_ir import summarize_legal_role_curriculum_experiment as q


def selection():
    parent = {'earlier': 50, 'temporal': 60, 'prior_consistency': 40,
              'document_parent': 20, 'document_expanded': 30}
    stages = [{'steps': step, **parent, 'new': 70, 'guard_parent': 0, 'guard_expanded': 0}
              for step in (200, 400)]
    return parent, stages


def test_selection_prefers_earliest_only_after_all_tuning_ranks_tie():
    parent, stages = selection()
    assert q.selection_choice(stages, parent)['steps'] == 200
    stages[1]['new'] += 1
    assert q.selection_choice(stages, parent)['steps'] == 400


@pytest.mark.parametrize('panel', ['earlier', 'temporal', 'prior_consistency', 'document_parent', 'document_expanded'])
def test_every_retention_gate_is_binding_even_when_new_tuning_improves(panel):
    parent, stages = selection()
    stages[1]['new'] += 10; stages[1][panel] = parent[panel] - 2
    assert q.selection_choice(stages, parent)['steps'] == 200
    stages[1][panel] += 1
    assert q.selection_choice(stages, parent)['steps'] == 400


@pytest.mark.parametrize('guard', ['guard_parent', 'guard_expanded'])
def test_guard_acceptance_disqualifies_without_hiding_parent_fallback(guard):
    parent, stages = selection()
    for stage in stages: stage[guard] = 1
    assert q.selection_choice(stages, parent) is None


def test_prior_consistency_retention_is_not_an_unregistered_tiebreaker():
    parent, stages = selection()
    stages[1]['prior_consistency'] += 5
    assert q.selection_choice(stages, parent)['steps'] == 200


@pytest.mark.parametrize('mutation', ['bool_metric', 'extra_metric', 'missing_stage', 'negative_count', 'fresh_selection'])
def test_selection_rejects_malformed_or_unregistered_metrics(mutation):
    parent, stages = selection()
    if mutation == 'bool_metric': stages[0]['new'] = True
    if mutation == 'extra_metric': stages[0]['accuracy'] = 1
    if mutation == 'missing_stage': stages.pop()
    if mutation == 'negative_count': stages[0]['new'] = -1
    if mutation == 'fresh_selection': stages[0]['fresh_exact'] = 144
    with pytest.raises(ValueError): q.selection_choice(stages, parent)


def pair_fixture():
    canonical = {'rules': [{'modality': 'O', 'actor': 'registrar', 'action': 'archive', 'object': 'notice',
                           'conditions': [], 'exceptions': [], 'temporal': []}]}
    rows = [{'id': f'row-{i}', 'source_text': text, 'canonical_ir': deepcopy(canonical), 'domain': 'new',
             'trigger_supervised': True, 'trigger_span': [1, 2]}
            for i, text in enumerate(('The registrar shall archive the notice.', 'The registrar must archive the notice.'))]
    pairs = [{'pair_id': 'pair-0', 'case_group': 'case-0', 'left_id': 'row-0', 'right_id': 'row-1',
              'canonical_ir_sha256': q.digest(canonical)}]
    return rows, pairs


def test_one_semantic_pair_per_case_is_valid_without_contrastive_pair_assumption():
    rows, pairs = pair_fixture()
    assert q.verify_pairs(rows, pairs)['pairs'] == 1


@pytest.mark.parametrize('mutation', ['meaning', 'missing', 'duplicate', 'trigger', 'hash', 'same_source'])
def test_semantically_inconsistent_or_incomplete_pairs_rejected(mutation):
    rows, pairs = pair_fixture()
    if mutation == 'meaning': rows[1]['canonical_ir']['rules'][0]['exceptions'] = ['waiver']
    if mutation == 'missing': rows.pop()
    if mutation == 'duplicate': pairs[0]['right_id'] = pairs[0]['left_id']
    if mutation == 'trigger': rows[0]['trigger_supervised'] = False
    if mutation == 'hash': pairs[0]['canonical_ir_sha256'] = '0' * 64
    if mutation == 'same_source': rows[1]['source_text'] = rows[0]['source_text']
    with pytest.raises(ValueError): q.verify_pairs(rows, pairs)


def report_fixture():
    replay = {name: [{'id': f'{name}-{i}'} for i in range(6)]
              for name in ('earlier', 'prior_new', 'temporal', 'prior_consistency')}
    pairs = [{'left_id': f'left-{i}', 'right_id': f'right-{i}'} for i in range(3)]
    inputs = {'replay': replay, 'training_pairs': pairs}
    before = {'progress': {'optimizer_steps': 0}, 'model_state': {'main': [0], 'actor_boundary.weight': [0]}}
    after = {'progress': {'optimizer_steps': 200}, 'model_state': {'main': [1], 'actor_boundary.weight': [0]},
             'training_config': {'objective': 'consistency', 'seed': 1729},
             'model_config': {'trigger_enabled': False, 'trigger_loss_weight': 0., 'actor_loss_weight': 0.},
             'consistency_parent_checkpoint_sha256': 'a' * 64, 'consistency_parent_optimizer_steps': 800}
    pools = {'earlier': [r['id'] for r in replay['earlier']],
             'historical_new': [r['id'] for name in ('prior_new', 'temporal', 'prior_consistency') for r in replay[name]],
             'pairs': [[r['left_id'], r['right_id']] for r in pairs]}
    parts = {'semantic': 1., 'trigger': 0., 'actor': 0., 'semantic_earlier': 1., 'semantic_new': 1.,
             'actor_earlier': 0., 'actor_new': 0., 'js_modality': .1, 'js_presence': .1, 'js_endpoints': .1,
             'base_ce': 1., 'consistency_js': .1, 'weighted_consistency': .025, 'total': 1.025,
             'domain_rows': {'earlier': 3, 'new': 9}, 'supervised_trigger_rows': 9,
             'trigger_loss_rows': 0, 'pair_count': 3, 'consistency_weight': .25}
    report = {'optimizer_steps': 200, 'new_optimizer_steps_total': 200, 'training_executed': True,
              'stopped_reason': 'step_limit', 'tuning_used_for_fit': False, 'objective': 'consistency',
              'checkpoint_sha256': q.digest(after), 'consistency_parent_checkpoint_sha256': 'a' * 64,
              'consistency_parent_optimizer_steps': 800, 'batch_losses': [1.025] * 200,
              'batch_loss_components': [deepcopy(parts) for _ in range(200)],
              'batch_exposures': [q.expected_batch(1729, step, pools) for step in range(1, 201)],
              'domain_exposures': {'earlier': 600, 'new': 1800}, 'pair_exposures': 600,
              'elapsed_seconds': 1., 'gradient_norm_max': 1.,
              'auxiliary_gradient_norm_max': {'trigger_boundary': 0., 'trigger_modality': 0., 'actor_boundary': 0.},
              'changed_parameter_names': ['main']}
    return report, before, after, inputs


def test_complete200_update_receipt_checks_every_batch_and_loss_component():
    report, before, after, inputs = report_fixture()
    result = q.verify_training_report(report, before, after, inputs)
    assert result['optimizer_updates'] == 200
    assert result['independent_schedule_and_loss_accounting_verified'] is True
    assert result['optimizer_trajectory_replayed'] is False


@pytest.mark.parametrize('mutation', ['old_pool', 'pair_swap', 'missing_step', 'parent_hash', 'parent_steps',
                                    'js_total', 'js_bound', 'weight', 'nan_loss', 'aux_gradient',
                                    'changed_parameter', 'tuning_fit', 'ce_objective'])
def test_corrupted_training_receipt_rejected(mutation):
    report, before, after, inputs = report_fixture()
    if mutation == 'old_pool': inputs['replay']['prior_consistency'].reverse()
    if mutation == 'pair_swap': report['batch_exposures'][70]['pairs'][0].reverse()
    if mutation == 'missing_step': report['batch_exposures'].pop()
    if mutation == 'parent_hash': report['consistency_parent_checkpoint_sha256'] = 'b' * 64
    if mutation == 'parent_steps': report['consistency_parent_optimizer_steps'] = 400
    if mutation == 'js_total': report['batch_loss_components'][90]['consistency_js'] = .2
    if mutation == 'js_bound': report['batch_loss_components'][90]['js_endpoints'] = .8
    if mutation == 'weight': report['batch_loss_components'][90]['consistency_weight'] = 0.
    if mutation == 'nan_loss': report['batch_losses'][90] = float('nan')
    if mutation == 'aux_gradient': report['auxiliary_gradient_norm_max']['actor_boundary'] = 1.
    if mutation == 'changed_parameter': report['changed_parameter_names'] = []
    if mutation == 'tuning_fit': report['tuning_used_for_fit'] = True
    if mutation == 'ce_objective': after['training_config']['objective'] = 'ce'; report['checkpoint_sha256'] = q.digest(after)
    with pytest.raises(ValueError): q.verify_training_report(report, before, after, inputs)


def inventory_fixture():
    models, pipelines, files, document_files = [], [], {}, {}
    heads = {'parent': {}, **{f'expanded-{seed}': {} for seed in q.SEEDS}}
    boundaries = {name: {panel: {} for panel in q.DOCUMENT_COUNTS} for name in heads}
    for objective in q.POLICIES:
        for architecture in q.ARCHITECTURES:
            for seed in q.SEEDS:
                name = f'{objective}_{architecture}-{seed}'
                item = {'name': name, 'objective': objective, 'architecture': architecture, 'seed': seed,
                    'enabled': architecture == 'grounding', 'decoder_kind': 'consistency' if objective == 'parent' else 'role_curriculum',
                    'checkpoint': {'sha256': str(seed)}, 'selection': 'unchanged_parent' if objective == 'parent' else 'candidate',
                    'selected_steps': 0 if objective == 'parent' else 400, 'executed_steps': 0 if objective == 'parent' else 400}
                models.append(item); files[name] = {panel: {} for panel in q.SINGLE_COUNTS}
                for policy in ('parent', 'expanded'):
                    pipe = {**item, 'name': name + '__' + policy, 'source_model_name': name, 'boundary_policy': policy,
                            'boundary_head': 'parent' if policy == 'parent' else f'expanded-{seed}'}
                    pipelines.append(pipe); document_files[pipe['name']] = {panel: {} for panel in q.DOCUMENT_COUNTS}
    return models, pipelines, files, document_files, heads, boundaries


def test_inventory_keeps_all_models_panels_and_fixed_seed_boundaries():
    result = q.verify_inventory(*inventory_fixture())
    assert result == {'single_model_slots': 12, 'document_pipeline_slots': 24, 'fixed_boundary_heads': 4,
        'selected_single_rows': 16008, 'selected_pipeline_documents': 9216, 'fixed_boundary_documents': 1536}


@pytest.mark.parametrize('mutation', ['missing_model', 'missing_real_panel', 'boundary_seed', 'control_updates', 'changed_pipeline_weights'])
def test_inventory_rejects_silent_panel_and_control_changes(mutation):
    args = inventory_fixture(); models, pipelines, files, _, _, _ = args
    if mutation == 'missing_model': models.pop()
    if mutation == 'missing_real_panel': files[models[0]['name']].pop('real_exposed')
    if mutation == 'boundary_seed': pipelines[1]['boundary_head'] = 'expanded-1731'
    if mutation == 'control_updates': models[0]['executed_steps'] = 1
    if mutation == 'changed_pipeline_weights': pipelines[0]['checkpoint'] = {'sha256': 'other'}
    with pytest.raises(ValueError): q.verify_inventory(*args)


def test_sealed_read_guard_blocks_actual_os_open_until_explicit_release(tmp_path):
    path = tmp_path / 'sealed.json'; path.write_text('{"reference": true}')
    code = '''import json, sys
from pathlib import Path
from scripts.ops.legal_ir import summarize_legal_role_curriculum_experiment as q
path = Path(sys.argv[1]); guard = q.SealedReadGuard([{'path': str(path)}]); sys.addaudithook(guard.event)
try: path.read_bytes()
except ValueError: pass
else: raise AssertionError('sealed read was allowed')
assert guard.events == [{'path': str(path.resolve()), 'after_build_freeze': False}]
guard.released = True
assert json.loads(path.read_bytes()) == {'reference': True}
assert guard.events[-1]['after_build_freeze'] is True
'''
    result = subprocess.run([sys.executable, '-c', code, str(path)], cwd=q.ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_real_diagnostics_preserves_all_abstentions_and_has_no_reference_accuracy(tmp_path, monkeypatch):
    from scripts.ops.legal_ir import evaluate_legal_uscode_fidelity as evaluation
    from ipfs_datasets_py.logic.autoformal import legal_statutory_context as context
    from tests.unit.logic.test_qualify_legal_context_routing import source, prediction, decision
    official = [source(i, 'real') for i in range(86)]
    for i in range(83, 86):
        official[i]['source_text'] = official[i-83]['source_text']
        official[i]['source_sha256'] = official[i-83]['source_sha256']
    routes = [decision(s, False) for s in official]
    route_ref = q.write(tmp_path / 'routes.json', routes)
    manifest = q.write(tmp_path / 'manifest.json', {'fixture': True})
    models, originals, files, singles = [], [], {}, {}
    generation = {'target_access': False, 'rows': [prediction(s, False) for s in official]}
    for row in generation['rows']: row['reason'] = 'copied_spans_overlap'
    generation['reports'] = [{'rows': generation['rows']}]
    generation_ref = q.write(tmp_path / 'generation.json', generation)
    for objective in q.POLICIES:
        for architecture in q.ARCHITECTURES:
            for seed in q.SEEDS:
                name = f'{objective}_{architecture}-{seed}'; checkpoint = {'test_seed': seed}
                models.append({'name': name, 'objective': objective, 'architecture': architecture, 'seed': seed, 'checkpoint': checkpoint})
                singles[name] = {'real_exposed': deepcopy(generation)}
                files[name] = {'real_exposed': generation_ref}
                if objective == 'parent':
                    originals.append({'name': f'consistency_{architecture}-{seed}', 'checkpoint': checkpoint, 'generation': generation_ref})
    original_ref = q.write(tmp_path / 'original.json', {'models': originals})
    route_plan = q.write(tmp_path / 'route-plan.json', {'prior_summary': original_ref})
    summary = q.write(tmp_path / 'routing-summary.json', {'schema': q.routing_audit.SCHEMA, 'source_views': 86,
        'statutory_accuracy': None, 'real_routes': route_ref, 'plan': route_plan})
    inputs = {'config': {'real_source_manifest': manifest}, 'sources': {'real_exposed': q.previous.source_rows(official)}}
    monkeypatch.setattr(evaluation, 'validate_manifest', lambda _: official)
    monkeypatch.setattr(context, 'inspect_prediction', lambda s, p: {'source_id': s['id'], 'source_semantics_verified': False})
    result = q.real_diagnostics(inputs, {'models': models, 'files': files}, singles, summary['path'])
    assert result['model_source_slots'] == 1032
    assert result['routing_counts']['slots'] == result['routing_counts']['decoder_abstained'] == 1032
    assert result['routing_counts']['retained_candidate'] == 0
    assert result['reference_accuracy'] is None and result['real_reference_count'] == 0
    assert all(value['abstained'] == 86 and value['reference_accuracy'] is None for value in result['models'].values())
    assert result['candidate_suppression_is_accuracy_improvement'] is False


def annotation_fixture():
    text = 'Editorial index 947. The registrar shall archive the notice.'
    def span(literal):
        start = text.index(literal); return [start, start + len(literal)]
    row = {'id': 'authored-unit-case', 'source_text': text,
           'facet_spans': {'actor': span('The registrar'), 'action': span('archive'), 'object': span('the notice'),
                           'conditions': None, 'exceptions': None, 'temporal': None}, 'trigger_span': span('shall'),
           'canonical_ir': {'rules': [{'modality': 'O', 'actor': 'The registrar', 'action': 'archive', 'object': 'the notice',
                                       'conditions': [], 'exceptions': [], 'temporal': []}]}}
    template = 'Editorial index {number}. {actor} {trigger} {action} {object}.'
    label = {**deepcopy(row), 'panel': 'unit', 'source_sha256': hashlib.sha256(text.encode()).hexdigest(),
             'annotation_authority': 'authored_controlled_example_not_statutory_gold', 'template': template,
             'template_fingerprint': hashlib.sha256(template.encode()).hexdigest(), 'case_group': 'unit-case', 'presence_mask': 0,
             'editorial_context': [{'start_char': 0, 'end_char': len('Editorial index 947. '),
                'source_text': 'Editorial index 947. ', 'author_stipulated_role': 'nonoperative_editorial_context'}]}
    return row, label


def test_annotation_rebuild_masks_citation_numbers_and_retains_editorial_structure():
    row, label = annotation_fixture()
    assert q.verify_annotation(row, label, 'unit')['template_fingerprint'] == label['template_fingerprint']


@pytest.mark.parametrize('mutation', ['template_hash_repair', 'source_hash', 'coordinate', 'authority',
                                    'editorial_overlap', 'editorial_literal', 'trigger_overlap', 'wrong_split', 'presence_mask'])
def test_annotation_mutations_cannot_fake_novelty_or_remove_operative_spans(mutation):
    row, label = annotation_fixture()
    if mutation == 'template_hash_repair':
        label['template'] = 'unique claimed template'
        label['template_fingerprint'] = hashlib.sha256(label['template'].encode()).hexdigest()
    if mutation == 'source_hash': label['source_sha256'] = 'a' * 64
    if mutation == 'coordinate': label['facet_spans']['actor'][0] += 1
    if mutation == 'authority': label['annotation_authority'] = 'independently_verified_US_Code'
    if mutation == 'editorial_overlap':
        note = label['editorial_context'][0]; note['end_char'] = row['facet_spans']['actor'][1]
        note['source_text'] = row['source_text'][:note['end_char']]
    if mutation == 'editorial_literal': label['editorial_context'][0]['source_text'] = 'fabricated metadata'
    if mutation == 'trigger_overlap':
        row['trigger_span'] = row['facet_spans']['actor']; label['trigger_span'] = row['trigger_span']
    if mutation == 'wrong_split': label['panel'] = 'different'
    if mutation == 'presence_mask': label['presence_mask'] = 1
    with pytest.raises(ValueError): q.verify_annotation(row, label, 'unit')


@pytest.mark.parametrize('field', ['case_group', 'meaning_group', 'side'])
def test_annotation_pair_permutation_rejected_even_if_cardinalities_match(field):
    pairs = [{'left_id': 'a', 'right_id': 'b', 'case_group': 'case-a', 'pair_id': 'meaning-a'},
             {'left_id': 'c', 'right_id': 'd', 'case_group': 'case-b', 'pair_id': 'meaning-b'}]
    annotations = [{'id': identity, 'case_group': pair['case_group'], 'meaning_group': pair['pair_id'], 'side': side}
                   for pair in pairs for side, identity in enumerate((pair['left_id'], pair['right_id']))]
    q.verify_annotation_pairs(pairs, annotations)
    other = 1 if field == 'side' else 2
    annotations[0][field], annotations[other][field] = annotations[other][field], annotations[0][field]
    with pytest.raises(ValueError, match='membership'): q.verify_annotation_pairs(pairs, annotations)


def test_fresh_coordinate_validation_uses_six_pinned_old_rows_without_changing_fresh_denominator():
    def row(index, domain):
        actor = ('Old' if domain == 'earlier' else 'New') + f' registrar {index}'
        text = actor + ' must archive the notice.'
        def span(literal):
            start = text.index(literal); return [start, start + len(literal)]
        return {'id': domain + str(index), 'source_text': text, 'domain': domain,
            'trigger_supervised': domain == 'new', 'trigger_span': span('must') if domain == 'new' else None,
            'facet_spans': {'actor': span(actor), 'action': span('archive'), 'object': span('the notice'),
                           'conditions': None, 'exceptions': None, 'temporal': None},
            'canonical_ir': {'rules': [{'modality': 'O', 'actor': actor, 'action': 'archive', 'object': 'the notice',
                                      'conditions': [], 'exceptions': [], 'temporal': []}]}}
    earlier, fresh = [row(i, 'earlier') for i in range(8)], [row(i, 'new') for i in range(6)]
    before = deepcopy(fresh)
    q.validate_fresh_coordinates({'replay': {'earlier': earlier}}, fresh)
    assert fresh == before and len(fresh) == 6
