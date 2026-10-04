from copy import deepcopy
import json
import hashlib
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.ops.legal_ir import summarize_legal_facet_retention_experiment as q


def selection():
    parent = {'earlier': 50, 'temporal': 60, 'prior_consistency': 40,
              'document_parent': 20, 'document_expanded': 30, 'role':40, 'new':80, 'new_document_parent':20,'new_document_expanded':30}
    stages = [{'steps': step, **parent, 'guard_parent': 0, 'guard_expanded': 0,'new_guard_parent':0,'new_guard_expanded':0}
              for step in (400, 800)]
    return parent, stages


def test_selection_prefers_earliest_only_after_all_tuning_ranks_tie():
    parent, stages = selection()
    assert q.selection_choice(stages, parent)['steps'] == 400
    stages[1]['new'] += 1
    assert q.selection_choice(stages, parent)['steps'] == 800


@pytest.mark.parametrize('panel', ['earlier', 'temporal', 'prior_consistency', 'document_parent', 'document_expanded'])
def test_every_retention_gate_is_binding_even_when_new_tuning_improves(panel):
    parent, stages = selection()
    stages[1]['new'] += 10; stages[1][panel] = parent[panel] - 2
    assert q.selection_choice(stages, parent)['steps'] == 400
    stages[1][panel] += 1
    assert q.selection_choice(stages, parent)['steps'] == 800


@pytest.mark.parametrize('guard', list(q.GUARDS))
def test_guard_acceptance_disqualifies_without_hiding_parent_fallback(guard):
    parent, stages = selection()
    for stage in stages: stage[guard] = 1
    assert q.selection_choice(stages, parent) is None


def test_prior_consistency_retention_is_not_an_unregistered_tiebreaker():
    parent, stages = selection()
    stages[1]['prior_consistency'] += 5
    assert q.selection_choice(stages, parent)['steps'] == 400


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
              for name in ('earlier', 'prior_new', 'temporal', 'prior_consistency','prior_role')}
    pairs = [{'left_id': f'left-{i}', 'right_id': f'right-{i}'} for i in range(3)]
    inputs = {'replay': replay, 'training_pairs': pairs}
    before = {'progress': {'optimizer_steps': 0}, 'model_state': {'main': [0], 'actor_boundary.weight': [0]}}
    after = {'progress': {'optimizer_steps': 400}, 'model_state': {'main': [1], 'actor_boundary.weight': [0]},
             'training_config': {'objective': 'facet_retention', 'seed': 1729},
             'model_config': {'trigger_enabled': False, 'trigger_loss_weight': 0., 'actor_loss_weight': 0.},
             'consistency_parent_checkpoint_sha256': 'a' * 64, 'consistency_parent_optimizer_steps': 800}
    pools = {'earlier': [r['id'] for r in replay['earlier']],
             'historical_new': [r['id'] for name in ('prior_new', 'temporal', 'prior_consistency','prior_role') for r in replay[name]],
             'pairs': [[r['left_id'], r['right_id']] for r in pairs]}
    parts = {'semantic': 1., 'trigger': 0., 'actor': 0., 'semantic_earlier': 1., 'semantic_new': 1.,
             'actor_earlier': 0., 'actor_new': 0., 'js_modality': .1, 'js_presence': .1, 'js_endpoints': .1,
             'base_ce': 1., 'consistency_js': .1, 'weighted_consistency': .025, 'total': 1.1,'base_objective':1.025,'teacher_presence_kl':.1,'teacher_endpoint_kl':.1,
             'teacher_presence_terms':24.,'teacher_endpoint_terms':12.,'overlap_facet_pairs':36.,'teacher_kl':.1,'span_overlap':.25,
             'weighted_teacher':.05,'weighted_overlap':.025,'teacher_weight':.5,'overlap_weight':.1,
             'domain_rows': {'earlier': 3, 'new': 9}, 'supervised_trigger_rows': 9,
             'trigger_loss_rows': 0, 'pair_count': 3, 'consistency_weight': .25}
    report = {'optimizer_steps': 400, 'new_optimizer_steps_total': 400, 'training_executed': True,
              'stopped_reason': 'step_limit', 'tuning_used_for_fit': False, 'objective': 'facet_retention',
              'checkpoint_sha256': q.digest(after), 'consistency_parent_checkpoint_sha256': 'a' * 64,
              'consistency_parent_optimizer_steps': 800, 'batch_losses': [1.1] * 400,
              'batch_loss_components': [deepcopy(parts) for _ in range(400)],
              'batch_exposures': [q.expected_batch(1729, step, pools) for step in range(1, 401)],
              'domain_exposures': {'earlier': 1200, 'new': 3600}, 'pair_exposures': 1200,
              'elapsed_seconds': 1., 'gradient_norm_max': 1.,
              'auxiliary_gradient_norm_max': {'trigger_boundary': 0., 'trigger_modality': 0., 'actor_boundary': 0.},
              'changed_parameter_names': ['main'],'teacher_training_labels_only':True,'teacher_state_unchanged':True,'teacher_gradients_disabled':True}
    eligibility={row['id']:{'teacher_presence_terms':4,'teacher_endpoint_terms':2,'overlap_facet_pairs':3} for rows in replay.values() for row in rows}
    for pair in pairs:
        for key in ('left_id','right_id'): eligibility[pair[key]]={'overlap_facet_pairs':3}
    return report, before, after, inputs, eligibility


