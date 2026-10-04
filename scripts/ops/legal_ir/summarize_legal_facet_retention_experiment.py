#!/usr/bin/env python3
"""Independent qualification of matched facet-retention training interventions.

Reuse frozen scoring/build primitives. Verify the new objective, exact matched
training traces and all source-only outputs before opening held-out references.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import math
import multiprocessing
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import summarize_legal_role_curriculum_experiment as prior

require, digest, read_ref, ref, write, sha = prior.require, prior.digest, prior.read_ref, prior.ref, prior.write, prior.sha
retained, previous, clauses, boundary = prior.retained, prior.previous, prior.clauses, prior.boundary
boundary_qualification, routing_audit = prior.boundary_qualification, prior.routing_audit
SealedReadGuard, single_error_metrics, expected_batch = prior.SealedReadGuard, prior.single_error_metrics, prior.expected_batch
SCHEMA = 'legal-facet-retention-independent-qualification/v1'
SEEDS, ARCHITECTURES = prior.SEEDS, prior.ARCHITECTURES
OBJECTIVES = ('base', 'facet_retention')
POLICIES = ('parent', *OBJECTIVES)
OLD_BOUNDS = {'earlier': 96, 'temporal': 120, 'prior_consistency': 96,
              'document_parent': 72, 'document_expanded': 72}
NEW_BOUNDS = {'role': 96, 'new': 192, 'new_document_parent': 72, 'new_document_expanded': 72}
GUARDS = ('guard_parent', 'guard_expanded', 'new_guard_parent', 'new_guard_expanded')


def selection_choice(stages, parent):
    bounds = {**OLD_BOUNDS, **NEW_BOUNDS}
    require(set(parent) == set(bounds) and all(type(parent[k]) is int and 0 <= parent[k] <= n for k, n in bounds.items()),
            'closed bounded same-parent retention and new-panel metrics required')
    require(type(stages) is list and [r.get('steps') for r in stages] == [400, 800], 'both400/800 stages required')
    fields = {**bounds, **{key: 24 for key in GUARDS}}
    for stage in stages:
        require(set(stage) == {'steps', *fields} and all(type(stage[k]) is int and 0 <= stage[k] <= n for k, n in fields.items()),
                'closed bounded tuning-only metrics required')
    eligible = [stage for stage in stages if all(stage[k] >= parent[k] - 1 for k in OLD_BOUNDS)
        and all(stage[k] >= parent[k] for k in NEW_BOUNDS) and all(stage[k] == 0 for k in GUARDS)]
    return max(eligible, key=lambda stage: (2 * stage['role'] + stage['new'], stage['new_document_expanded'],
        stage['new_document_parent'], stage['temporal'], stage['document_expanded'], stage['document_parent'],
        stage['earlier'], -stage['steps'])) if eligible else None


def group_replay_jobs(jobs):
    """Share a loaded immutable checkpoint, while recomputing every saved panel."""
    require(len({job['name'] for job in jobs}) == len(jobs), 'unique replay job names required')
    groups = {}
    for job in jobs:
        if job['kind'] == 'boundary':
            checkpoint, kind = job['checkpoint'], 'boundary'
        else:
            checkpoint, kind = job['model']['checkpoint'], job['model']['decoder_kind']
        key = (kind, checkpoint['sha256'])
        groups.setdefault(key, {'decoder_kind': kind, 'checkpoint': checkpoint, 'jobs': []})['jobs'].append(job)
    return list(groups.values())


def replay_with_decoder(job, decoder):
    expected = read_ref(job['generation'])
    if job.get('stage'): expected = expected['generation']
    copied = occurrences = 0
    if job['kind'] == 'boundary':
        actual = clauses.decode_all(decoder, job['sources'])
        checkpoint = job['checkpoint']
    elif job['kind'] == 'single':
        actual = previous.generate(decoder, job['sources'], ablation='none')
        checkpoint = job['model']['checkpoint']
        for source, prediction in zip(job['sources'], actual['rows']):
            copied += retained.prior.source_audit.assert_source_copy(prediction, source)
    else:
        checkpoint = job['model']['checkpoint']
        segments = read_ref(job['boundary'])
        actual = {'rows': clauses.integrate(segments, job['sources'], decoder),
            'target_access': False, 'references_supplied': False, 'training_executed': False}
        lookup = {r['candidate_id']: r for r in segments['rows']}
        for row in actual['rows']:
            segment = lookup[row['candidate_id']]
            require(row['segmentation_status'] == segment['status'], 'pipeline changed frozen segmentation status')
            if segment['plan'] is None:
                require(row['composition'] is row['clause_generation'] is None, 'boundary abstention emitted clauses')
            else:
                plan = segment['plan']
                retained.compose.validate_source_plan(plan, expected_plan_sha256=plan['plan_sha256'])
                require(len(row['clause_generation']['rows']) == plan['clause_count'], 'clause occurrence inventory differs')
                for clause, prediction in zip(plan['clauses'], row['clause_generation']['rows']):
                    copied += retained.prior.source_audit.assert_source_copy(prediction, clause); occurrences += 1
                if row['composition'] is not None:
                    require(row['composition']['source_plan'] == plan, 'source occurrence intervals changed')
                    retained.compose.validate_composition(row['composition'], expected_plan_sha256=plan['plan_sha256'])
    require(actual == expected, 'independent full numerical replay differs: ' + job['name'])
    return {'kind': job['kind'], 'name': job['name'], 'rows': len(job['sources']), 'generation': job['generation'],
        'checkpoint': checkpoint, 'boundary': job.get('boundary'), 'source_inputs_sha256': digest(job['sources']),
        'recorded_generation_sha256': digest(actual), 'exact_recorded_payload_replay': True,
        'clause_occurrences_replayed': occurrences, 'copied_facets_verified': copied,
        'stage_tuning': job.get('stage', False), 'training_diagnostic': job.get('training_diagnostic', False),
        'recomputed_for_this_saved_panel': True, 'target_access': False}


def replay_group(group):
    import torch
    torch.set_num_threads(1)
    if group['decoder_kind'] == 'boundary':
        decoder = boundary.ClauseBoundaryDecoder(read_ref(group['checkpoint']))
    else:
        from scripts.ops.legal_ir import run_legal_facet_retention_experiment as runner
        decoder = runner.load_decoder(group['checkpoint'], group['decoder_kind'])
    result = []
    for job in group['jobs']:
        checkpoint = job['checkpoint'] if job['kind'] == 'boundary' else job['model']['checkpoint']
        require(checkpoint['sha256'] == group['checkpoint']['sha256'], 'group changed checkpoint identity')
        read_ref(checkpoint, parse=False)
        result.append(replay_with_decoder(job, decoder))
        print({'phase': 'replayed', 'name': job['name'], 'rows': len(job['sources'])}, flush=True)
    return result


def brute_force_overlap(left, right):
    """Independent tiny-model oracle over every pair of nonempty valid spans."""
    count = len(left)
    require(1 <= count <= 4 and len(right) == count, 'tiny matching span spaces required')
    return sum(float(left[a][b]) * float(right[c][d]) for a in range(count) for b in range(a, count)
               for c in range(count) for d in range(c, count) if max(a, c) <= min(b, d))


def teacher_eligibility(output, records):
    """Independently enumerate the teacher's accepted, label-correct decisions."""
    fields = ('object', 'conditions', 'exceptions', 'temporal')
    result = []
    for index, record in enumerate(records):
        count = len(record['tokens']); presence, endpoints = 0, 0
        for optional, _ in enumerate(fields):
            facet = optional + 2
            scores = output['presence'][index, optional].detach()
            gold = bool(record['labels']['presence'][facet])
            correct = bool(scores[1] > scores[0]) == gold and float(abs(scores[1] - scores[0])) > 1e-7
            if not correct: continue
            presence += 1
            if optional == 0 or not gold: continue
            values = (output['start'][index, facet, :count, None] + output['end'][index, facet, None, :count]).detach()
            ranked = sorted(((float(values[left, right]), left, right) for left in range(count)
                             for right in range(left, count)), reverse=True)
            unique = len(ranked) == 1 or ranked[0][0] - ranked[1][0] > 1e-7
            if unique and ranked[0][1:] == tuple(record['labels']['spans'][facet]): endpoints += 2
        result.append({'teacher_presence_terms': presence, 'teacher_endpoint_terms': endpoints,
                       'overlap_facet_pairs': math.comb(sum(record['labels']['presence']), 2)})
    return result


