#!/usr/bin/env python3
"""Independent authored role-curriculum training, inference and build qualification.

Real U.S. Code views remain exposed, source-only diagnostics. Authored exact
reference metrics and native compiler success are separate evidence categories.
"""
from __future__ import annotations

import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import summarize_legal_clause_consistency_experiment as consistency_audit
from scripts.ops.legal_ir import qualify_legal_context_routing as routing_audit

require, digest = consistency_audit.require, consistency_audit.digest
read_ref, ref, write, sha = consistency_audit.read_ref, consistency_audit.ref, consistency_audit.write, consistency_audit.sha
expected_batch = consistency_audit.expected_batch
SCHEMA = 'legal-role-curriculum-independent-qualification/v1'
SEEDS = (1729, 1730, 1731)
ARCHITECTURES = ('continuation', 'grounding')
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing
import re
from scripts.ops.legal_ir import summarize_legal_construction_retention_experiment as retained
from scripts.ops.legal_ir import summarize_legal_boundary_curriculum_experiment as boundary_qualification
from scripts.ops.legal_ir import run_legal_clause_boundary_experiment as clauses
from scripts.ops.legal_ir import run_legal_grounding_experiment as previous
from ipfs_datasets_py.logic.autoformal import legal_clause_boundary_decoder as boundary
OBJECTIVES = ('role_curriculum',)
POLICIES = ('parent', 'role_curriculum')
SINGLE_COUNTS = {'tuning_earlier': 96, 'tuning_temporal': 120, 'tuning_prior_consistency': 96, 'tuning_new': 96,
    'fresh': 144, 'prior_consistency': 144, 'prior_construction': 180, 'earlier_regression': 192,
    'temporal_regression': 180, 'real_exposed': 86}
DOCUMENT_COUNTS = {'document_tuning': 96, 'prior_consistency_documents': 96,
    'prior_boundary_documents': 96, 'exposed_documents': 96}
TUNING = ('earlier', 'temporal', 'prior_consistency', 'new')
RETENTION = ('earlier', 'temporal', 'prior_consistency', 'document_parent', 'document_expanded')
FALSE = retained.FALSE
single_error_metrics = consistency_audit.single_error_metrics
objective_sanity = consistency_audit.objective_sanity



def selection_choice(stages, parent):
    bounds = {'earlier': 96, 'temporal': 120, 'prior_consistency': 96,
              'document_parent': 72, 'document_expanded': 72}
    require(set(parent) == set(bounds) and all(type(parent[k]) is int and 0 <= parent[k] <= n for k, n in bounds.items()),
            'closed bounded same-parent retention metrics required')
    require(type(stages) is list and [r.get('steps') for r in stages] == [200, 400], 'both additional-update stages required')
    fields = {**bounds, 'new': 96, 'guard_parent': 24, 'guard_expanded': 24}
    for stage in stages:
        require(set(stage) == {'steps', *fields} and all(type(stage[k]) is int and 0 <= stage[k] <= n for k, n in fields.items()),
                'closed bounded tuning-only metrics required')
    eligible = [r for r in stages if all(r[k] >= parent[k] - 1 for k in bounds)
        and r['guard_parent'] == r['guard_expanded'] == 0]
    return max(eligible, key=lambda r: (r['new'], r['temporal'], r['document_expanded'], r['document_parent'], r['earlier'], -r['steps'])) if eligible else None


def verify_pairs(rows, pairs):
    required = {'pair_id', 'case_group', 'left_id', 'right_id', 'canonical_ir_sha256'}
    lookup = {r['id']: r for r in rows}
    require(len(rows) == 2 * len(pairs) and len(lookup) == len(rows)
        and len({r['source_text'] for r in rows}) == len(rows), 'unique two-row semantic pair inventory required')
    members, case_groups, pair_ids = set(), set(), set()
    for pair in pairs:
        require(set(pair) == required and all(type(pair[k]) is str and pair[k] for k in required), 'closed semantic pair metadata required')
        require(pair['pair_id'] not in pair_ids and pair['left_id'] != pair['right_id']
            and {pair['left_id'], pair['right_id']} <= set(lookup)
            and not {pair['left_id'], pair['right_id']} & members, 'pair identity or source membership overlaps')
        left, right = lookup[pair['left_id']], lookup[pair['right_id']]
        require(left['canonical_ir'] == right['canonical_ir'] and digest(left['canonical_ir']) == pair['canonical_ir_sha256'],
                'paired examples must have identical complete canonical semantics')
        for row in (left, right):
            require(row['domain'] == 'new' and row['trigger_supervised'] is True and row['trigger_span'] is not None,
                    'new paired rows require explicit trigger supervision')
        members.update((pair['left_id'], pair['right_id'])); case_groups.add(pair['case_group']); pair_ids.add(pair['pair_id'])
    require(members == set(lookup), 'semantic pair inventory dropped rows')
    return {'pairs': len(pairs), 'rows': len(rows), 'case_groups': sorted(case_groups), 'pair_ids': sorted(pair_ids),
        'complete_canonical_semantics_equal': True, 'ordered_pair_manifest_sha256': digest(pairs)}