def test_complete400_update_receipt_checks_every_batch_and_loss_component():
    report, before, after, inputs, eligibility = report_fixture()
    result = q.verify_training_report(report, before, after, inputs, eligibility)
    assert result['optimizer_updates'] == 400
    assert result['independent_schedule_and_loss_accounting_verified'] is True
    assert result['optimizer_trajectory_replayed'] is False


@pytest.mark.parametrize('mutation', ['old_pool', 'pair_swap', 'missing_step', 'parent_hash', 'parent_steps',
                                    'js_total', 'js_bound', 'weight', 'nan_loss', 'aux_gradient',
                                    'changed_parameter', 'tuning_fit', 'ce_objective'])
def test_corrupted_training_receipt_rejected(mutation):
    report, before, after, inputs, eligibility = report_fixture()
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
    with pytest.raises(ValueError): q.verify_training_report(report, before, after, inputs, eligibility)


def inventory_fixture():
    models, pipelines, files, document_files = [], [], {}, {}
    heads = {'parent': {}, **{f'expanded-{seed}': {} for seed in q.SEEDS}}
    boundaries = {name: {panel: {} for panel in q.DOCUMENT_COUNTS} for name in heads}
    for objective in q.POLICIES:
        for architecture in q.ARCHITECTURES:
            for seed in q.SEEDS:
                name = f'{objective}_{architecture}-{seed}'
                item = {'name': name, 'objective': objective, 'architecture': architecture, 'seed': seed,
                    'enabled': architecture == 'grounding', 'decoder_kind': 'consistency' if objective == 'parent' else 'facet_retention',
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
    assert result == {'single_model_slots': 18, 'document_pipeline_slots': 36, 'fixed_boundary_heads': 4,
        'selected_single_rows': 30924, 'selected_pipeline_documents': 20736, 'fixed_boundary_documents': 2304}


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
from scripts.ops.legal_ir import summarize_legal_facet_retention_experiment as q
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
    inputs = {'real_source_manifest': manifest, 'sources': {'real_exposed': q.previous.source_rows(official)}}
    monkeypatch.setattr(evaluation, 'validate_manifest', lambda _: official)
    monkeypatch.setattr(context, 'inspect_prediction', lambda s, p: {'source_id': s['id'], 'source_semantics_verified': False})
    result = q.real_diagnostics(inputs, {'models': models, 'files': files}, singles, summary['path'])
    assert result['model_source_slots'] == 1548
    assert result['routing_counts']['slots'] == result['routing_counts']['decoder_abstained'] == 1548
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
    template = 'editorial index #. <actor> <modal> <action> <object>'
    label = {**deepcopy(row), 'panel': 'unit', 'source_sha256': hashlib.sha256(text.encode()).hexdigest(),
             'annotation_authority': 'authored_controlled_example_not_statutory_gold', 'template': template,
             'template_fingerprint': hashlib.sha256(template.encode()).hexdigest(), 'case_group': 'unit-case', 'presence_mask': 0, 'qualifier_cues':[],
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

@pytest.mark.parametrize('field',list(q.NEW_BOUNDS))
def test_new_retention_panels_have_zero_tolerance(field):
    parent,stages=selection()
    stages[1]['new']+=10;stages[1][field]=parent[field]-1
    assert q.selection_choice(stages,parent)['steps']==400
    stages[1][field]=parent[field]
    if field=='new': stages[1]['role']+=1
    assert q.selection_choice(stages,parent)['steps']==800


def test_rank_uses_equal_panel_accuracy_weight_and_excludes_train_score():
    parent,stages=selection();stages[0]['role']+=2;stages[1]['new']+=3
    assert q.selection_choice(stages,parent)['steps']==400
    stages[1]['new']+=2
    assert q.selection_choice(stages,parent)['steps']==800
    stages[1]['training_new_exact']=768
    with pytest.raises(ValueError):q.selection_choice(stages,parent)


@pytest.mark.parametrize('mutation',['teacher_count','new_pair_teacher','endpoint_count','overlap_count','unbounded_overlap','teacher_weight','overlap_weight','weighted_teacher','weighted_overlap','teacher_changed'])
def test_training_loss_mask_and_bundle_corruption_rejected(mutation):
    report,before,after,inputs,eligibility=report_fixture();parts=report['batch_loss_components'][12]
    if mutation=='teacher_count':parts['teacher_presence_terms']-=1
    if mutation=='new_pair_teacher':parts['teacher_presence_terms']+=24
    if mutation=='endpoint_count':parts['teacher_endpoint_terms']+=2
    if mutation=='overlap_count':parts['overlap_facet_pairs']-=1
    if mutation=='unbounded_overlap':parts['span_overlap']=1.1
    if mutation=='teacher_weight':parts['teacher_weight']=.4
    if mutation=='overlap_weight':parts['overlap_weight']=0
    if mutation=='weighted_teacher':parts['weighted_teacher']=0
    if mutation=='weighted_overlap':parts['weighted_overlap']=0
    if mutation=='teacher_changed':report['teacher_state_unchanged']=False
    with pytest.raises(ValueError):q.verify_training_report(report,before,after,inputs,eligibility)


def test_grouped_replay_loads_once_but_executes_each_saved_panel(monkeypatch):
    from scripts.ops.legal_ir import run_legal_facet_retention_experiment as runner
    checkpoint={'path':'fixture','sha256':'a'*64};model={'checkpoint':checkpoint,'decoder_kind':'consistency'}
    jobs=[{'kind':'single','name':str(i),'model':model,'sources':[{'id':str(i)}]} for i in range(4)]
    groups=q.group_replay_jobs(jobs);assert len(groups)==1
    loaded=[];executed=[];decoder=object()
    monkeypatch.setattr(runner,'load_decoder',lambda *args:(loaded.append(args) or decoder))
    monkeypatch.setattr(q,'read_ref',lambda *args,**kwargs:None)
    def replay(job,current):
        assert current is decoder;executed.append(job['name']);return {'name':job['name']}
    monkeypatch.setattr(q,'replay_with_decoder',replay)
    assert q.replay_group(groups[0])==[{'name':str(i)} for i in range(4)]
    assert len(loaded)==1 and executed==['0','1','2','3']
    changed=deepcopy(jobs[0]);changed['name']='other';changed['model']['decoder_kind']='facet_retention'
    assert len(q.group_replay_jobs(jobs+[changed]))==2
    with pytest.raises(ValueError):q.group_replay_jobs(jobs+[jobs[0]])


def teacher_fixture():
    import torch
    generator=torch.Generator().manual_seed(928)
    def output():
        return {'modality':torch.randn(12,3,generator=generator,requires_grad=True),
            'presence':torch.randn(12,4,2,generator=generator,requires_grad=True),
            'start':torch.randn(12,6,3,generator=generator,requires_grad=True),
            'end':torch.randn(12,6,3,generator=generator,requires_grad=True)}
    student,teacher=output(),output()
    records=[{'tokens':[0,1,2],'labels':{'presence':[True,True,False,True,False,False],
        'spans':[(0,0),(2,2),(-100,-100),(1,1),(-100,-100),(-100,-100)]}} for _ in range(12)]
    with torch.no_grad():
        teacher['presence'][:]=torch.tensor([[5.,-5.],[-5.,5.],[5.,-5.],[5.,-5.]])
        teacher['start'][:,3]=torch.tensor([-5.,5.,-5.]);teacher['end'][:,3]=torch.tensor([-5.,5.,-5.])
    return student,teacher,records


@pytest.mark.parametrize('error',['none','wrong_presence','wrong_span','span_tie','presence_tie','absent'])
def test_independent_teacher_enumeration_matches_mask_with_ties_and_wrong_decisions(error):
    import torch
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_facet_retention as runtime
    student,teacher,records=teacher_fixture()
    with torch.no_grad():
        if error=='wrong_presence':teacher['presence'][:,1]=torch.tensor([5.,-5.])
        if error=='wrong_span':teacher['start'][:,3]=torch.tensor([5.,-5.,-5.]);teacher['end'][:,3]=torch.tensor([5.,-5.,-5.])
        if error=='span_tie':teacher['start'][:,3]=0;teacher['end'][:,3]=0
        if error=='presence_tie':teacher['presence'][:,1]=0
        if error=='absent':
            for r in records:r['labels']['presence'][3]=False;r['labels']['spans'][3]=(-100,-100)
            teacher['presence'][:,1]=torch.tensor([5.,-5.])
    counts=q.teacher_eligibility(teacher,records);loss,parts=runtime._teacher_loss(torch,student,teacher,records)
    for key in ('teacher_presence_terms','teacher_endpoint_terms'):assert parts[key]==sum(c[key] for c in counts[:6])
    assert parts['teacher_endpoint_terms']==(12 if error=='none' else 0)
    loss.backward();assert all(v.grad is None for v in teacher.values())
    assert student['presence'].grad is not None


def test_new_pair_teacher_logits_never_enter_historical_mask():
    import torch
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_facet_retention as runtime
    student,teacher,records=teacher_fixture();a,counts=runtime._teacher_loss(torch,student,teacher,records)
    with torch.no_grad():
        for tensor in teacher.values():tensor[6:]=100
    b,updated=runtime._teacher_loss(torch,student,teacher,records)
    assert a==b and counts==updated


def test_bruteforce_overlap_and_reverse_span_exclusion():
    import torch
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_facet_retention as runtime
    for seed in range(4):
        torch.manual_seed(seed)
        for length in range(1,5):
            logits=[torch.randn(length,dtype=torch.float64,requires_grad=True) for _ in range(4)]
            a=runtime._valid_span_distribution(torch,*logits[:2]);b=runtime._valid_span_distribution(torch,*logits[2:])
            value=runtime._pair_overlap_probability(a,b)
            assert float(value)==pytest.approx(q.brute_force_overlap(a.detach(),b.detach()),abs=1e-12)
            value.backward();assert all(torch.isfinite(x.grad).all() for x in logits)
    start=torch.tensor([-100.,-100.,100.]);end=torch.tensor([100.,-100.,-100.])
    qspan=runtime._valid_span_distribution(torch,start,end)
    assert qspan[2,0]==0 and float(qspan.sum())==pytest.approx(1)
    assert float(runtime._pair_overlap_probability(qspan,qspan))>0


def test_gold_present_overlap_does_not_disappear_when_student_presence_is_absent():
    import torch
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_facet_retention as runtime
    student,_,records=teacher_fixture();a,counts=runtime._overlap_loss(torch,student,records)
    with torch.no_grad():student['presence'][:]=torch.tensor([100.,-100.])
    b,changed=runtime._overlap_loss(torch,student,records)
    assert a==b and counts==changed and counts['overlap_facet_pairs']==36


def test_training_annotations_and_duplicate_document_occurrences_validate_without_fresh_reads(monkeypatch):
    from scripts.ops.legal_ir import prepare_legal_facet_retention_corpus as corpus
    for family in corpus.FAMILIES:
        row,annotation=corpus.render('train',family,0,0,0)
        assert q.verify_annotation(row,annotation,'train')['template_fingerprint']==annotation['template_fingerprint']
    row,annotation=corpus.authored_document('document_tuning',24)
    occurrences=q.document_clauses([row],[annotation])
    assert len(occurrences)==2 and occurrences[0]['id']!=occurrences[1]['id']
    assert occurrences[0]['source_text']==occurrences[1]['source_text'] or occurrences[0]['source_text'][:-1]==occurrences[1]['source_text'][:-1]
    duplicate=deepcopy(occurrences[0]);duplicate['id']='second-occurrence'
    seen=[];monkeypatch.setattr(q,'validate_fresh_coordinates',lambda _,rows:seen.append(rows))
    assert q.validate_occurrence_coordinates({},[occurrences[0],duplicate])=={'occurrences':2,'distinct_coordinate_validation_sources':1}
    assert len(seen[0])==1
    duplicate['canonical_ir']['rules'][0]['modality']='F'
    with pytest.raises(ValueError):q.validate_occurrence_coordinates({},[occurrences[0],duplicate])