SINGLE_COUNTS = {'tuning_earlier':96,'tuning_temporal':120,'tuning_prior_consistency':96,'tuning_prior_role':96,'tuning_new':192,
    'fresh':192,'prior_role':144,'prior_consistency':144,'prior_construction':180,'earlier_regression':192,'temporal_regression':180,'real_exposed':86}
DOCUMENT_COUNTS = {key:96 for key in ('document_tuning','new_document_tuning','fresh_documents',
    'prior_consistency_documents','prior_boundary_documents','exposed_documents')}
TUNING = ('earlier','temporal','prior_consistency','prior_role','new')
RETENTION = (*OLD_BOUNDS, *NEW_BOUNDS)
FALSE = retained.FALSE
verify_pairs = prior.verify_pairs
verify_annotation_pairs = prior.verify_annotation_pairs
validate_fresh_coordinates = prior.validate_fresh_coordinates
consistency_audit = prior.consistency_audit


class TeacherEligibilityCache(dict):
    def exact_batch_counts(self, identities):
        import torch
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as span
        key=tuple(identities)
        if key not in self.batch_counts:
            batch=[self.records[identity] for identity in identities]
            with torch.no_grad(): counts=teacher_eligibility(self.model(*span._batch(torch,batch)),batch)
            self.batch_counts[key]={field:sum(row[field] for row in counts[:6]) for field in ('teacher_presence_terms','teacher_endpoint_terms')}
        return self.batch_counts[key]


def teacher_cache(parent, inputs):
    """Numerically evaluate the frozen parent once per labeled historical source."""
    import torch
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_mixed_replay as mixed
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as span
    records, _ = mixed._splits(inputs['training'], [])
    by_id = {row['id']:row for row in records}
    historical = [row for pool in inputs['replay'].values() for row in pool]
    model = mixed._model(torch, parent['model_config'])
    model.load_state_dict({key:torch.tensor(value,dtype=template.dtype) for key,template in model.state_dict().items()
        for value in [parent['model_state'][key]]}, strict=True)
    model.eval()
    for parameter in model.parameters(): parameter.requires_grad_(False)
    before=mixed._state_digest(model); result=TeacherEligibilityCache()
    result.model=model;result.records=by_id;result.batch_counts={}
    with torch.no_grad():
        for offset in range(0,len(historical),48):
            batch=[by_id[row['id']] for row in historical[offset:offset+48]]
            output=model(*span._batch(torch,batch))
            for row,counts in zip(batch,teacher_eligibility(output,batch),strict=True): result[row['id']]=counts
    require(mixed._state_digest(model)==before and all(p.grad is None for p in model.parameters()), 'independent teacher audit changed weights')
    require(len(result)==3120, 'all historical teacher decisions required')
    # The overlap count is label-derived and also needed for new paired rows.
    for row in records:
        if row['id'] not in result: result[row['id']]={'overlap_facet_pairs':math.comb(sum(row['labels']['presence']),2)}
    return result

def verify_training_report(report, preceding, checkpoint, inputs, eligibility):
    start, finish = preceding['progress']['optimizer_steps'], checkpoint['progress']['optimizer_steps']
    config, model_config = checkpoint['training_config'], checkpoint['model_config']
    objective = config['objective']; enabled = model_config['trigger_enabled']; weight = .25
    require(objective in OBJECTIVES, 'matched objective required')
    require(finish - start == report['optimizer_steps'] == 400 and report['new_optimizer_steps_total'] == finish
        and report['training_executed'] is True and report['stopped_reason'] == 'step_limit'
        and report['tuning_used_for_fit'] is False and report['objective'] == objective,
        'complete fixed400-update training stage with fitting-only labels required')
    require(report['checkpoint_sha256'] == digest(checkpoint)
        and report['consistency_parent_checkpoint_sha256'] == checkpoint['consistency_parent_checkpoint_sha256']
        and report['consistency_parent_optimizer_steps'] == checkpoint['consistency_parent_optimizer_steps'] == 800,
        'training report checkpoint or consistency800 parent binding differs')
    require(len(report['batch_losses']) == len(report['batch_loss_components']) == len(report['batch_exposures']) == 400
        and report['domain_exposures'] == {'earlier': 1200, 'new': 3600} and report['pair_exposures'] == 1200,
        'complete3+3+3pair stage exposures required')
    require(type(report['elapsed_seconds']) in (int, float) and math.isfinite(report['elapsed_seconds']) and report['elapsed_seconds'] > 0
        and math.isfinite(report['gradient_norm_max']) and report['gradient_norm_max'] >= 0,
        'finite training timing and gradient receipts required')
    pools = {'earlier': [r['id'] for r in inputs['replay']['earlier']],
        'historical_new': [r['id'] for name in ('prior_new', 'temporal', 'prior_consistency', 'prior_role') for r in inputs['replay'][name]],
        'pairs': [[r['left_id'], r['right_id']] for r in inputs['training_pairs']]}
    numerical = ('semantic', 'trigger', 'actor', 'semantic_earlier', 'semantic_new', 'actor_earlier', 'actor_new',
        'js_modality', 'js_presence', 'js_endpoints', 'base_ce', 'consistency_js', 'weighted_consistency', 'total', 'base_objective','teacher_presence_kl','teacher_endpoint_kl','teacher_kl','span_overlap','weighted_teacher','weighted_overlap')
    require(report['teacher_training_labels_only'] is report['teacher_state_unchanged'] is report['teacher_gradients_disabled'] is True, 'teacher was not frozen or used unadmitted labels')
    exact_batch_checks=[]
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
            and close(parts['base_objective'], parts['base_ce'] + parts['weighted_consistency']) and close(loss, parts['total']),
            'independent CE/three-component JS/weighted total accounting differs')
        teacher_weight, overlap_weight = (.5,.1) if objective == 'facet_retention' else (0.,0.)
        expected_counts = {key:sum(eligibility[identity][key] for identity in exposure['ids'][:6])
            for key in ('teacher_presence_terms','teacher_endpoint_terms')}
        expected_counts['overlap_facet_pairs']=sum(eligibility[identity]['overlap_facet_pairs'] for identity in exposure['ids'])
        if any(parts[key]!=expected_counts[key] for key in ('teacher_presence_terms','teacher_endpoint_terms')) and isinstance(eligibility,TeacherEligibilityCache):
            original={key:expected_counts[key] for key in ('teacher_presence_terms','teacher_endpoint_terms')}
            exact=eligibility.exact_batch_counts(exposure['ids']);expected_counts.update(exact)
            exact_batch_checks.append({'step':step,'cached':original,'exact_batch':exact})
        require(all(parts[key]==value for key,value in expected_counts.items()), 'independent teacher-label eligibility or gold-present overlap counts differ')
        require(parts['teacher_weight']==teacher_weight and parts['overlap_weight']==overlap_weight
            and -2e-6 <= parts['span_overlap'] <= 1+2e-6
            and close(parts['teacher_kl'],(parts['teacher_presence_kl']+parts['teacher_endpoint_kl'])/2)
            and close(parts['weighted_teacher'],teacher_weight*parts['teacher_kl'])
            and close(parts['weighted_overlap'],overlap_weight*parts['span_overlap'])
            and close(parts['total'],parts['base_objective']+parts['weighted_teacher']+parts['weighted_overlap']),
            'matched loss intervention arithmetic or bounded overlap differs')
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
    return {'additional_steps_before': start, 'additional_steps_after': finish, 'optimizer_updates': 400,
        'domain_exposures': report['domain_exposures'], 'pair_exposures': 1200,
        'batch_trace_sha256': digest(report['batch_exposures']), 'same_semantics_pairs_only': True,
        'independent_schedule_and_loss_accounting_verified': True, 'exact_batch_teacher_rechecks':exact_batch_checks, 'optimizer_trajectory_replayed': False}