def verify_training_report(report, preceding, checkpoint, inputs):
    start, finish = preceding['progress']['optimizer_steps'], checkpoint['progress']['optimizer_steps']
    config, model_config = checkpoint['training_config'], checkpoint['model_config']
    objective = config['objective']; enabled = model_config['trigger_enabled']; weight = .25
    require(objective == 'consistency', 'fixed role-consistency objective required')
    require(finish - start == report['optimizer_steps'] == 200 and report['new_optimizer_steps_total'] == finish
        and report['training_executed'] is True and report['stopped_reason'] == 'step_limit'
        and report['tuning_used_for_fit'] is False and report['objective'] == objective,
        'complete fixed200-update training stage with fitting-only labels required')
    require(report['checkpoint_sha256'] == digest(checkpoint)
        and report['consistency_parent_checkpoint_sha256'] == checkpoint['consistency_parent_checkpoint_sha256']
        and report['consistency_parent_optimizer_steps'] == checkpoint['consistency_parent_optimizer_steps'] == 800,
        'training report checkpoint or consistency800 parent binding differs')
    require(len(report['batch_losses']) == len(report['batch_loss_components']) == len(report['batch_exposures']) == 200
        and report['domain_exposures'] == {'earlier': 600, 'new': 1800} and report['pair_exposures'] == 600,
        'complete3+3+3pair stage exposures required')
    require(type(report['elapsed_seconds']) in (int, float) and math.isfinite(report['elapsed_seconds']) and report['elapsed_seconds'] > 0
        and math.isfinite(report['gradient_norm_max']) and report['gradient_norm_max'] >= 0,
        'finite training timing and gradient receipts required')
    pools = {'earlier': [r['id'] for r in inputs['replay']['earlier']],
        'historical_new': [r['id'] for name in ('prior_new', 'temporal', 'prior_consistency') for r in inputs['replay'][name]],
        'pairs': [[r['left_id'], r['right_id']] for r in inputs['training_pairs']]}
    numerical = ('semantic', 'trigger', 'actor', 'semantic_earlier', 'semantic_new', 'actor_earlier', 'actor_new',
        'js_modality', 'js_presence', 'js_endpoints', 'base_ce', 'consistency_js', 'weighted_consistency', 'total')
    def close(a, b): return math.isclose(a, b, rel_tol=2e-5, abs_tol=2e-6)
    for step, (exposure, parts, loss) in enumerate(zip(report['batch_exposures'], report['batch_loss_components'], report['batch_losses']), start + 1):
        require(exposure == expected_batch(config['seed'], step, pools), 'independent objective-neutral paired minibatch order differs')
        require(parts['domain_rows'] == {'earlier': 3, 'new': 9} and parts['supervised_trigger_rows'] == 9
            and parts['trigger_loss_rows'] == (9 if enabled else 0) and parts['pair_count'] == 3
            and parts['consistency_weight'] == weight, 'domain, trigger mask or paired loss counts differ')
        require(all(type(parts[k]) in (int, float) and math.isfinite(parts[k]) and parts[k] >= -2e-6 for k in numerical)
            and type(loss) in (float, int) and math.isfinite(loss) and loss >= -2e-6, 'finite bounded loss components required')
        require(all(parts[k] <= math.log(2) + 2e-6 for k in ('js_modality', 'js_presence', 'js_endpoints', 'consistency_js')),
                'Jensen-Shannon divergence exceeds probability bound')
        require(close(parts['semantic'], (parts['semantic_earlier'] + parts['semantic_new']) / 2)
            and close(parts['actor'], (parts['actor_earlier'] + parts['actor_new']) / 2)
            and close(parts['base_ce'], parts['semantic'] + model_config['trigger_loss_weight'] * parts['trigger'] + model_config['actor_loss_weight'] * parts['actor'])
            and close(parts['consistency_js'], sum(parts[k] for k in ('js_modality', 'js_presence', 'js_endpoints')) / 3)
            and close(parts['weighted_consistency'], weight * parts['consistency_js'])
            and close(parts['total'], parts['base_ce'] + parts['weighted_consistency']) and close(loss, parts['total']),
            'independent CE/three-component JS/weighted total accounting differs')
        if not enabled:
            require(all(parts[k] == 0 for k in ('actor', 'trigger', 'actor_earlier', 'actor_new')), 'disabled auxiliary losses must be zero')
    gradients = report['auxiliary_gradient_norm_max']
    require(set(gradients) == {'trigger_boundary', 'trigger_modality', 'actor_boundary'}
        and all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in gradients.values()), 'finite auxiliary gradient inventory required')
    if not enabled:
        require(all(v == 0 for v in gradients.values()), 'disabled auxiliary gradients must remain zero')
        for name, value in preceding['model_state'].items():
            if name.startswith(('trigger_boundary.', 'trigger_modality.', 'actor_boundary.')):
                require(checkpoint['model_state'][name] == value, 'disabled auxiliary parameters changed')
    changed = [name for name, value in checkpoint['model_state'].items() if value != preceding['model_state'][name]]
    require(changed and len(report['changed_parameter_names']) == len(changed)
        and sorted(report['changed_parameter_names']) == sorted(changed), 'changed model tensor inventory differs')
    return {'additional_steps_before': start, 'additional_steps_after': finish, 'optimizer_updates': 200,
        'domain_exposures': report['domain_exposures'], 'pair_exposures': 600,
        'batch_trace_sha256': digest(report['batch_exposures']), 'same_semantics_pairs_only': True,
        'independent_schedule_and_loss_accounting_verified': True, 'optimizer_trajectory_replayed': False}



def replay_job(job):
    import torch
    torch.set_num_threads(1)
    from scripts.ops.legal_ir import run_legal_role_curriculum_experiment as runner
    if job['kind'] == 'boundary':
        return boundary_qualification.replay_job(job)
    item = job['model']; expected = read_ref(job['generation'])
    if job.get('stage'): expected = expected['generation']
    decoder = runner.load_decoder(item['checkpoint'], item['decoder_kind'])
    copied = occurrences = 0
    if job['kind'] == 'single':
        actual = previous.generate(decoder, job['sources'], ablation='none')
        for source, prediction in zip(job['sources'], actual['rows']):
            copied += retained.prior.source_audit.assert_source_copy(prediction, source)
    else:
        frozen_boundaries = read_ref(job['boundary'])
        actual = {'rows': clauses.integrate(frozen_boundaries, job['sources'], decoder),
            'target_access': False, 'references_supplied': False, 'training_executed': False}
        by_id = {r['candidate_id']: r for r in frozen_boundaries['rows']}
        for row in actual['rows']:
            segment = by_id[row['candidate_id']]
            require(row['segmentation_status'] == segment['status'], 'pipeline changed frozen segmentation status')
            if segment['plan'] is None:
                require(row['composition'] is row['clause_generation'] is None, 'boundary abstention emitted clause predictions')
            else:
                plan = segment['plan']
                retained.compose.validate_source_plan(plan, expected_plan_sha256=plan['plan_sha256'])
                require(len(row['clause_generation']['rows']) == plan['clause_count'], 'pipeline clause occurrence inventory differs')
                for clause, prediction in zip(plan['clauses'], row['clause_generation']['rows']):
                    copied += retained.prior.source_audit.assert_source_copy(prediction, clause); occurrences += 1
                if row['composition'] is not None:
                    require(row['composition']['source_plan'] == plan, 'pipeline changed frozen source occurrence intervals')
                    retained.compose.validate_composition(row['composition'], expected_plan_sha256=plan['plan_sha256'])
    require(actual == expected, 'independent full numerical replay differs: ' + job['name'])
    return {'kind': job['kind'], 'name': job['name'], 'rows': len(job['sources']), 'generation': job['generation'],
        'checkpoint': item['checkpoint'], 'boundary': job.get('boundary'), 'source_inputs_sha256': digest(job['sources']),
        'recorded_generation_sha256': digest(actual), 'exact_recorded_payload_replay': True,
        'clause_occurrences_replayed': occurrences, 'copied_facets_verified': copied,
        'stage_tuning': job.get('stage', False), 'target_access': False}



def verify_inventory(models, pipelines, files, document_files, heads, boundaries):
    expected_models = {f'{objective}_{architecture}-{seed}' for objective in POLICIES
        for architecture in ARCHITECTURES for seed in SEEDS}
    expected_pipelines = {name + '__' + policy for name in expected_models for policy in ('parent', 'expanded')}
    expected_heads = {'parent', *(f'expanded-{seed}' for seed in SEEDS)}
    require(len(models) == 12 and {m['name'] for m in models} == set(files) == expected_models
        and len(pipelines) == 24 and {p['name'] for p in pipelines} == set(document_files) == expected_pipelines
        and set(heads) == set(boundaries) == expected_heads,
        'complete12 single models/24 document pipelines/four fixed boundary heads required')
    by_model = {m['name']: m for m in models}
    for model in models:
        require(model['name'] == f"{model['objective']}_{model['architecture']}-{model['seed']}"
            and model['enabled'] is (model['architecture'] == 'grounding')
            and model['decoder_kind'] in ('consistency', 'role_curriculum')
            and set(files[model['name']]) == set(SINGLE_COUNTS), 'single model architecture, seed or panel inventory differs')
        if model['objective'] == 'parent':
            require(model['decoder_kind'] == 'consistency' and model['selection'] == 'unchanged_parent'
                and model['selected_steps'] == model['executed_steps'] == 0,
                'original same-architecture consistency800 control attribution differs')
    for pipeline in pipelines:
        model = by_model[pipeline['source_model_name']]; policy = pipeline['boundary_policy']
        require(policy in ('parent', 'expanded') and pipeline['name'] == model['name'] + '__' + policy
            and pipeline['boundary_head'] == ('parent' if policy == 'parent' else f"expanded-{model['seed']}")
            and set(document_files[pipeline['name']]) == set(DOCUMENT_COUNTS)
            and all(pipeline[k] == model[k] for k in ('architecture', 'objective', 'seed', 'checkpoint', 'decoder_kind', 'enabled', 'selection', 'selected_steps')),
            'paired pipeline checkpoint or fixed same-seed boundary binding differs')
    require(all(set(panels) == set(DOCUMENT_COUNTS) for panels in boundaries.values()), 'fixed boundary panel inventory differs')
    return {'single_model_slots': 12, 'document_pipeline_slots': 24, 'fixed_boundary_heads': 4,
        'selected_single_rows': 16008, 'selected_pipeline_documents': 9216, 'fixed_boundary_documents': 1536}