def verify_inventory(models, pipelines, files, document_files, heads, boundaries):
    expected_models = {f'{objective}_{architecture}-{seed}' for objective in POLICIES
        for architecture in ARCHITECTURES for seed in SEEDS}
    expected_pipelines = {name + '__' + policy for name in expected_models for policy in ('parent', 'expanded')}
    expected_heads = {'parent', *(f'expanded-{seed}' for seed in SEEDS)}
    require(len(models) == 18 and {m['name'] for m in models} == set(files) == expected_models
        and len(pipelines) == 36 and {p['name'] for p in pipelines} == set(document_files) == expected_pipelines
        and set(heads) == set(boundaries) == expected_heads,
        'complete18 single models/36 document pipelines/four fixed boundary heads required')
    by_model = {m['name']: m for m in models}
    for model in models:
        require(model['name'] == f"{model['objective']}_{model['architecture']}-{model['seed']}"
            and model['enabled'] is (model['architecture'] == 'grounding')
            and model['decoder_kind'] in ('consistency', 'facet_retention')
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
    return {'single_model_slots': 18, 'document_pipeline_slots': 36, 'fixed_boundary_heads': 4,
        'selected_single_rows': 30924, 'selected_pipeline_documents': 20736, 'fixed_boundary_documents': 2304}




def tuning_audit(fields,item,inputs,frozen,label):
    jobs,normalized=[],{}
    for panel in TUNING:
        reference=fields['tuning_'+panel];saved=read_ref(reference);sources=inputs['sources']['tuning_'+panel]
        metric=previous.score(saved['generation']['rows'],sources,inputs['tuning'][panel])
        require(saved['metrics']==metric and fields['tuning_'+panel+'_exact']==metric['exact'],'independent single tuning counts differ')
        normalized['role' if panel=='prior_role' else panel]=metric['exact']
        jobs.append({'kind':'single','name':label+'/tuning_'+panel,'model':item,'sources':sources,'generation':reference,'stage':True})
    for panel,prefix in (('document_tuning',''),('new_document_tuning','new_')):
        for policy in ('parent','expanded'):
            reference=fields[panel+'_'+policy];saved=read_ref(reference);sources=inputs['document_sources'][panel]
            metric=retained.score_documents(saved['generation'],sources,inputs[panel])
            require(saved['metrics']==metric and fields['tuning_'+prefix+'document_'+policy+'_exact']==metric['exact']
                and fields['tuning_'+prefix+'document_'+policy+'_unsupported_accepted']==metric['unsupported_accepted'], 'independent joint document tuning differs')
            normalized[prefix+'document_'+policy]=metric['exact'];normalized[prefix+'guard_'+policy]=metric['unsupported_accepted']
            head='parent' if policy=='parent' else f"expanded-{item['seed']}"
            jobs.append({'kind':'document','name':label+'/'+panel+'_'+policy,'model':item,'sources':sources,
                'generation':reference,'boundary':frozen['boundaries'][head][panel],'stage':True})
    reference=fields['training_new'];saved=read_ref(reference)
    metric=previous.score(saved['generation']['rows'],inputs['training_sources'],inputs['new_train'])
    require(saved['metrics']==metric and fields['training_new_exact']==metric['exact'] and metric['count']==768
        and saved['diagnostic_only'] is True and saved['checkpoint_selection_uses_this_metric'] is False, 'TRAIN diagnostic bookkeeping differs')
    jobs.append({'kind':'single','name':label+'/training_new','model':item,'sources':inputs['training_sources'],
        'generation':reference,'stage':True,'training_diagnostic':True})
    return jobs,normalized

def verify_training(inputs, frozen, selection):
    from scripts.ops.legal_ir import run_legal_facet_retention_experiment as runner
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_facet_retention as runtime
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consistency as parent_runtime
    require(selection['executed_optimizer_updates'] == 9600 and selection['fresh_targets_opened'] is selection['regression_targets_opened'] is False,
            'complete pre-reference fitting freeze required')
    trials = selection['trials']; models = {m['name']: m for m in frozen['models']}
    require(len(trials) == 12 and {(r['objective'], r['architecture'], r['seed']) for r in trials} ==
        {(o, a, s) for o in OBJECTIVES for a in ARCHITECTURES for s in SEEDS}, 'all12 matched objective/architecture/seed trials required')
    parent_tuning = read_ref(selection['parent_tuning']); jobs, audits, parents, eligibility_by_parent = [], [], {}, {}
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
        eligibility_by_parent[name]=teacher_cache(read_ref(parent_ref),inputs)
        for panel in TUNING:
            require(read_ref(parent_tuning[name]['tuning_' + panel])['generation'] == read_ref(frozen['files'][name]['tuning_' + panel]),
                    'parent reference and selected single tuning outputs differ')
        for panel, policy in ((p,b) for p in ('document_tuning','new_document_tuning') for b in ('parent','expanded')):
            require(read_ref(parent_tuning[name][panel + '_' + policy])['generation'] == read_ref(frozen['document_files'][name + '__' + policy][panel]),
                    'parent reference and selected document tuning outputs differ')
    for trial in trials:
        name, seed, architecture, objective = (trial[k] for k in ('name', 'seed', 'architecture', 'objective'))
        require(trial == models[name] and trial['executed_steps'] == 800 and trial['enabled'] is (architecture == 'grounding')
            and trial['fresh_targets_opened'] is trial['regression_targets_opened'] is False
            and trial['trial_wall_limit_seconds']==600 and 0<trial['trial_wall_seconds']<=600,
            'trial identity/architecture/budget differs')
        require({k: v for k, v in trial.items() if k != 'selection_record'} == read_ref(trial['selection_record']), 'trial selection record differs')
        parent_name = f'parent_{architecture}-{seed}'; parent_ref = models[parent_name]['checkpoint']
        require(trial['parent'] == parent_ref and trial['parent_tuning'] == parent_tuning[parent_name], 'same-architecture/seed parent tuning anchor differs')
        parent = parent_runtime.load_checkpoint(parent_ref['path'], expected_sha256=parent_ref['sha256'])
        require(parent['progress']['optimizer_steps'] == 800 and parent['model_config']['seed'] == seed
            and parent['model_config']['trigger_enabled'] is trial['enabled'], 'frozen consistency800 parent architecture differs')
        initial = runtime.load_checkpoint(trial['initial_checkpoint']['path'], expected_sha256=trial['initial_checkpoint']['sha256'])
        reconstructed = runtime.build_checkpoint(parent, inputs['training'], tuning, pairs, objective=objective, seed=seed, learning_rate=.001, batch_size=12)
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
        for panel in (*TUNING, 'training_new'):
            key=panel if panel=='training_new' else 'tuning_'+panel
            a = read_ref(initialization['parent_tuning'][key]); b = read_ref(initialization['tuning'][key])
            require(a['generation']['rows'] == b['generation']['rows'] and a['metrics'] == b['metrics'], 'initial source predictions/logits changed')
            require(all(report['checkpoint_sha256'] == digest(initial) for report in b['generation']['reports']), 'initial inference checkpoint metadata differs')
        for panel, policy in ((p,b) for p in ('document_tuning','new_document_tuning') for b in ('parent','expanded')):
            a = read_ref(initialization['parent_tuning'][panel + '_' + policy]); b = read_ref(initialization['tuning'][panel + '_' + policy])
            require(runner.document_signature(a['generation']) == runner.document_signature(b['generation']) and a['metrics'] == b['metrics'],
                    'initial learned-boundary pipeline predictions changed')
        require([s['steps'] for s in trial['stages']] == [400, 800], 'complete400/800 candidate inventory required')
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
            report_audit = verify_training_report(report, previous_checkpoint, checkpoint, inputs, eligibility_by_parent[parent_name])
            item = {**trial, 'checkpoint': stage['checkpoint'], 'decoder_kind': 'facet_retention'}
            local_jobs, scores = tuning_audit(stage, item, inputs, frozen, name + f"/stage-{stage['steps']}")
            jobs.extend(local_jobs); normalized.append({'steps': stage['steps'], **scores})
            wanted_eligible = (all(scores[k] >= parents[parent_name][k]-1 for k in OLD_BOUNDS)
                and all(scores[k] >= parents[parent_name][k] for k in NEW_BOUNDS) and all(scores[k]==0 for k in GUARDS))
            require(stage['eligible'] is wanted_eligible, 'recorded multi-panel retention eligibility differs')
            stages.append({**report_audit, 'checkpoint': stage['checkpoint'], 'training_report': stage['training_report'],
                'tuning': scores, 'eligible': wanted_eligible})
            previous_checkpoint = checkpoint
        chosen = selection_choice(normalized, parents[parent_name])
        steps = chosen['steps'] if chosen else 0
        checkpoint_ref = next(s['checkpoint'] for s in trial['stages'] if s['steps'] == steps) if chosen else parent_ref
        status = 'candidate' if chosen else 'parent_fallback_no_acceptable_replacement'
        require(trial['selected_steps'] == steps and trial['checkpoint'] == checkpoint_ref and trial['selection'] == status
            and trial['decoder_kind'] == ('facet_retention' if chosen else 'consistency'), 'independent tuning-only candidate/fallback choice differs')
        chosen_fields = next(s for s in trial['stages'] if s['steps'] == steps) if chosen else parent_tuning[parent_name]
        for panel in TUNING:
            require(read_ref(chosen_fields['tuning_' + panel])['generation'] == read_ref(frozen['files'][name]['tuning_' + panel]), 'selected single tuning differs from chosen stage')
        for panel, policy in ((p,b) for p in ('document_tuning','new_document_tuning') for b in ('parent','expanded')):
            require(read_ref(chosen_fields[panel + '_' + policy])['generation'] == read_ref(frozen['document_files'][name + '__' + policy][panel]),
                    'selected document tuning differs from chosen stage')
        audits.append({'name': name, 'objective': objective, 'architecture': architecture, 'seed': seed, 'parent': parent_ref,
            'initial_checkpoint': trial['initial_checkpoint'], 'initial_model_state_sha256': digest(parent['model_state']),
            'stages': stages, 'parent_tuning': parents[parent_name], 'selection': status, 'selected_steps': steps,
            'checkpoint': checkpoint_ref, 'executed_optimizer_updates': 800,
            'historical_optimizer_resumed': False, 'optimizer_trajectory_replayed': False})
    trial_receipts = []
    for trial in trials:
        exposures = [row for stage in trial['stages'] for row in read_ref(stage['training_report'])['batch_exposures']]
        require(len(exposures) == 800, 'complete update trace required')
        trial_receipts.append({'objective':trial['objective'],'architecture': trial['architecture'], 'seed': trial['seed'], 'parent': trial['parent'],
            'batch_count': 800, 'batch_exposures_sha256': digest(exposures), 'same_architecture_no_update_control': True, 'same_batch_order_as_other_objective':True})
    for architecture in ARCHITECTURES:
        for seed in SEEDS:
            pair=[r for r in trial_receipts if r['architecture']==architecture and r['seed']==seed]
            require(len(pair)==2 and pair[0]['parent']==pair[1]['parent'] and pair[0]['batch_exposures_sha256']==pair[1]['batch_exposures_sha256'], 'matched objective parent or complete minibatch trace differs')
    require(selection['trial_update_audit'] == trial_receipts, 'frozen trial update receipt differs')
    return jobs, audits


def verify_fitting(inputs):
    from scripts.ops.legal_ir import prepare_legal_role_curriculum as old_corpus
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_mixed_replay as mixed
    old=old_corpus.load_training_inputs(inputs['manifest']['inputs']['prior_corpus']['path'])
    replay={**old['replay'],'prior_role':old['new_train']}
    require(inputs['replay']==replay and {k:len(v) for k,v in replay.items()}==
        {'earlier':1152,'prior_new':600,'temporal':600,'prior_consistency':384,'prior_role':384}, 'historical pool/order changed')
    artifacts=inputs['manifest']['artifacts'];train,tune=(read_ref(artifacts[k]) for k in ('new_training','new_tuning'))
    pairs,tpairs=(read_ref(artifacts[k]) for k in ('training_pairs','tuning_pairs'))
    require(inputs['training']==[r for name in ('earlier','prior_new','temporal','prior_consistency','prior_role') for r in replay[name]]+train
        and inputs['new_train']==train and inputs['training_pairs']==pairs and inputs['tuning']['new']==tune
        and inputs['tuning_pairs']==tpairs,'complete fitting labels/order/pairs differ')
    require(all(inputs['tuning'][key]==value for key,value in {**old['tuning'],'prior_role':old['new_tuning']}.items()), 'retention tuning changed')
    training,tuning=verify_pairs(train,pairs),verify_pairs(tune,tpairs)
    require((training['pairs'],tuning['pairs'])==(384,96) and len(training['case_groups'])==384 and len(tuning['case_groups'])==96
        and not set(training['case_groups'])&set(tuning['case_groups']),'paired case groups differ')
    parsed,pt=mixed._splits(inputs['training'],[r for panel in TUNING for r in inputs['tuning'][panel]])
    require(len(parsed)==3888 and len(pt)==600,'complete coordinate labels required')
    real=inputs['sources']['real_exposed'];rh={digest(r['source_text']) for r in real}
    require(len(real)==86 and len({r['id'] for r in real})==86 and len(rh)==83
        and not rh&{digest(r['source_text']) for r in inputs['training']},'exposed real sources entered fitting')
    require(clauses.source_rows(read_ref(artifacts['document_tuning_targets']))==inputs['document_sources']['new_document_tuning'], 'new tuning document identity differs')
    return {'training_pairs':training,'tuning_pairs':tuning,'historical_rows':3120,'new_rows':768,'total_training_rows':3888,
        'explicit_coordinate_and_trigger_labels_validated':True,'historical_replay_and_tuning_preserved':True,'real_views_used_as_supervision':0}


def role_layout(row):
    import re
    from scripts.ops.legal_ir import prepare_legal_grounding_curriculum as old
    text=row['source_text'];cursor=0;pieces=[]
    for start,end,field in sorted((s[0],s[1],f) for f,s in row['facet_spans'].items() if s is not None):
        require(type(start) is int and type(end) is int and cursor<=start<end<=len(text),'layout coordinates overlap or escape source')
        pieces.extend((text[cursor:start],'<'+field+'>'));cursor=end
    pieces.append(text[cursor:]);masked=''.join(pieces).casefold()
    masked=re.sub(r'\b\d+\b','#',masked);masked=re.sub(r'(?<=\()\w(?=\))','#',masked)
    masked=' '.join(masked.split())
    for cue in sorted(set(old.TRIGGER_MEANINGS)|{'shall','must','may','is permitted to','must not','may not'},key=len,reverse=True):
        masked=re.sub(r'\b'+re.escape(cue)+r'\b','<modal>',masked)
    return masked.rstrip('.;')


def verify_annotation(row,label,panel):
    import hashlib
    text=row['source_text'];rule=row['canonical_ir']['rules'][0]
    require(label['panel']==panel and label['id']==row['id'] and label['source_sha256']==hashlib.sha256(text.encode()).hexdigest()
        and label['facet_spans']==row['facet_spans'] and label['trigger_span']==row['trigger_span']
        and label['annotation_authority']=='authored_controlled_example_not_statutory_gold','annotation source or authority differs')
    require(label['presence_mask']==sum(1<<i for i,f in enumerate(('conditions','exceptions','temporal')) if rule[f]),'annotation optional presence mask differs')
    intervals=sorted((s[0],s[1],f) for f,s in {**row['facet_spans'],'trigger':row['trigger_span']}.items() if s is not None)
    cursor=0
    for start,end,field in intervals:
        require(type(start) is int and type(end) is int and cursor<=start<end<=len(text),'facet/trigger overlap or invalid interval')
        if field!='trigger':
            value=rule[field];value=value[0] if isinstance(value,list) else value
            require(text[start:end]==value,'facet literal does not match exact source interval')
        cursor=end
    template=role_layout(row)
    require(label['template']==template and label['template_fingerprint']==hashlib.sha256(template.encode()).hexdigest(),'independent modal-normalized template differs')
    for note in label['editorial_context']:
        start,end=note['start_char'],note['end_char']
        require(0<=start<end<=len(text) and text[start:end]==note['source_text'] and note['author_stipulated_role']=='nonoperative_editorial_context'
            and all(end<=a or start>=b for a,b,_ in intervals),'editorial context overlaps operative facet')
    for cue in label['qualifier_cues']:
        start,end=cue['start_char'],cue['end_char']
        require(cue['field'] in ('conditions','exceptions') and 0<=start<end<=len(text) and text[start:end]==cue['source_text']
            and all(end<=a or start>=b for a,b,_ in intervals),'qualifier cue annotation differs')
    return {'template_fingerprint':label['template_fingerprint'],'case_group':label['case_group']}


def document_clauses(rows,annotations):
    lookup={a['candidate_id']:a for a in annotations};result=[]
    for row in rows:
        a=lookup[row['candidate_id']]
        require(a['source_sha256']==row['source_sha256']==boundary.text_sha(row['source_text']) and a['supported'] is row['supported']
            and a['guard']==row['unsupported_reason'] and len(a['clause_coordinates'])==a['clause_occurrences']==len(row['clauses']), 'document occurrence annotation differs')
        unique=len({digest(c['rule']) for c in row['clauses']})
        require(a['unique_rules']==unique and row['repeated_rule_occurrences'] is (unique<len(row['clauses'])),'duplicate occurrences were collapsed')
        cursor=0
        for i,(c,coord) in enumerate(zip(row['clauses'],a['clause_coordinates'],strict=True)):
            left,right=c['char_start'],c['char_end']
            require(cursor<=left<right<=len(row['source_text']) and coord['clause_index']==i and coord['char_start']==left and coord['char_end']==right,'clause occurrence interval differs')
            cursor=right;text=row['source_text'][left:right]
            fields={f:[x-left for x in span] if span else None for f,span in coord['facet_spans'].items()}
            rule=c['rule'];presence=sum(1<<j for j,f in enumerate(('conditions','exceptions','temporal')) if rule[f])
            require(coord['presence_mask']==presence,'document annotation presence mask differs')
            intervals=[]
            for field,span in fields.items():
                value=rule[field];value=(value[0] if value else None) if isinstance(value,list) else value
                require((span is None)==(value is None),'document omitted or invented qualifier coordinate')
                if span is not None:
                    require(0<=span[0]<span[1]<=len(text) and text[slice(*span)]==value,'document literal source interval differs')
                    intervals.append(span)
            trigger=[x-left for x in coord['trigger_span']];intervals.append(trigger)
            require(0<=trigger[0]<trigger[1]<=len(text),'document trigger leaves clause')
            ordered=sorted(intervals);require(all(a[1]<=b[0] for a,b in zip(ordered,ordered[1:])),'document facets or trigger overlap')
            for note in coord['editorial_context']:
                require(left<=note['start_char']<note['end_char']<=right and row['source_text'][note['start_char']:note['end_char']]==note['source_text']
                    and note['author_stipulated_role']=='nonoperative_editorial_context'
                    and all(note['end_char']<=left+a or note['start_char']>=left+b for a,b in intervals),'document editorial role or interval differs')
            result.append({'id':f"{row['candidate_id']}-occurrence-{i}-"+boundary.text_sha(text)[:24],'source_text':text,
                'canonical_ir':{'rules':[rule]},'facet_spans':fields,'trigger_span':trigger,'domain':'new','trigger_supervised':True})
    return result



def validate_occurrence_coordinates(inputs,rows):
    unique={}
    for row in rows:
        key=row['source_text']
        if key in unique:
            require({k:v for k,v in row.items() if k!='id'}=={k:v for k,v in unique[key].items() if k!='id'},'equal occurrence text has inconsistent labels')
        else: unique[key]=row
    validate_fresh_coordinates(inputs,list(unique.values()))
    return {'occurrences':len(rows),'distinct_coordinate_validation_sources':len(unique)}


def audit_exposure(inputs,single_targets,document_targets,evidence):
    import re
    from scripts.ops.legal_ir import prepare_legal_facet_retention_corpus as corpus
    from scripts.ops.legal_ir import prepare_legal_grounding_curriculum as coordinates
    exposure,ledger=evidence['exposure_audit'],evidence['annotation_ledger']
    require(exposure['schema']=='authored-legal-facet-retention-exposure/v1' and ledger['schema']=='authored-legal-facet-retention-annotations/v1','exposure schema differs')
    panels={'train':inputs['new_train'],'tuning':inputs['tuning']['new'],'fresh':single_targets['fresh']}
    pairs={'train':inputs['training_pairs'],'tuning':inputs['tuning_pairs'],'fresh':evidence['challenge_pairs']}
    annotations={a['id']:a for a in ledger['single_rows']}
    require(len(annotations)==len(ledger['single_rows'])==1152 and set(annotations)=={r['id'] for rows in panels.values() for r in rows},'complete single annotation inventory required')
    normalize=lambda text:' '.join(re.findall(r'\w+|[^\w\s]',text.casefold()))
    seen_sources,seen_meanings,seen_cases=set(),set(),set();audits={};all_texts=[]
    for panel,rows in panels.items():
        audit=verify_pairs(rows,pairs[panel]);labels=[annotations[r['id']] for r in rows]
        verify_annotation_pairs(pairs[panel],labels);validate_fresh_coordinates(inputs,rows)
        for row in rows: verify_annotation(row,annotations[row['id']],panel)
        balance=Counter((r['canonical_ir']['rules'][0]['modality'],annotations[r['id']]['presence_mask']) for r in rows)
        require(balance=={(m,mask):len(rows)//24 for m in 'OPF' for mask in range(8)},'all modality/mask combinations must retain exact denominator')
        require(Counter(a['family'] for a in labels)=={f:len(rows)//8 for f in corpus.FAMILIES},'all eight family counts differ')
        texts={normalize(r['source_text']) for r in rows};meanings={digest(r['canonical_ir']) for r in rows};cases=set(audit['case_groups'])
        require(len(texts)==len(rows) and len(meanings)==len(cases)==len(rows)//2 and not(texts&seen_sources or meanings&seen_meanings or cases&seen_cases),'source/meaning/case crosses authored splits')
        seen_sources|=texts;seen_meanings|=meanings;seen_cases|=cases;all_texts.extend(r['source_text'] for r in rows)
        audits[panel]={'rows':len(rows),'meaning_groups':len(meanings),'families':dict(Counter(a['family'] for a in labels)),
            'templates':len({a['template_fingerprint'] for a in labels})}
    docpanels={'document_tuning':inputs['new_document_tuning'],'document_fresh':document_targets['fresh_documents']}
    da={a['candidate_id']:a for a in ledger['document_rows']}
    require(len(da)==len(ledger['document_rows'])==192 and set(da)=={r['candidate_id'] for rows in docpanels.values() for r in rows},'all document annotations required')
    docclauses={}
    for panel,rows in docpanels.items():
        require(Counter(r['supported'] for r in rows)=={True:72,False:24}
            and Counter(len(r['clauses']) for r in rows if r['supported'])=={1:24,2:24,3:24}
            and sum(r['repeated_rule_occurrences'] for r in rows)==12
            and Counter(r['unsupported_reason'] for r in rows if not r['supported'])=={g:8 for g in corpus.GUARDS},'document support/guard/occurrence denominator differs')
        require(all(da[r['candidate_id']]['panel']==panel for r in rows),'document panel annotation differs')
        dc=document_clauses(rows,ledger['document_rows']);docclauses[panel]=dc
        validate_occurrence_coordinates(inputs,dc)
        texts={normalize(r['source_text']) for r in [*rows,*dc]};meanings={digest(r['canonical_ir']) for r in dc};cases={da[r['candidate_id']]['case_group'] for r in rows}
        require(len(cases)==96 and not(texts&seen_sources or meanings&seen_meanings or cases&seen_cases),'document source/meaning/case crosses other panel')
        seen_sources|=texts;seen_meanings|=meanings;seen_cases|=cases;all_texts.extend(r['source_text'] for r in [*rows,*dc])
        audits[panel]={'rows':96,'supported':72,'guards':24,'occurrences':len(dc),'repeated_rule_documents':12}
    # Reuse reviewed manifest-ancestry discovery; independently read, join and mask every pool below.
    _,_,excluded,expected_refs,source_refs,real_count=corpus.historical_inputs(inputs['manifest']['inputs']['prior_corpus']['path'])
    artifacts=inputs['manifest']['artifacts']
    for name,key in (('new_facet_train','new_training'),('new_facet_tuning','new_tuning')):
        expected_refs[name]={'reference':artifacts[key],'representation':'annotated_single'}
    expected_refs['new_facet_document_tuning']={'reference':artifacts['document_tuning_targets'],'representation':'document_clauses'}
    require(exposure['known_pool_references']==expected_refs,'known-pool ancestry differs')
    pools={}
    for name,metadata in expected_refs.items():
        rows=read_ref(metadata['reference']);representation=metadata['representation']
        if representation=='document_clauses': rows=retained.document_audit_clauses(rows)
        elif representation=='earlier_single_targets':
            sources={r['id']:r for r in read_ref(metadata['source_reference'])['splits']['challenge']};converted=[]
            for row in rows['targets']:
                fields={}
                for field in ('actor','action','object','conditions','exceptions','temporal'):
                    value=row['source_spans'][field];fields[field]=(value[0] if value else None) if field in ('conditions','exceptions','temporal') else (value or None)
                converted.append({'id':row['id'],'source_text':sources[row['id']]['source_text'],'facet_spans':fields})
            rows=converted
        else: require(representation in ('annotated_single','grounding_single'),'unknown historical representation')
        if 'filter_domain' in metadata: rows=[r for r in rows if r['domain']==metadata['filter_domain']]
        pools[name]=rows
    layouts={name:{role_layout(r) for r in rows} for name,rows in pools.items()}
    require(exposure['known_pool_counts']=={k:len(v) for k,v in pools.items()} and exposure['known_role_masked_layouts']=={k:sorted(v) for k,v in layouts.items()},'independent layout or pool counts differ')
    layout_counts={}
    for kind,rows in (('single_rows',panels['fresh']),('document_clause_rows',docclauses['document_fresh'])):
        expected=[]
        for row in rows:
            layout=role_layout(row);matches=sorted(k for k,v in layouts.items() if layout in v)
            item={'id':row['id'],'source_sha256':boundary.text_sha(row['source_text']),'role_masked_layout':layout,
                'matching_pools':matches,'layout_status':'matched_local_layout' if matches else 'unmatched_local_combination',
                'matched_new_training':'new_facet_train' in matches}
            if kind=='single_rows': item.update({k:annotations[row['id']][k] for k in ('case_group','family','side')})
            expected.append(item)
        require(exposure[kind]==expected,'full fresh local-exposure row payload differs')
        layout_counts[kind]=dict(Counter(r['layout_status'] for r in expected))
    cue_evidence={cue:[a['id'] for a in ledger['single_rows'] if a['panel']=='train' and any(q['source_text'].strip().casefold()==cue for q in a['qualifier_cues'])]
        for cue in ('if','when','provided that','unless','except when','except where')}
    require(exposure['cue_training_rows']==cue_evidence and all(cue_evidence.values()),'qualifier cue exposure witnesses differ')
    known={normalize(text) for text in excluded}
    require(not known&seen_sources and exposure['new_overlap_count']==0 and exposure['prior_unique_normalized_sources']==len(known)
        and exposure['prior_inventory_sha256']==digest(sorted(boundary.text_sha(text) for text in known))
        and exposure['prior_source_inputs']==source_refs and exposure['real_exposed_views']==real_count==86,'historical source exclusion differs')
    split=exposure['split_audit']
    require(split==inputs['manifest']['split_audit'] and split['unique_normalized_sources_including_document_clauses']==len(seen_sources)
        and split['canonical_meanings_including_document_clauses']==len(seen_meanings) and split['case_groups']==len(seen_cases)
        and all(split[k]==0 for k in ('cross_split_source_overlap','cross_split_meaning_overlap','cross_split_case_overlap')),'independent authored split audit differs')
    return {'panels':audits,'known_unique_normalized_sources':len(known),'layout_counts':layout_counts,'source_overlap':0,'meaning_overlap':0,
        'authored_source_count':len(seen_sources),'independent_statutory_gold_count':0,'real_exposed_rows':86,
        'universal_layout_novelty_claimed':False,'scope':'Authored shared grammar with explicitly measured matched layouts and unmatched local combinations.'}
def verify_protocol(plan, inputs, frozen):
    require(plan['objectives'] == list(OBJECTIVES) and plan['architectures'] == list(ARCHITECTURES)
        and plan['seeds'] == list(SEEDS) and plan['additional_stage_steps'] == [400, 800]
        and plan['additional_updates_per_trial'] == 800 and plan['total_optimizer_updates'] == 9600
        and plan['optimizer'] == 'Adam' and plan['learning_rate'] == .001 and plan['optimizer_reset'] is True
        and plan['historical_optimizer_resumed'] is False and plan['batch_size'] == 12
        and plan['batch_quota'] == {'earlier': 3, 'historical_new': 3, 'new_pairs': 3, 'new_pair_rows': 6}
        and plan['training_diagnostic_count']==768 and plan['training_diagnostics_used_for_selection'] is False
        and plan['teacher_weight']==.5 and plan['overlap_weight']==.1 and plan['matched_objective_pair_batches'] is True
        and plan['consistency_weight'] == .25 and plan['fixed_sampler_and_same_architecture_parent_control'] is True
        and plan['inference_changed'] is plan['joint_search_enabled'] is False
        and plan['threads_per_worker'] == 1 and 1 <= plan['workers'] <= 3
        and plan['single_counts'] == SINGLE_COUNTS and plan['document_counts'] == DOCUMENT_COUNTS
        and plan['boundary_heads'] == inputs['boundary_heads'] and plan['retention_tolerance'] == 1
        and plan['unsupported_acceptance_tolerance'] == 0
        and plan['fresh_targets_opened'] is plan['regression_targets_opened'] is False,
        'predeclared matched facet retention protocol differs')
    read_ref(inputs['config']['study_design'], parse=False)
    for pipeline in frozen['pipelines']:
        require(pipeline['boundary_checkpoint'] == inputs['boundary_heads'][pipeline['boundary_head']]['checkpoint'],
                'pipeline changed frozen boundary checkpoint')



def target_references(config,manifest):
    roleconfig=read_ref(config['prior_role_experiment_config']);rolemanifest=read_ref(roleconfig['corpus_manifest'])
    singles,docs,_=prior.target_references(roleconfig,rolemanifest)
    singles['prior_role']=singles['fresh'];singles['fresh']=manifest['artifacts']['challenge_targets']
    docs['fresh_documents']=manifest['artifacts']['document_challenge_targets']
    evidence={key:manifest['artifacts'][key] for key in ('annotation_ledger','exposure_audit','challenge_pairs')}
    return singles,docs,evidence


def objective_sanity():
    import torch
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_facet_retention as runtime
    inherited=prior.objective_sanity();generator=torch.Generator().manual_seed(7613)
    errors=[]
    for size in range(1,5):
        for _ in range(3):
            logits=[torch.randn(size,generator=generator,dtype=torch.float64) for i in range(4)]
            left=runtime._valid_span_distribution(torch,*logits[:2]);right=runtime._valid_span_distribution(torch,*logits[2:])
            actual=float(runtime._pair_overlap_probability(left,right));expected=brute_force_overlap(left,right)
            require(abs(actual-expected)<1e-12 and 0<=actual<=1,'independent exhaustive valid-span overlap differs')
            require(bool((left.tril(-1)==0).all()) and bool((right.tril(-1)==0).all()),'invalid spans received probability')
            errors.append(abs(actual-expected))
    return {'inherited_role_js':inherited,'exhaustive_overlap_cases':len(errors),'maximum_overlap_error':max(errors),
        'teacher_masks_verified_from_actual_parent_logits_and_admitted_training_labels':True,
        'no_teacher_supervision_from_tuning_or_fresh_targets':True}

def real_diagnostics(inputs, frozen, singles, routing_summary_path):
    from scripts.ops.legal_ir import evaluate_legal_uscode_fidelity as evaluation
    from ipfs_datasets_py.logic.autoformal import legal_statutory_context as context
    route_summary_ref = ref(routing_summary_path); route_summary = read_ref(route_summary_ref)
    require(route_summary['schema'] == routing_audit.SCHEMA and route_summary['source_views'] == 86
        and route_summary['statutory_accuracy'] is None, 'frozen reference-free routing qualification required')
    decisions = read_ref(route_summary['real_routes'])
    manifest = read_ref(inputs['real_source_manifest'])
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
        'source_views': 86, 'distinct_source_texts': 83, 'model_source_slots': 1548,
        'routing_counts': dict(aggregate), 'real_reference_count': 0, 'reference_accuracy': None,
        'source_semantics_verified': False, 'training_or_selection_used_real_sources': False,
        'candidate_suppression_is_accuracy_improvement': False,
        'scope': 'Exposed and overlapping 2024 statutory views; raw predictions and routing outcomes both retained.'}

def run(args):
    import torch
    torch.set_num_threads(1)
    from scripts.ops.legal_ir import run_legal_facet_retention_experiment as runner
    from scripts.ops.legal_ir import prepare_legal_facet_retention_corpus as corpus
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_facet_retention as runtime
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consistency as parent_runtime
    from ipfs_datasets_py.logic.autoformal import legal_calendar_lake as gate
    require(type(args.workers) is int and 1 <= args.workers <= 3, 'one to three CPU replay workers required')
    folder, output = Path(args.run_directory).resolve(), Path(args.output).resolve()
    candidate_choice_ref=ref(args.candidate_choice);read_ref(candidate_choice_ref,parse=False)
    frozen_ref = ref(folder / 'generation-frozen.json'); frozen = read_ref(frozen_ref)
    require(frozen['schema'] == runner.SCHEMA and frozen['all_training_selection_and_generation_complete'] is True
        and frozen['fresh_targets_opened'] is frozen['regression_targets_opened'] is False
        and frozen['executed_optimizer_updates'] == 9600 and frozen['boundary_optimizer_updates'] == 0
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
    for module in (sys.modules[__name__], prior, runner, corpus, runtime, parent_runtime, consistency_audit, routing_audit,
        retained, retained.prior, retained.calendar, retained.calendar_summary, retained.compose,
        boundary_qualification, boundary_qualification.attribution, boundary_qualification.boundary_audit,
        clauses, boundary, previous, gate):
        pins[str(Path(module.__file__).resolve())] = sha(module.__file__)
    qualification_plan = write(output / 'qualification-plan.json', {'schema': SCHEMA, 'generation_freeze': frozen_ref,
        'producer_pins': pins, 'experimental_candidate_choice_before_reference_release':candidate_choice_ref, 'routing_summary': ref(args.routing_summary), 'target_references': single_target_refs,
        'document_target_references': document_target_refs, 'posthoc_evidence': evidence_refs,
        'native_build_single_panel': 'fresh', 'native_build_document_panel': 'fresh_documents',
        'fresh_single_build_slots': 18, 'fresh_document_build_slots': 36,
        'fresh_targets_opened': False, 'fresh_document_panel_is_new_holdout': True})
    require(runtime.next_batch_indices is parent_runtime.next_batch_indices, 'matched arms changed frozen sampler')
    fitting, sanity = verify_fitting(inputs), objective_sanity()
    selection = read_ref(frozen['selections'])
    jobs, training_audits = verify_training(inputs, frozen, selection)
    require(frozen['parent_fallbacks'] == [r['name'] for r in selection['trials'] if r['selection'] != 'candidate'],
            'parent fallback inventory differs')
    training_ref = write(output / 'training-and-selection-audit.json', {'schema': SCHEMA, 'selections': frozen['selections'],
        'fitting': fitting, 'objective_sanity': sanity, 'trials': training_audits,
        'executed_optimizer_updates': 9600, 'boundary_optimizer_updates': 0,
        'initial_numerical_predictions_equal_verified_against_replayed_parent': True,
        'teacher_historical_source_evaluations':18720, 'teacher_audit_counted_as_saved_prediction_replay':False,
        'teacher_exact_batch_recheck_events':sum(len(s['exact_batch_teacher_rechecks']) for t in training_audits for s in t['stages']),
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
    require(sum(len(j['sources']) for j in jobs if j.get('stage')) == 52560
        and sum(len(j['sources']) for j in jobs if not j.get('stage') and j['kind'] == 'single') == 30924
        and sum(len(j['sources']) for j in jobs if not j.get('stage') and j['kind'] == 'document') == 20736
        and sum(len(j['sources']) for j in jobs if j['kind'] == 'boundary') == 2304, 'complete replay denominators differ')
    replays = [];groups=group_replay_jobs(jobs)
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context('spawn')) as pool:
        for future in as_completed([pool.submit(replay_group,group) for group in groups]):
            replays.extend(future.result())
    require(len(replays)==len(jobs) and sum(r['rows'] for r in replays)==106524, 'full saved-panel replay denominator differs')
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
        'grouped_checkpoint_loads':len(groups),'prediction_memoization_used':False,
        'training_diagnostic_rows':sum(r['rows'] for r in replays if r['training_diagnostic']),
        'single_rows': sum(r['rows'] for r in replays if r['kind'] == 'single'),
        'document_rows': sum(r['rows'] for r in replays if r['kind'] == 'document'),
        'boundary_rows': sum(r['rows'] for r in replays if r['kind'] == 'boundary'),
        'stage_and_parent_tuning_rows': 52560, 'selected_single_rows': 30924, 'selected_document_rows': 20736,
        'fresh_and_regression_targets_opened': False, 'reference_derived_layout_evidence_opened': False, **FALSE})
    single_selections, document_selections = {}, {}
    for model in frozen['models']:
        name = model['name']; sources = inputs['sources']['fresh']; predictions = singles[name]['fresh']['rows']
        selected = retained.calendar.select_candidates(sources, predictions, toolchain=args.toolchain, policy=retained.calendar.POLICY)
        lookup = {s['id']: (s, p) for s, p in zip(sources, predictions)}
        for entry in selected['rows']:
            retained.calendar_summary.verify_entry(*lookup[entry['candidate']['candidate_id']], entry)
        require(selected['source_count'] == len(selected['rows']) + len(selected['excluded']) == 192, 'fresh build selection dropped sources')
        single_selections[name] = selected
    build_document_panel = 'fresh_documents'
    for pipeline in frozen['pipelines']:
        name = pipeline['name']
        document_selections[name] = retained.document_selection(documents[name][build_document_panel]['rows'],
            inputs['document_sources'][build_document_panel], toolchain=args.toolchain)
    build_selection_ref = write(output / 'build-selection-frozen.json', {'schema': SCHEMA,
        'single': single_selections, 'document': document_selections, 'replay': replay_ref,
        'single_source_slots': 3456, 'document_source_slots': 3456,
        'document_panel': build_document_panel, 'document_panel_is_exposed_regression': False,
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
    read_ref(candidate_choice_ref,parse=False)
    require(not guard.events, 'a sealed target read was attempted before reference release')
    guard.released = True
    print({'phase': 'references_released_after_build_freeze', 'builds': builds_ref}, flush=True)
    single_targets = {'tuning_' + panel: inputs['tuning'][panel] for panel in TUNING}
    for panel, pin in single_target_refs.items():
        single_targets[panel] = previous.reference_rows(read_ref(pin), inputs['sources'][panel])
    document_targets = {'document_tuning': inputs['document_tuning'], 'new_document_tuning': inputs['new_document_tuning']}
    for panel, pin in document_target_refs.items():
        document_targets[panel] = read_ref(pin)
        require(clauses.source_rows(document_targets[panel]) == inputs['document_sources'][panel], 'document source/reference binding differs')
    evidence = {key: read_ref(pin) for key, pin in evidence_refs.items()}
    exposure_ref = write(output / 'authored-exposure-audit.json', audit_exposure(inputs, single_targets, document_targets, evidence))
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
        'experimental_candidate_choice_before_reference_release':candidate_choice_ref,
        'reference_single': single_target_refs, 'reference_documents': document_target_refs, 'posthoc_evidence': evidence_refs,
        'models': model_reports, 'pipelines': pipeline_reports, 'single_totals': single_totals, 'document_totals': document_totals,
        'producer_pins': pins, 'parent_fallbacks': frozen['parent_fallbacks'], 'executed_optimizer_updates': 9600,
        'boundary_optimizer_updates': 0, 'inventory': inventory,
        'single_inference_rows_replayed': sum(r['rows'] for r in replays if r['kind'] == 'single'),
        'document_inference_rows_replayed': sum(r['rows'] for r in replays if r['kind'] == 'document'),
        'boundary_source_documents_replayed': sum(r['rows'] for r in replays if r['kind'] == 'boundary'),
        'clause_occurrences_replayed': sum(r.get('clause_occurrences_replayed', 0) for r in replays),
        'actual_lake_build_invocations': sum(b['backend_executed'] for selections in builds.values() for batches in selections.values() for b in batches),
        'build_attempts': sum(len(batches) for selections in builds.values() for batches in selections.values()),
        'native_single_build_slots': 18, 'native_fresh_document_build_slots': 36,
        'document_build_panel': build_document_panel, 'new_document_holdout_available': True,
        'fresh_target_and_regression_references_opened_after_replay_and_build_freezes': True,
        'reference_derived_novelty_evidence_opened_after_build_freeze': True,
        'test_results_used_for_selection_or_gate_revision': False, 'real_reference_accuracy_available': False,
        'scope': 'Matched loss-bundle training with identical executed800-update budgets, corpus, parents and minibatches. Selected fresh-arm contrasts include the frozen selection policy because selected steps or fallback can differ. Authored exactness, native compilation and unmeasured statutory fidelity remain separate.', **FALSE}
    write(output / 'summary.json', result)
    print({'complete': str(output / 'summary.json'), 'single_totals': single_totals, 'document_totals': document_totals}, flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-directory', required=True); parser.add_argument('--output', required=True)
    parser.add_argument('--routing-summary', required=True)
    parser.add_argument('--candidate-choice',required=True)
    parser.add_argument('--lake-executable', required=True); parser.add_argument('--toolchain', default='leanprover/lean4:v4.34.1')
    parser.add_argument('--workers', type=int, default=3)
    run(parser.parse_args())