def tuning_audit(fields, item, inputs, frozen, label):
    """Recompute all gate metrics with independent complete-source scoring."""
    jobs, normalized = [], {}
    for panel in TUNING:
        reference = fields['tuning_' + panel]; saved = read_ref(reference)
        sources = inputs['sources']['tuning_' + panel]
        metric = previous.score(saved['generation']['rows'], sources, inputs['tuning'][panel])
        require(saved['metrics'] == metric and fields['tuning_' + panel + '_exact'] == metric['exact'], 'independent single tuning counts differ')
        normalized[panel] = metric['exact']
        jobs.append({'kind': 'single', 'name': label + '/tuning_' + panel, 'model': item, 'sources': sources,
            'generation': reference, 'stage': True})
    for policy in ('parent', 'expanded'):
        reference = fields['document_tuning_' + policy]; saved = read_ref(reference)
        sources = inputs['document_sources']['document_tuning']
        metric = retained.score_documents(saved['generation'], sources, inputs['document_tuning'])
        require(saved['metrics'] == metric and fields['tuning_document_' + policy + '_exact'] == metric['exact']
            and fields['tuning_document_' + policy + '_unsupported_accepted'] == metric['unsupported_accepted'],
            'independent canonical AND occurrence document tuning counts differ')
        normalized['document_' + policy] = metric['exact']; normalized['guard_' + policy] = metric['unsupported_accepted']
        head = 'parent' if policy == 'parent' else f"expanded-{item['seed']}"
        jobs.append({'kind': 'document', 'name': label + '/document_tuning_' + policy, 'model': item, 'sources': sources,
            'generation': reference, 'boundary': frozen['boundaries'][head]['document_tuning'], 'stage': True})
    return jobs, normalized



def verify_training(inputs, frozen, selection):
    from scripts.ops.legal_ir import run_legal_role_curriculum_experiment as runner
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_role_curriculum as runtime
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consistency as parent_runtime
    require(selection['executed_optimizer_updates'] == 2400 and selection['fresh_targets_opened'] is selection['regression_targets_opened'] is False,
            'complete pre-reference fitting freeze required')
    trials = selection['trials']; models = {m['name']: m for m in frozen['models']}
    require(len(trials) == 6 and {(r['objective'], r['architecture'], r['seed']) for r in trials} ==
        {(o, a, s) for o in OBJECTIVES for a in ARCHITECTURES for s in SEEDS}, 'all6 role/architecture/seed trials required')
    parent_tuning = read_ref(selection['parent_tuning']); jobs, audits, parents = [], [], {}
    tuning = [r for panel in TUNING for r in inputs['tuning'][panel]]
    pairs = [[p['left_id'], p['right_id']] for p in inputs['training_pairs']]
    require(inputs['runtime_pairs'] == pairs, 'runtime pair index list differs from annotated meaning pairs')
    expected_parent_names = {f'parent_{a}-{s}' for a in ARCHITECTURES for s in SEEDS}
    require(set(parent_tuning) == expected_parent_names, 'all six parent tuning references required')
    for name in sorted(expected_parent_names):
        model = models[name]; parent_ref = inputs['parents'][(model['architecture'], model['seed'])]['checkpoint']
        require(model['checkpoint'] == model['parent'] == parent_ref, 'unchanged consistency800 parent checkpoint differs')
        local_jobs, metric = tuning_audit(parent_tuning[name], model, inputs, frozen, 'parent-reference-' + name)
        jobs.extend(local_jobs); parents[name] = {k: metric[k] for k in RETENTION}
        for panel in TUNING:
            require(read_ref(parent_tuning[name]['tuning_' + panel])['generation'] == read_ref(frozen['files'][name]['tuning_' + panel]),
                    'parent reference and selected single tuning outputs differ')
        for policy in ('parent', 'expanded'):
            require(read_ref(parent_tuning[name]['document_tuning_' + policy])['generation'] == read_ref(frozen['document_files'][name + '__' + policy]['document_tuning']),
                    'parent reference and selected document tuning outputs differ')
    for trial in trials:
        name, seed, architecture, objective = (trial[k] for k in ('name', 'seed', 'architecture', 'objective'))
        require(trial == models[name] and trial['executed_steps'] == 400 and trial['enabled'] is (architecture == 'grounding')
            and trial['fresh_targets_opened'] is trial['regression_targets_opened'] is False,
            'trial identity/architecture/budget differs')
        require({k: v for k, v in trial.items() if k != 'selection_record'} == read_ref(trial['selection_record']), 'trial selection record differs')
        parent_name = f'parent_{architecture}-{seed}'; parent_ref = models[parent_name]['checkpoint']
        require(trial['parent'] == parent_ref and trial['parent_tuning'] == parent_tuning[parent_name], 'same-architecture/seed parent tuning anchor differs')
        parent = parent_runtime.load_checkpoint(parent_ref['path'], expected_sha256=parent_ref['sha256'])
        require(parent['progress']['optimizer_steps'] == 800 and parent['model_config']['seed'] == seed
            and parent['model_config']['trigger_enabled'] is trial['enabled'], 'frozen consistency800 parent architecture differs')
        initial = runtime.load_checkpoint(trial['initial_checkpoint']['path'], expected_sha256=trial['initial_checkpoint']['sha256'])
        reconstructed = runtime.build_checkpoint(parent, inputs['training'], tuning, pairs, objective='consistency', seed=seed, learning_rate=.001, batch_size=12)
        require(initial == reconstructed and initial['model_state'] == parent['model_state']
            and initial['optimizer_state'] == {'schema': 'adam-default-betas-eps/v1', 'parameters': {}}
            and initial['progress']['optimizer_steps'] == 0 and trial['initial_model_state_sha256'] == digest(parent['model_state']),
            'copied pretrained tensors/fresh Adam/complete initialization reconstruction differs')
        initialization = read_ref(trial['initialization'])
        require(initialization['parent'] == parent_ref and initialization['initial'] == trial['initial_checkpoint']
            and initialization['initial_model_state_sha256'] == initialization['parent_model_state_sha256'] == digest(parent['model_state'])
            and initialization['parent_tuning'] == parent_tuning[parent_name]
            and initialization['all_initial_tensors_equal'] is initialization['all_tuning_numerical_predictions_equal'] is initialization['optimizer_reset'] is True
            and initialization['historical_optimizer_resumed'] is False, 'initialization provenance or optimizer reset receipt differs')
        for panel in TUNING:
            a = read_ref(initialization['parent_tuning']['tuning_' + panel]); b = read_ref(initialization['tuning']['tuning_' + panel])
            require(a['generation']['rows'] == b['generation']['rows'] and a['metrics'] == b['metrics'], 'initial source predictions/logits changed')
            require(all(report['checkpoint_sha256'] == digest(initial) for report in b['generation']['reports']), 'initial inference checkpoint metadata differs')
        for policy in ('parent', 'expanded'):
            a = read_ref(initialization['parent_tuning']['document_tuning_' + policy]); b = read_ref(initialization['tuning']['document_tuning_' + policy])
            require(runner.document_signature(a['generation']) == runner.document_signature(b['generation']) and a['metrics'] == b['metrics'],
                    'initial learned-boundary pipeline predictions changed')
        require([s['steps'] for s in trial['stages']] == [200, 400], 'complete200/400 candidate inventory required')
        previous_checkpoint = initial; normalized, stages = [], []
        for stage in trial['stages']:
            checkpoint = runtime.load_checkpoint(stage['checkpoint']['path'], expected_sha256=stage['checkpoint']['sha256'])
            require(stage['previous_checkpoint_sha256'] == checkpoint['parent_checkpoint_sha256'] == digest(previous_checkpoint)
                and checkpoint['progress']['optimizer_steps'] == stage['steps'], 'checkpoint/optimizer resumption chain differs')
            for field in ('schema', 'lineage_id', 'implementation', 'consistency_parent_checkpoint', 'consistency_parent_checkpoint_sha256',
                'consistency_parent_optimizer_steps', 'model_config', 'training_config', 'initial_model_state_sha256',
                'training_manifest_sha256', 'tuning_manifest_sha256', 'pair_manifest_sha256', 'training_count', 'tuning_count', 'pool_counts'):
                require(checkpoint[field] == initial[field], 'stage fitting provenance changed: ' + field)
            report = read_ref(stage['training_report'])
            report_audit = verify_training_report(report, previous_checkpoint, checkpoint, inputs)
            item = {**trial, 'checkpoint': stage['checkpoint'], 'decoder_kind': 'role_curriculum'}
            local_jobs, scores = tuning_audit(stage, item, inputs, frozen, name + f"/stage-{stage['steps']}")
            jobs.extend(local_jobs); normalized.append({'steps': stage['steps'], **scores})
            wanted_eligible = all(scores[k] >= parents[parent_name][k] - 1 for k in parents[parent_name]) and scores['guard_parent'] == scores['guard_expanded'] == 0
            require(stage['eligible'] is wanted_eligible, 'recorded multi-panel retention eligibility differs')
            stages.append({**report_audit, 'checkpoint': stage['checkpoint'], 'training_report': stage['training_report'],
                'tuning': scores, 'eligible': wanted_eligible})
            previous_checkpoint = checkpoint
        chosen = selection_choice(normalized, parents[parent_name])
        steps = chosen['steps'] if chosen else 0
        checkpoint_ref = next(s['checkpoint'] for s in trial['stages'] if s['steps'] == steps) if chosen else parent_ref
        status = 'candidate' if chosen else 'parent_fallback_no_acceptable_replacement'
        require(trial['selected_steps'] == steps and trial['checkpoint'] == checkpoint_ref and trial['selection'] == status
            and trial['decoder_kind'] == ('role_curriculum' if chosen else 'consistency'), 'independent tuning-only candidate/fallback choice differs')
        chosen_fields = next(s for s in trial['stages'] if s['steps'] == steps) if chosen else parent_tuning[parent_name]
        for panel in TUNING:
            require(read_ref(chosen_fields['tuning_' + panel])['generation'] == read_ref(frozen['files'][name]['tuning_' + panel]), 'selected single tuning differs from chosen stage')
        for policy in ('parent', 'expanded'):
            require(read_ref(chosen_fields['document_tuning_' + policy])['generation'] == read_ref(frozen['document_files'][name + '__' + policy]['document_tuning']),
                    'selected document tuning differs from chosen stage')
        audits.append({'name': name, 'objective': objective, 'architecture': architecture, 'seed': seed, 'parent': parent_ref,
            'initial_checkpoint': trial['initial_checkpoint'], 'initial_model_state_sha256': digest(parent['model_state']),
            'stages': stages, 'parent_tuning': parents[parent_name], 'selection': status, 'selected_steps': steps,
            'checkpoint': checkpoint_ref, 'executed_optimizer_updates': 400,
            'historical_optimizer_resumed': False, 'optimizer_trajectory_replayed': False})
    trial_receipts = []
    for trial in trials:
        exposures = [row for stage in trial['stages'] for row in read_ref(stage['training_report'])['batch_exposures']]
        require(len(exposures) == 400, 'complete update trace required')
        trial_receipts.append({'architecture': trial['architecture'], 'seed': trial['seed'], 'parent': trial['parent'],
            'batch_count': 400, 'batch_exposures_sha256': digest(exposures), 'same_architecture_no_update_control': True})
    require(selection['trial_update_audit'] == trial_receipts, 'frozen trial update receipt differs')
    return jobs, audits


def verify_fitting(inputs):
    from scripts.ops.legal_ir import prepare_legal_clause_consistency_corpus as old_corpus
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_mixed_replay as mixed
    manifest = inputs['manifest']
    old = old_corpus.load_training_inputs(manifest['inputs']['prior_corpus']['path'])
    replay = {**old['replay'], 'prior_consistency': old['new_train']}
    require(inputs['replay'] == replay and {k: len(v) for k, v in replay.items()} ==
        {'earlier': 1152, 'prior_new': 600, 'temporal': 600, 'prior_consistency': 384},
        'historical replay, order or prior consistency labels changed')
    artifacts = manifest['artifacts']
    train, tune = (read_ref(artifacts[k]) for k in ('new_training', 'new_tuning'))
    pairs, tuning_pairs = (read_ref(artifacts[k]) for k in ('training_pairs', 'tuning_pairs'))
    expected_training = [r for name in ('earlier', 'prior_new', 'temporal', 'prior_consistency') for r in replay[name]] + train
    require(inputs['training'] == expected_training and inputs['new_train'] == train
        and inputs['training_pairs'] == pairs and inputs['tuning']['new'] == tune
        and inputs['tuning_pairs'] == tuning_pairs, 'new fitting/pair manifests changed')
    wanted_tuning = {'earlier': old['tuning']['earlier'], 'temporal': old['tuning']['temporal'],
                     'prior_consistency': old['new_tuning']}
    require(all(inputs['tuning'][k] == value for k, value in wanted_tuning.items()), 'retention tuning labels changed')
    training, tuning = verify_pairs(train, pairs), verify_pairs(tune, tuning_pairs)
    require((training['pairs'], tuning['pairs']) == (192, 48)
        and len(training['case_groups']) == 192 and len(tuning['case_groups']) == 48
        and not set(training['case_groups']) & set(tuning['case_groups']), 'authored meaning/case separation differs')
    parsed, _ = mixed._splits(inputs['training'], [r for panel in TUNING for r in inputs['tuning'][panel]])
    require(len(parsed) == 3120, 'complete source-copy fitting records required')
    real = inputs['sources']['real_exposed']
    real_hashes = {digest(r['source_text']) for r in real}
    require(len(real) == 86 and len({r['id'] for r in real}) == 86 and len(real_hashes) == 83
        and not real_hashes & {digest(r['source_text']) for r in inputs['training']},
        'all86 exposed views, including repeated text views, must remain outside fitting')
    return {'training_pairs': training, 'tuning_pairs': tuning, 'historical_rows': 2736, 'new_rows': 384,
        'total_training_rows': 3120, 'explicit_coordinate_and_trigger_labels_validated': True,
        'historical_replay_and_tuning_preserved': True, 'real_views_used_as_supervision': 0}


def verify_annotation(row, label, panel):
    import hashlib
    def text_hash(text): return hashlib.sha256(text.encode()).hexdigest()
    text = row['source_text']
    require(label['panel'] == panel and label['id'] == row['id'] and label['source_sha256'] == text_hash(text)
        and label['facet_spans'] == row['facet_spans'] and label['trigger_span'] == row['trigger_span']
        and label['annotation_authority'] == 'authored_controlled_example_not_statutory_gold',
        'source coordinates or authored authority differ')
    rule = row['canonical_ir']['rules'][0]
    require(label['presence_mask'] == sum(1 << index for index, field in enumerate(('conditions', 'exceptions', 'temporal'))
                                          if rule[field]), 'annotation presence mask differs from complete canonical meaning')
    intervals = sorted((span[0], span[1], name) for name, span in
        {**row['facet_spans'], 'trigger': row['trigger_span']}.items() if span is not None)
    cursor, template = 0, ''
    for start, end, name in intervals:
        require(cursor <= start < end <= len(text), 'authored facet/trigger overlap')
        template += text[cursor:start] + '{' + name + '}'; cursor = end
    template += text[cursor:]
    template = re.sub(r'\b[0-9]+\b', '{number}', template)
    require(template == label['template'] and text_hash(template) == label['template_fingerprint'],
            'independent role-masked template differs')
    for note in label['editorial_context']:
        start, end = note['start_char'], note['end_char']
        require(0 <= start < end <= len(text) and text[start:end] == note['source_text']
            and note['author_stipulated_role'] == 'nonoperative_editorial_context'
            and all(end <= left or start >= right for left, right, _ in intervals),
            'authored editorial context overlaps an operative labeled facet')
    return {'template_fingerprint': label['template_fingerprint'], 'case_group': label['case_group']}


def verify_annotation_pairs(pairs, annotations):
    by_id = {row['id']: row for row in annotations}
    for pair in pairs:
        for side, key in enumerate(('left_id', 'right_id')):
            row = by_id[pair[key]]
            require(row['case_group'] == pair['case_group'] and row['meaning_group'] == pair['pair_id']
                and row['side'] == side, 'annotation membership differs from exact semantic pair')


def validate_fresh_coordinates(inputs, fresh):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_mixed_replay as mixed
    # Frozen _splits is also a training-contract validator and requires six rows
    # in each domain. These pinned earlier rows serve coordinate validation only.
    validation_prefix = inputs['replay']['earlier'][:6]
    require(len(validation_prefix) == 6 and all(row['domain'] == 'earlier' for row in validation_prefix)
        and all(row['domain'] == 'new' for row in fresh), 'fresh coordinate validation domains differ')
    parsed, _ = mixed._splits(validation_prefix + fresh, [])
    require(len(parsed) == 6 + len(fresh), 'fresh coordinate validation dropped examples')


def audit_exposure(inputs, fresh, evidence):
    """Reconstruct template and source disjointness only after the build freeze."""
    from scripts.ops.legal_ir import prepare_legal_clause_consistency_corpus as old_corpus
    import hashlib
    def text_hash(text): return hashlib.sha256(text.encode()).hexdigest()
    def normalized(text): return ' '.join(re.findall(r'\w+|[^\w\s]', text.casefold()))
    panels = {'train': inputs['new_train'], 'tuning': inputs['tuning']['new'], 'fresh': fresh}
    ledger, exposure, pairs = (evidence[k] for k in ('annotation_ledger', 'exposure_audit', 'challenge_pairs'))
    require(set(ledger) == set(panels), 'complete authored annotation panels required')
    require(verify_pairs(fresh, pairs)['pairs'] == 72, 'fresh pairing inventory differs')
    validate_fresh_coordinates(inputs, fresh)
    pair_panels = {'train': inputs['training_pairs'], 'tuning': inputs['tuning_pairs'], 'fresh': pairs}
    seen_texts, seen_meanings, seen_templates, seen_ids, seen_cases = set(), set(), set(), set(), set()
    audits = {}
    for panel, rows in panels.items():
        labels = ledger[panel]
        by_id = {r['id']: r for r in labels}
        require(len(by_id) == len(labels) == len(rows) and set(by_id) == {r['id'] for r in rows},
                'annotation denominator or identity differs')
        verify_annotation_pairs(pair_panels[panel], labels)
        require(dict(Counter(r['family'] for r in labels)) == {name: len(rows) // 4 for name in
            ('numbered_heading', 'preposed_date', 'editorial_cross_reference', 'extent_framing')},
            'complete balanced four-family annotation inventory differs')
        templates, cases = set(), set()
        for row in rows:
            annotation = verify_annotation(row, by_id[row['id']], panel)
            templates.add(annotation['template_fingerprint']); cases.add(annotation['case_group'])
        texts = {text_hash(normalized(r['source_text'])) for r in rows}
        meanings = {digest(r['canonical_ir']) for r in rows}; ids = {r['id'] for r in rows}
        require(len(texts) == len(ids) == len(rows) and len(meanings) == len(cases) == len(rows) // 2
            and not (texts & seen_texts or meanings & seen_meanings or templates & seen_templates
                     or ids & seen_ids or cases & seen_cases), 'authored split source/meaning/template/case overlap')
        require(dict(Counter(r['canonical_ir']['rules'][0]['modality'] for r in rows)) ==
                {m: len(rows) // 3 for m in ('O', 'P', 'F')}, 'modality denominator differs')
        seen_texts |= texts; seen_meanings |= meanings; seen_templates |= templates; seen_ids |= ids; seen_cases |= cases
        audits[panel] = {'rows': len(rows), 'meaning_groups': len(meanings), 'templates': len(templates),
                        'families': dict(Counter(r['family'] for r in labels))}
    old = old_corpus.load_training_inputs(inputs['manifest']['inputs']['prior_corpus']['path'])
    old_config = read_ref(inputs['manifest']['inputs']['prior_config'])
    source_refs = [v for k, v in old_config.items() if k.endswith('_sources')]
    known = [*old['new_train'], *old['new_tuning'], *old['fresh_sources'], *old['fresh_document_sources'],
             *inputs['sources']['real_exposed']]
    known += [r for pool in old['replay'].values() for r in pool]
    known += [r for pool in old['tuning'].values() for r in pool]
    for pin in source_refs:
        value = read_ref(pin); known.extend(value['challenge'] if type(value) is dict and 'challenge' in value else value)
    known_hashes = {text_hash(normalized(r['source_text'])) for r in known}
    require(not known_hashes & seen_texts and exposure['new_overlap_count'] == 0
        and exposure['prior_unique_normalized_sources'] == len(known_hashes)
        and exposure['prior_inventory_sha256'] == digest(sorted(known_hashes))
        and exposure['prior_source_inputs'] == source_refs and exposure['real_exposed_views'] == 86,
        'historical/exposed source exclusion audit differs')
    return {'panels': audits, 'known_unique_normalized_sources': len(known_hashes),
        'authored_source_count': len(seen_texts), 'source_overlap': 0, 'meaning_overlap': 0, 'template_overlap': 0,
        'real_exposed_rows': 86, 'independent_statutory_gold_count': 0,
        'scope': 'Distinct concrete templates within shared authored construction families; not unseen-grammar certification.'}


def verify_protocol(plan, inputs, frozen):
    require(plan['objectives'] == list(OBJECTIVES) and plan['architectures'] == list(ARCHITECTURES)
        and plan['seeds'] == list(SEEDS) and plan['additional_stage_steps'] == [200, 400]
        and plan['additional_updates_per_trial'] == 400 and plan['total_optimizer_updates'] == 2400
        and plan['optimizer'] == 'Adam' and plan['learning_rate'] == .001 and plan['optimizer_reset'] is True
        and plan['historical_optimizer_resumed'] is False and plan['batch_size'] == 12
        and plan['batch_quota'] == {'earlier': 3, 'historical_new': 3, 'new_pairs': 3, 'new_pair_rows': 6}
        and plan['consistency_weight'] == .25 and plan['fixed_sampler_and_same_architecture_parent_control'] is True
        and plan['inference_changed'] is plan['joint_search_enabled'] is False
        and plan['threads_per_worker'] == 1 and 1 <= plan['workers'] <= 3
        and plan['single_counts'] == SINGLE_COUNTS and plan['document_counts'] == DOCUMENT_COUNTS
        and plan['boundary_heads'] == inputs['boundary_heads'] and plan['retention_tolerance'] == 1
        and plan['unsupported_acceptance_tolerance'] == 0
        and plan['fresh_targets_opened'] is plan['regression_targets_opened'] is False,
        'predeclared authored role curriculum protocol differs')
    read_ref(inputs['config']['study_design'], parse=False)
    for pipeline in frozen['pipelines']:
        require(pipeline['boundary_checkpoint'] == inputs['boundary_heads'][pipeline['boundary_head']]['checkpoint'],
                'pipeline changed frozen boundary checkpoint')


def target_references(config, manifest):
    old_config = read_ref(config['prior_experiment_config'])
    old_manifest = read_ref(old_config['corpus_manifest'])
    single = {'fresh': manifest['artifacts']['challenge_targets'],
        'prior_consistency': old_manifest['artifacts']['challenge_targets'],
        **{panel: old_config[panel + '_targets'] for panel in
           ('prior_construction', 'earlier_regression', 'temporal_regression')}}
    documents = {'prior_consistency_documents': old_manifest['artifacts']['document_challenge_targets'],
        'prior_boundary_documents': old_config['prior_boundary_document_targets'],
        'exposed_documents': old_config['exposed_document_targets']}
    evidence = {key: manifest['artifacts'][key] for key in ('annotation_ledger', 'exposure_audit', 'challenge_pairs')}
    return single, documents, evidence


class SealedReadGuard:
    """Record real OS-level target reads and reject every pre-build attempt."""
    def __init__(self, references):
        self.paths = {str(Path(pin['path']).resolve()) for pin in references}
        self.released = False
        self.events = []

    def event(self, name, arguments):
        if name != 'open' or not isinstance(arguments[0], (str, bytes, Path)):
            return
        path = arguments[0].decode() if type(arguments[0]) is bytes else str(arguments[0])
        if str(Path(path).resolve()) in self.paths:
            self.events.append({'path': str(Path(path).resolve()), 'after_build_freeze': self.released})
            require(self.released, 'sealed target or layout evidence opened before native build freeze')


def real_diagnostics(inputs, frozen, singles, routing_summary_path):
    from scripts.ops.legal_ir import evaluate_legal_uscode_fidelity as evaluation
    from ipfs_datasets_py.logic.autoformal import legal_statutory_context as context
    route_summary_ref = ref(routing_summary_path); route_summary = read_ref(route_summary_ref)
    require(route_summary['schema'] == routing_audit.SCHEMA and route_summary['source_views'] == 86
        and route_summary['statutory_accuracy'] is None, 'frozen reference-free routing qualification required')
    decisions = read_ref(route_summary['real_routes'])
    manifest = read_ref(inputs['config']['real_source_manifest'])
    sources = evaluation.validate_manifest(manifest)
    require(previous.source_rows(sources) == inputs['sources']['real_exposed'], 'official real source view join differs')
    routing_audit.route_index(sources, decisions)
    original = read_ref(read_ref(route_summary['plan'])['prior_summary'])
    originals = {model['name']: model for model in original['models']}
    reports, aggregate = {}, Counter()
    for model in frozen['models']:
        generation = singles[model['name']]['real_exposed']
        rows = routing_audit.prediction_rows(generation, sources)
        routed = routing_audit.compare_routing(sources, rows, decisions)
        counts = Counter(row['status'] for row in rows)
        reasons = Counter(row.get('reason') for row in rows if row['status'] == 'abstained')
        require(sum(counts.values()) == 86, 'real-source denominator differs')
        unchanged = None
        if model['objective'] == 'parent':
            old = originals[f"consistency_{model['architecture']}-{model['seed']}"]
            require(old['checkpoint'] == model['checkpoint'] and read_ref(old['generation']) == generation,
                    'no-update parent real predictions changed from previous diagnostic study')
            unchanged = True
        reports[model['name']] = {'generation': frozen['files'][model['name']]['real_exposed'],
            'count': 86, 'decoded': counts['decoded'], 'abstained': counts['abstained'],
            'abstention_reasons': dict(reasons), 'routing': routed,
            'literal_source_diagnostics': [context.inspect_prediction(s, p) for s, p in zip(sources, rows)],
            'unchanged_parent_generation': unchanged, 'reference_accuracy': None, 'source_semantics_verified': False}
        aggregate.update(routed['counts'])
    return {'models': reports, 'routing_summary': route_summary_ref, 'route_decisions': route_summary['real_routes'],
        'source_views': 86, 'distinct_source_texts': 83, 'model_source_slots': 1032,
        'routing_counts': dict(aggregate), 'real_reference_count': 0, 'reference_accuracy': None,
        'source_semantics_verified': False, 'training_or_selection_used_real_sources': False,
        'candidate_suppression_is_accuracy_improvement': False,
        'scope': 'Exposed and overlapping 2024 statutory views; raw predictions and routing outcomes both retained.'}


def run(args):
    import torch
    torch.set_num_threads(1)
    from scripts.ops.legal_ir import run_legal_role_curriculum_experiment as runner
    from scripts.ops.legal_ir import prepare_legal_role_curriculum as corpus
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_role_curriculum as runtime
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consistency as parent_runtime
    from ipfs_datasets_py.logic.autoformal import legal_calendar_lake as gate
    require(type(args.workers) is int and 1 <= args.workers <= 3, 'one to three CPU replay workers required')
    folder, output = Path(args.run_directory).resolve(), Path(args.output).resolve()
    frozen_ref = ref(folder / 'generation-frozen.json'); frozen = read_ref(frozen_ref)
    require(frozen['schema'] == runner.SCHEMA and frozen['all_training_selection_and_generation_complete'] is True
        and frozen['fresh_targets_opened'] is frozen['regression_targets_opened'] is False
        and frozen['executed_optimizer_updates'] == 2400 and frozen['boundary_optimizer_updates'] == 0
        and frozen['training_executed'] is True, 'complete fixed-budget source-only generation freeze required')
    plan = read_ref(frozen['plan'])
    require(all(sha(path) == wanted for path, wanted in plan['producer_pins'].items()), 'frozen training source drift')
    config = read_ref(plan['config']); manifest = read_ref(config['corpus_manifest'])
    single_target_refs, document_target_refs, evidence_refs = target_references(config, manifest)
    guard = SealedReadGuard([*single_target_refs.values(), *document_target_refs.values(), *evidence_refs.values()])
    sys.addaudithook(guard.event)
    inputs = runner.load_config(plan['config']['path'])
    require(read_ref(frozen['sources']) == inputs['sources'] and read_ref(frozen['document_sources']) == inputs['document_sources']
        and read_ref(frozen['heads']) == frozen['models'] and read_ref(frozen['pipeline_heads']) == frozen['pipelines'],
        'frozen source/model/pipeline inventories differ')
    inventory = verify_inventory(frozen['models'], frozen['pipelines'], frozen['files'], frozen['document_files'],
                                 inputs['boundary_heads'], frozen['boundaries'])
    verify_protocol(plan, inputs, frozen)
    output.mkdir(parents=True, exist_ok=False)
    pins = dict(plan['producer_pins'])
    for module in (sys.modules[__name__], runner, corpus, runtime, parent_runtime, consistency_audit, routing_audit,
        retained, retained.prior, retained.calendar, retained.calendar_summary, retained.compose,
        boundary_qualification, boundary_qualification.attribution, boundary_qualification.boundary_audit,
        clauses, boundary, previous, gate):
        pins[str(Path(module.__file__).resolve())] = sha(module.__file__)
    qualification_plan = write(output / 'qualification-plan.json', {'schema': SCHEMA, 'generation_freeze': frozen_ref,
        'producer_pins': pins, 'routing_summary': ref(args.routing_summary), 'target_references': single_target_refs,
        'document_target_references': document_target_refs, 'posthoc_evidence': evidence_refs,
        'native_build_single_panel': 'fresh', 'native_build_document_panel': 'prior_consistency_documents',
        'fresh_single_build_slots': 12, 'exposed_regression_document_build_slots': 24,
        'fresh_targets_opened': False, 'exposed_document_panel_is_new_holdout': False})
    require(runtime._loss is parent_runtime._loss and runtime.next_batch_indices is parent_runtime.next_batch_indices,
            'role curriculum changed the frozen objective or sampler')
    fitting, sanity = verify_fitting(inputs), objective_sanity()
    selection = read_ref(frozen['selections'])
    jobs, training_audits = verify_training(inputs, frozen, selection)
    require(frozen['parent_fallbacks'] == [r['name'] for r in selection['trials'] if r['selection'] != 'candidate'],
            'parent fallback inventory differs')
    training_ref = write(output / 'training-and-selection-audit.json', {'schema': SCHEMA, 'selections': frozen['selections'],
        'fitting': fitting, 'objective_sanity': sanity, 'trials': training_audits,
        'executed_optimizer_updates': 2400, 'boundary_optimizer_updates': 0,
        'initial_numerical_predictions_equal_verified_against_replayed_parent': True,
        'optimizer_trajectory_replayed': False, **FALSE})
    for name, head in inputs['boundary_heads'].items():
        for panel, pin in frozen['boundaries'][name].items():
            jobs.append({'kind': 'boundary', 'name': name + '/' + panel, 'checkpoint': head['checkpoint'],
                'sources': inputs['document_sources'][panel], 'generation': pin})
    singles, documents = {}, {}
    for model in frozen['models']:
        name = model['name']; singles[name] = {}
        for panel, pin in frozen['files'][name].items():
            singles[name][panel] = read_ref(pin)
            require(len(singles[name][panel]['rows']) == SINGLE_COUNTS[panel], 'selected single inference dropped sources')
            jobs.append({'kind': 'single', 'name': name + '/' + panel, 'model': model,
                         'sources': inputs['sources'][panel], 'generation': pin})
    for pipeline in frozen['pipelines']:
        name = pipeline['name']; documents[name] = {}
        for panel, pin in frozen['document_files'][name].items():
            documents[name][panel] = read_ref(pin)
            require(len(documents[name][panel]['rows']) == DOCUMENT_COUNTS[panel], 'selected pipeline inference dropped documents')
            jobs.append({'kind': 'document', 'name': name + '/' + panel, 'model': pipeline,
                'sources': inputs['document_sources'][panel], 'generation': pin,
                'boundary': frozen['boundaries'][pipeline['boundary_head']][panel]})
    require(sum(len(j['sources']) for j in jobs if j.get('stage')) == 10800
        and sum(len(j['sources']) for j in jobs if not j.get('stage') and j['kind'] == 'single') == 16008
        and sum(len(j['sources']) for j in jobs if not j.get('stage') and j['kind'] == 'document') == 9216
        and sum(len(j['sources']) for j in jobs if j['kind'] == 'boundary') == 1536, 'complete replay denominators differ')
    replays = []
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context('spawn')) as pool:
        for future in as_completed([pool.submit(replay_job, job) for job in jobs]):
            value = future.result(); replays.append(value)
            print({'phase': 'replayed', 'kind': value['kind'], 'panel': value['name'], 'rows': value['rows']}, flush=True)
    for i, left in enumerate(frozen['models']):
        for right in frozen['models'][i + 1:]:
            if left['checkpoint'] == right['checkpoint'] and left['decoder_kind'] == right['decoder_kind']:
                require(singles[left['name']] == singles[right['name']], 'duplicate selected checkpoint outputs differ')
                if left['seed'] == right['seed']:
                    require(all(documents[left['name'] + '__' + p] == documents[right['name'] + '__' + p]
                                for p in ('parent', 'expanded')), 'duplicate selected checkpoint pipeline outputs differ')
    real_ref = write(output / 'real-source-diagnostics.json', real_diagnostics(inputs, frozen, singles, args.routing_summary))
    replay_ref = write(output / 'replay-frozen.json', {'schema': SCHEMA, 'generation_freeze': frozen_ref,
        'training_and_selection_audit': training_ref, 'real_source_diagnostics': real_ref,
        'panels': sorted(replays, key=lambda r: r['name']),
        'single_rows': sum(r['rows'] for r in replays if r['kind'] == 'single'),
        'document_rows': sum(r['rows'] for r in replays if r['kind'] == 'document'),
        'boundary_rows': sum(r['rows'] for r in replays if r['kind'] == 'boundary'),
        'stage_and_parent_tuning_rows': 10800, 'selected_single_rows': 16008, 'selected_document_rows': 9216,
        'fresh_and_regression_targets_opened': False, 'reference_derived_layout_evidence_opened': False, **FALSE})
    single_selections, document_selections = {}, {}
    for model in frozen['models']:
        name = model['name']; sources = inputs['sources']['fresh']; predictions = singles[name]['fresh']['rows']
        selected = retained.calendar.select_candidates(sources, predictions, toolchain=args.toolchain, policy=retained.calendar.POLICY)
        lookup = {s['id']: (s, p) for s, p in zip(sources, predictions)}
        for entry in selected['rows']:
            retained.calendar_summary.verify_entry(*lookup[entry['candidate']['candidate_id']], entry)
        require(selected['source_count'] == len(selected['rows']) + len(selected['excluded']) == 144, 'fresh build selection dropped sources')
        single_selections[name] = selected
    build_document_panel = 'prior_consistency_documents'
    for pipeline in frozen['pipelines']:
        name = pipeline['name']
        document_selections[name] = retained.document_selection(documents[name][build_document_panel]['rows'],
            inputs['document_sources'][build_document_panel], toolchain=args.toolchain)
    build_selection_ref = write(output / 'build-selection-frozen.json', {'schema': SCHEMA,
        'single': single_selections, 'document': document_selections, 'replay': replay_ref,
        'single_source_slots': 1728, 'document_source_slots': 2304,
        'document_panel': build_document_panel, 'document_panel_is_exposed_regression': True,
        'canonical_references_used_for_selection': False, 'fresh_targets_opened': False,
        'interpretation_policy': retained.calendar.POLICY})
    builds = {'single': {}, 'document': {}}
    for kind, selections in (('single', single_selections), ('document', document_selections)):
        for name, selected in selections.items():
            builds[kind][name] = retained.build_batches(selected['rows'], output / 'builds' / kind / name, args)
            print({'phase': 'built', 'kind': kind, 'model': name, 'supported_for_lowering': len(selected['rows'])}, flush=True)
    builds_ref = write(output / 'builds-frozen.json', {'schema': SCHEMA, **builds, 'selections': build_selection_ref,
        'replay': replay_ref, 'fresh_and_regression_targets_opened': False,
        'reference_derived_layout_evidence_opened': False, **FALSE})
    require(not guard.events, 'a sealed target read was attempted before reference release')
    guard.released = True
    print({'phase': 'references_released_after_build_freeze', 'builds': builds_ref}, flush=True)
    single_targets = {'tuning_' + panel: inputs['tuning'][panel] for panel in TUNING}
    for panel, pin in single_target_refs.items():
        single_targets[panel] = previous.reference_rows(read_ref(pin), inputs['sources'][panel])
    document_targets = {'document_tuning': inputs['document_tuning']}
    for panel, pin in document_target_refs.items():
        document_targets[panel] = read_ref(pin)
        require(clauses.source_rows(document_targets[panel]) == inputs['document_sources'][panel], 'document source/reference binding differs')
    evidence = {key: read_ref(pin) for key, pin in evidence_refs.items()}
    exposure_ref = write(output / 'authored-exposure-audit.json', audit_exposure(inputs, single_targets['fresh'], evidence))
    boundary_metrics = {name: {panel: boundary_qualification.score_boundaries(read_ref(pin), inputs['document_sources'][panel], document_targets[panel])
        for panel, pin in panels.items()} for name, panels in frozen['boundaries'].items()}
    single_metrics, document_metrics, model_reports, pipeline_reports = {}, {}, [], []
    for model in frozen['models']:
        name = model['name']
        single_metrics[name] = {panel: single_error_metrics(value, inputs['sources'][panel], single_targets[panel], enabled=model['enabled'])
            for panel, value in singles[name].items() if panel != 'real_exposed'}
        exact = {r['id']: r['exact'] for r in single_metrics[name]['fresh']['rows']}
        metric = retained.prior.build_accounting(single_selections[name], builds['single'][name], exact)
        model_reports.append({**model, 'single_metrics': {p: {k: v for k, v in result.items() if k not in ('rows', 'error_rows')}
            for p, result in single_metrics[name].items()}, 'single_builds': metric, 'real_source_diagnostics': real_ref})
    for pipeline in frozen['pipelines']:
        name = pipeline['name']; document_metrics[name] = {}
        for panel, generation in documents[name].items():
            b = boundary_metrics[pipeline['boundary_head']][panel]
            if panel == build_document_panel:
                metric = boundary_qualification.pipeline_funnel(generation, b, inputs['document_sources'][panel], document_targets[panel],
                    document_selections[name], builds['document'][name])
            else:
                measured = retained.score_documents(generation, inputs['document_sources'][panel], document_targets[panel])
                references = {r['candidate_id']: r for r in document_targets[panel]}; boundaries = {r['id']: r for r in b['rows']}
                rows = [boundary_qualification.attribution.pipeline_record(r, references[r['candidate_id']], boundaries[r['candidate_id']]) for r in generation['rows']]
                metric = {'metrics': {k: v for k, v in measured.items() if k != 'rows'}, 'rows': rows,
                    'attribution': boundary_qualification.attribution.pipeline_counts(rows), 'native_build_not_executed_on_this_panel': True}
            document_metrics[name][panel] = metric
        pipeline_reports.append({**pipeline, 'panels': {panel: {k: v for k, v in value.items() if k != 'rows'}
            for panel, value in document_metrics[name].items()}})
    single_totals, document_totals = {}, {}
    for objective in POLICIES:
        for architecture in ARCHITECTURES:
            arm = objective + '_' + architecture; group = [m for m in model_reports if m['arm'] == arm]
            single_totals[arm] = {'panels': {panel: {key: sum(m['single_metrics'][panel][key] for m in group)
                for key in ('count', 'decoded', 'abstained', 'exact')} for panel in SINGLE_COUNTS if panel != 'real_exposed'},
                'builds': {key: sum(m['single_builds'][key] for m in group)
                    for key in ('count', 'built', 'built_exact', 'built_reference_mismatch', 'build_invocations')}}
            for policy in ('parent', 'expanded'):
                pipeline_arm = arm + '__' + policy; group_pipelines = [p for p in pipeline_reports if p['arm'] == pipeline_arm]
                document_totals[pipeline_arm] = {'panels': {panel: {key: sum(p['panels'][panel]['metrics'][key] for p in group_pipelines)
                    for key in ('count', 'supported', 'unsupported', 'composed', 'abstained', 'exact', 'decision_exact',
                        'canonical_rule_list_exact', 'occurrence_boundaries_exact', 'unsupported_accepted')} for panel in DOCUMENT_COUNTS},
                    'builds': {key: sum(p['panels'][build_document_panel]['builds'][key] for p in group_pipelines)
                        for key in group_pipelines[0]['panels'][build_document_panel]['builds']}}
    details_ref = write(output / 'scored-details.json', {'single': single_metrics, 'document': document_metrics, 'boundary': boundary_metrics})
    require(all(sha(path) == wanted for path, wanted in pins.items()), 'qualifier or producer source drift')
    require(runner.load_config(plan['config']['path']) == inputs, 'frozen fitting/source input closure changed')
    for pin in [frozen_ref, frozen['plan'], frozen['sources'], frozen['document_sources'], frozen['heads'], frozen['pipeline_heads'], frozen['selections'],
        *single_target_refs.values(), *document_target_refs.values(), *evidence_refs.values(),
        *[r for panels in frozen['files'].values() for r in panels.values()],
        *[r for panels in frozen['document_files'].values() for r in panels.values()],
        *[r for panels in frozen['boundaries'].values() for r in panels.values()]]:
        read_ref(pin, parse=False)
    opens_ref = write(output / 'phase-open-audit.json', {'schema': SCHEMA, 'sealed_paths': sorted(guard.paths),
        'events': guard.events, 'before_build_freeze_attempts': sum(not row['after_build_freeze'] for row in guard.events),
        'build_freeze': builds_ref, 'all_target_reads_after_build_freeze': True})
    result = {'schema': SCHEMA, 'qualification_plan': qualification_plan, 'generation_freeze': frozen_ref,
        'training_and_selection_audit': training_ref, 'replay': replay_ref, 'builds': builds_ref, 'details': details_ref,
        'authored_exposure_audit': exposure_ref, 'phase_open_audit': opens_ref, 'real_source_diagnostics': real_ref,
        'reference_single': single_target_refs, 'reference_documents': document_target_refs, 'posthoc_evidence': evidence_refs,
        'models': model_reports, 'pipelines': pipeline_reports, 'single_totals': single_totals, 'document_totals': document_totals,
        'producer_pins': pins, 'parent_fallbacks': frozen['parent_fallbacks'], 'executed_optimizer_updates': 2400,
        'boundary_optimizer_updates': 0, 'inventory': inventory,
        'single_inference_rows_replayed': sum(r['rows'] for r in replays if r['kind'] == 'single'),
        'document_inference_rows_replayed': sum(r['rows'] for r in replays if r['kind'] == 'document'),
        'boundary_source_documents_replayed': sum(r['rows'] for r in replays if r['kind'] == 'boundary'),
        'clause_occurrences_replayed': sum(r.get('clause_occurrences_replayed', 0) for r in replays),
        'actual_lake_build_invocations': sum(b['backend_executed'] for selections in builds.values() for batches in selections.values() for b in batches),
        'build_attempts': sum(len(batches) for selections in builds.values() for batches in selections.values()),
        'native_single_build_slots': 12, 'native_exposed_document_build_slots': 24,
        'document_build_panel': build_document_panel, 'new_document_holdout_available': False,
        'fresh_target_and_regression_references_opened_after_replay_and_build_freezes': True,
        'reference_derived_novelty_evidence_opened_after_build_freeze': True,
        'test_results_used_for_selection_or_gate_revision': False, 'real_reference_accuracy_available': False,
        'scope': 'Authored role curriculum versus exact no-update parents; optimization and curriculum effects are not isolated. Native compilation is separate from authored exactness and unmeasured statutory fidelity.', **FALSE}
    write(output / 'summary.json', result)
    print({'complete': str(output / 'summary.json'), 'single_totals': single_totals, 'document_totals': document_totals}, flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-directory', required=True); parser.add_argument('--output', required=True)
    parser.add_argument('--routing-summary', required=True)
    parser.add_argument('--lake-executable', required=True); parser.add_argument('--toolchain', default='leanprover/lean4:v4.34.1')
    parser.add_argument('--workers', type=int, default=3)
    run(parser.parse_args())
