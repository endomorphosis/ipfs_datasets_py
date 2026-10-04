"""Closed role-retention gates, full denominators and source-only row contracts."""
from copy import deepcopy
from pathlib import Path
import runpy

import pytest

from scripts.ops.legal_ir import run_legal_timing_ownership_experiment as runner

LEGACY = runpy.run_path(str(Path(__file__).parents[2]/'logic/test_legal_condition_rehearsal_experiment.py'))


def clause_metric():
    return {'count':6, 'fullrule_exact':3, 'decoded':5, 'actor_exact':4,
        'modality_fullrule':{m:{'count':2, 'exact':1} for m in 'OPF'},
        'optional_facet':{f:{c:{'count':3, 'exact':2} for c in ('present','absent')} for f in runner.OPTIONAL}}


def document_metric():
    return {'count':8, 'supported':6, 'unsupported':2, 'joint_exact':3,
        'supported_ids':[f's{i}' for i in range(6)], 'unsupported_ids':['u0','u1'],
        'joint_exact_ids':['s0','s1','s2'], 'unsupported_accepted_ids':[]}


def metrics(steps=100):
    value = LEGACY['metrics'](steps)
    value.update(new_single_metrics=clause_metric(), prior_condition_metrics=clause_metric(),
        role_retention_metrics={p:clause_metric() for p in runner.ROLE_RETENTION_PANELS},
        role_oracle_metrics={p:clause_metric() for p in ('role_tuning','role_fresh')},
        old_atom_oracle_metrics={p:clause_metric() for p in ('atom_tuning','atom_fresh')},
        oracle_document_metrics={p:document_metric() for p in runner.DOC_PANELS},
        fixed_document_metrics={p:{b:document_metric() for b in runner.POLICIES} for p in runner.DOC_PANELS})
    return value


def single_gain(value):
    value['new_single_metrics']['fullrule_exact'] += 1
    value['new_single_metrics']['modality_fullrule']['O']['exact'] += 1
    return value


def stamp(value, parent):
    return value | runner.gates(value, parent)


def good_stage(parent, steps=100):
    return stamp(single_gain(metrics(steps)), parent)


def test_no_update_is_not_an_improvement_and_parent_fallback_is_available():
    parent = metrics(); stages = [stamp(metrics(s), parent) for s in runner.STAGES]
    assert all(s['failures'] == ['new:no_strict_single_or_oracle_document_improvement'] for s in stages)
    assert runner.select_stage(stages, parent) is None


@pytest.mark.parametrize('gain', ['single', 'oracle_document'])
def test_either_new_single_or_oracle_document_exact_gain_can_qualify(gain):
    parent = metrics(); stage = metrics()
    if gain == 'single': single_gain(stage)
    else:
        m = stage['oracle_document_metrics']['new']; m['joint_exact'] += 1; m['joint_exact_ids'].append('s3')
    result = stamp(stage, parent)
    assert result['eligible'] and result['failures'] == []
    assert runner.select_stage([result, stamp(metrics(200), parent)], parent) is result


@pytest.mark.parametrize('policy', runner.POLICIES)
def test_better_fixed_boundary_result_alone_cannot_meet_strict_gain(policy):
    parent = metrics(); stage = metrics()
    m = stage['fixed_document_metrics']['new'][policy]; m['joint_exact'] += 1; m['joint_exact_ids'].append('s3')
    assert 'new:no_strict_single_or_oracle_document_improvement' in runner.gates(stage, parent)['failures']


def get_clause(stage, panel):
    if panel in ('role_tuning','role_fresh'):return stage['role_oracle_metrics'][panel]
    if panel.startswith('retained_role_'):return stage['role_retention_metrics'][panel.removeprefix('retained_role_')]
    return stage[panel] if panel in ('new_single_metrics','prior_condition_metrics') else stage['old_atom_oracle_metrics'][panel]


@pytest.mark.parametrize('panel', ['new_single_metrics','prior_condition_metrics','atom_tuning','atom_fresh','role_tuning','role_fresh','retained_role_tuning','retained_role_fresh'])
@pytest.mark.parametrize('label', ['present','absent'])
def test_optional_presence_stratum_cannot_regress_while_its_total_is_unchanged(panel, label):
    parent = metrics(); stage = single_gain(metrics())
    # Use a valid facet total above whole-rule exactness, allowing an exchange between strata.
    current = get_clause(stage, panel); other = 'absent' if label == 'present' else 'present'
    current['optional_facet']['conditions'][label]['exact'] -= 1
    current['optional_facet']['conditions'][other]['exact'] += 1
    result = runner.gates(stage, parent)
    assert not result['eligible'] and any('conditions_'+label+'_regressed' in f for f in result['failures'])


@pytest.mark.parametrize('field', runner.OPTIONAL)
def test_each_qualifier_field_has_independent_retention(field):
    parent = metrics(); stage = single_gain(metrics())
    stage['old_atom_oracle_metrics']['atom_fresh']['optional_facet'][field]['present']['exact'] -= 1
    assert 'atom_fresh:oracle_clauses:'+field+'_present_regressed' in runner.gates(stage, parent)['failures']


@pytest.mark.parametrize('modality', list('OPF'))
def test_modality_fullrule_losses_cannot_hide_in_equal_aggregate(modality):
    parent = metrics(); stage = single_gain(metrics())
    current = stage['old_atom_oracle_metrics']['atom_fresh']; other = next(m for m in 'OPF' if m != modality)
    current['modality_fullrule'][modality]['exact'] -= 1
    current['modality_fullrule'][other]['exact'] += 1
    assert 'atom_fresh:oracle_clauses:modality_'+modality+'_regressed' in runner.gates(stage, parent)['failures']


def test_actor_regression_is_not_hidden_by_unchanged_fullrule_count():
    parent = metrics(); stage = single_gain(metrics())
    stage['old_atom_oracle_metrics']['atom_tuning']['actor_exact'] -= 1
    assert 'atom_tuning:oracle_clauses:actor_exact_regressed' in runner.gates(stage, parent)['failures']


@pytest.mark.parametrize('panel', runner.DOC_PANELS)
@pytest.mark.parametrize('policy', ('oracle', *runner.POLICIES))
def test_unsupported_identity_swaps_are_rejected_despite_equal_accept_count(panel, policy):
    parent = metrics(); stage = single_gain(metrics())
    def target(value):
        return value['oracle_document_metrics'][panel] if policy == 'oracle' else value['fixed_document_metrics'][panel][policy]
    target(parent)['unsupported_accepted_ids'] = ['u0']; target(stage)['unsupported_accepted_ids'] = ['u1']
    result = runner.gates(stage, parent)
    assert not result['eligible'] and any(f.startswith(panel+':') and f.endswith(':new_unsupported_sources_accepted') for f in result['failures'])
    target(stage)['unsupported_accepted_ids'] = []
    assert runner.gates(stage, parent)['eligible']


@pytest.mark.parametrize('policy', ('oracle', *runner.POLICIES))
def test_supported_document_joint_losses_fail_even_when_guard_accepts_fall(policy):
    parent = metrics(); stage = single_gain(metrics())
    key = 'oracle_document_metrics' if policy == 'oracle' else 'fixed_document_metrics'
    base = parent[key]['atom_fresh'] if policy == 'oracle' else parent[key]['atom_fresh'][policy]
    current = stage[key]['atom_fresh'] if policy == 'oracle' else stage[key]['atom_fresh'][policy]
    base['unsupported_accepted_ids'] = ['u0']; current['joint_exact'] -= 1; current['joint_exact_ids'].pop()
    assert any(f.endswith(':joint_exact_regressed') for f in runner.gates(stage, parent)['failures'])


def test_all_original_legacy_gates_remain_active():
    parent = metrics(); stage = single_gain(metrics())
    stage['tuning_condition_document_expanded_unsupported_accepted'] = 1
    assert 'legacy_condition_retention_failed' in runner.gates(stage, parent)['failures']
    stage = single_gain(metrics()); stage['tuning_earlier_exact'] = parent['tuning_earlier_exact']-2
    assert 'legacy_condition_retention_failed' in runner.gates(stage, parent)['failures']


def test_rank_order_prioritizes_new_single_then_oracle_then_fixed_policies():
    original = metrics(); variants = []
    for panel, policy in (('new', 'original'), ('new', 'distill'), ('new', 'oracle')):
        value = deepcopy(original)
        m = value['oracle_document_metrics'][panel] if policy == 'oracle' else value['fixed_document_metrics'][panel][policy]
        m['joint_exact'] += 1; m['joint_exact_ids'].append('s3'); variants.append(value)
    variants.append(single_gain(deepcopy(original)))
    assert all(runner.ranking(left) < runner.ranking(right) for left,right in zip(variants,variants[1:]))
    expected = (3,3,3,3,6,*runner.legacy.ranking(original)[:-1],-100)
    assert runner.ranking(original) == expected


def test_earlier_stage_wins_tie_training_accuracy_cannot_select_and_saved_gate_must_match():
    parent = metrics(); early = good_stage(parent, 100); late = good_stage(parent, 200)
    late['training_new_exact'] = 1000000; late['training_auxiliary_exact'] = 768
    assert runner.select_stage([early,late], parent) is early
    late['eligible'] = False
    with pytest.raises(ValueError, match='saved stage gate'): runner.select_stage([early,late], parent)
    with pytest.raises(ValueError, match='both complete'): runner.select_stage([early], parent)


@pytest.mark.parametrize('mutation', ['optional_total_above_decoded','optional_total_below_fullrule','missing_class',
    'modality_sum','bool_count','duplicate_guard','wrong_guard_class','changed_supported_ids','wrong_stratum_count'])
def test_malformed_gate_metrics_fail_closed(mutation):
    parent = metrics(); stage = single_gain(metrics())
    m = stage['prior_condition_metrics']; document = stage['fixed_document_metrics']['new']['distill']
    if mutation == 'optional_total_above_decoded':
        for cell in m['optional_facet']['conditions'].values(): cell['exact'] = 3
    elif mutation == 'optional_total_below_fullrule':
        for cell in m['optional_facet']['conditions'].values(): cell['exact'] = 1
    elif mutation == 'missing_class': del m['optional_facet']['exceptions']['absent']
    elif mutation == 'modality_sum': m['modality_fullrule']['O']['exact'] += 1
    elif mutation == 'bool_count': m['decoded'] = True
    elif mutation == 'duplicate_guard': document['unsupported_accepted_ids'] = ['u0','u0']
    elif mutation == 'wrong_guard_class': document['unsupported_accepted_ids'] = ['s0']
    elif mutation == 'changed_supported_ids': document['supported_ids'][-1] = 's9'
    else:
        m['optional_facet']['temporal']['present']['count'] += 1
        m['optional_facet']['temporal']['absent']['count'] -= 1
    with pytest.raises(ValueError): runner.gates(stage, parent)


def sources_and_targets():
    sources = [{'id':'opaque-a','source_text':'The office must file the report.'},
        {'id':'opaque-b','source_text':'The board may retain the record.'}]
    sources = runner.source_rows(sources)
    canonical = {'rules':[{'modality':'O','actor':'The office','action':'file','object':'the report',
        'conditions':[],'exceptions':[],'temporal':[]}]}
    targets = [{**s,'canonical_ir':deepcopy(canonical)} for s in sources]
    targets[1]['canonical_ir']['rules'][0].update(modality='P', actor='The board', action='retain', object='the record')
    return sources, targets


def test_generated_rows_do_not_need_ids_and_abstention_is_wrong_even_for_absent_facets():
    sources, targets = sources_and_targets()
    class Decoder:
        def decode_formal_logic(self, texts, *, trigger_ablation='none'):
            assert texts == [s['source_text'] for s in sources]
            return {'target_access':False,'teacher_forcing':False,'rows':[
                {'status':'decoded','canonical_ir':targets[0]['canonical_ir'],'source_sha256':sources[0]['source_sha256']},
                {'status':'abstained','canonical_ir':None,'source_sha256':sources[1]['source_sha256']}]}
    generation = runner.generate(Decoder(), sources)
    assert all('id' not in row and 'candidate_id' not in row for row in generation['rows'])
    metric = runner.clause_metrics(generation, sources, targets); runner.validate_clause_metric(metric)
    assert metric['count'] == 2 and metric['decoded'] == metric['fullrule_exact'] == metric['actor_exact'] == 1
    assert metric['modality_fullrule']['P'] == {'count':1,'exact':0}
    assert all(metric['optional_facet'][f]['absent'] == {'count':2,'exact':1} for f in runner.OPTIONAL)


@pytest.mark.parametrize('mutation', ['dropped_row','wrong_hash','swapped_rows','status_payload','duplicate_id'])
def test_generated_clause_source_binding_rejects_incomplete_or_misaligned_rows(mutation):
    sources, targets = sources_and_targets()
    generation = {'rows':[{'status':'decoded','canonical_ir':r['canonical_ir'],'source_sha256':s['source_sha256']}
        for s,r in zip(sources,targets,strict=True)]}
    if mutation == 'dropped_row': generation['rows'].pop()
    elif mutation == 'wrong_hash': generation['rows'][0]['source_sha256'] = '0'*64
    elif mutation == 'swapped_rows': generation['rows'].reverse()
    elif mutation == 'status_payload': generation['rows'][0]['status'] = 'abstained'
    else: sources[1]['id'] = sources[0]['id']
    with pytest.raises(ValueError): runner.clause_metrics(generation, sources, targets)


def test_document_metric_keeps_interval_and_occurrence_failures_even_with_correct_rules():
    _, targets = sources_and_targets(); rule = targets[0]['canonical_ir']['rules'][0]
    refs = [{'candidate_id':'support','source_sha256':'a'*64,'supported':True,
        'clauses':[{'char_start':0,'char_end':9,'rule':rule},{'char_start':10,'char_end':19,'rule':rule}]},
        {'candidate_id':'guard','source_sha256':'b'*64,'supported':False,'clauses':[]}]
    rows = [{'candidate_id':'support','source_sha256':'a'*64,'segmentation_status':'segmented',
        'composition':{'source_rule_list':[rule,rule],'source_plan':{'clauses':[{'char_start':0,'char_end':8},{'char_start':10,'char_end':19}]}}},
        {'candidate_id':'guard','source_sha256':'b'*64,'segmentation_status':'abstained','composition':None}]
    metric = runner.document_metrics({'rows':rows}, refs); runner.validate_document_metric(metric)
    assert metric['count'] == 2 and metric['joint_exact'] == 0 and metric['unsupported_accepted_ids'] == []
    rows[0]['composition']['source_plan']['clauses'][0]['char_end'] = 9
    assert runner.document_metrics({'rows':rows}, refs)['joint_exact_ids'] == ['support']
    rows[0]['composition']['source_rule_list'].pop()
    assert runner.document_metrics({'rows':rows}, refs)['joint_exact'] == 0


def test_actual_frozen_numeric_decoder_generation_rows_have_no_id_and_rename_invariant():
    import torch
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_facet_retention as facet
    helpers = runpy.run_path(str(Path(__file__).with_name('test_legal_span_temporal_presence.py')))
    before = torch.get_num_threads(); torch.set_num_threads(1)
    try:
        parent = helpers['parents'].__wrapped__()[False]
        decoder = facet.FacetRetentionDecoder(parent)
        sources, targets = sources_and_targets()
        generation = runner.generate(decoder, sources)
        assert all('id' not in row and 'candidate_id' not in row for row in generation['rows'])
        metric = runner.clause_metrics(generation, sources, targets); runner.validate_clause_metric(metric)
        renamed = [{**s,'id':'renamed-'+s['id']} for s in sources]
        assert runner.generate(decoder, renamed) == generation
    finally:
        torch.set_num_threads(before)


def oracle_toy():
    from scripts.ops.legal_ir import prepare_legal_role_span_rehearsal_corpus as corpus
    row, _ = corpus.render('train', 9001, 'caption_presence', 'O', 7, 0, 1)
    clause = row['source_text']; text = clause+' '+clause
    source = {'candidate_id':'toy-document','source_text':text,'source_sha256':runner.boundary.text_sha(text)}
    compose = runner.clauses.compose
    plan = compose.prepare_source_plan(source, [{'clause_id':'first-occurrence','char_start':0,'char_end':len(clause),
        'scope':deepcopy(compose.FLAT_SCOPE)}, {'clause_id':'second-occurrence','char_start':len(clause)+1,
        'char_end':len(text),'scope':deepcopy(compose.FLAT_SCOPE)}])
    planned = {'candidate_id':source['candidate_id'],'source_sha256':source['source_sha256'],
        'status':'planned','source_plan':plan,'supplied_boundary_policy':'author_supplied_supported_eligibility_and_exact_occurrence_intervals'}
    return row, source, planned


class AuthoredToyDecoder:
    """Unit fixture emulating source-only model output; receives no reference objects."""
    def __init__(self, row, abstain_second=False):
        self.row = row; self.calls = []; self.abstain_second = abstain_second

    def decode_formal_logic(self, texts):
        assert type(texts) is list and all(type(t) is str for t in texts)
        self.calls.append(texts)
        rows = []
        for index, text in enumerate(texts):
            assert text == self.row['source_text']
            if self.abstain_second and index == 1:
                rows.append({'status':'abstained','canonical_ir':None,'source_sha256':runner.boundary.text_sha(text),
                    'target_access':False,'teacher_forcing':False})
                continue
            facets = {}
            for field, interval in self.row['facet_spans'].items():
                facets[field] = ({'present':True,'char_start':interval[0],'char_end':interval[1],'text':text[slice(*interval)]}
                    if interval else {'present':False,'char_start':None,'char_end':None,'text':None})
            rows.append({'status':'decoded','canonical_ir':deepcopy(self.row['canonical_ir']),
                'source_sha256':runner.boundary.text_sha(text),'span_diagnostics':{'facets':facets},
                'target_access':False,'teacher_forcing':False})
        return {'rows':rows,'target_access':False,'teacher_forcing':False}


def test_oracle_composition_preserves_two_equal_text_occurrences_and_declares_assistance():
    row, source, plan = oracle_toy(); decoder = AuthoredToyDecoder(row)
    result = runner.generate_oracle_documents(decoder, [plan], [source])
    assert decoder.calls == [[row['source_text'], row['source_text']]]
    assert result['references_supplied'] is True and result['semantic_targets_supplied'] is False
    assert result['supplied_supported_eligibility'] is True and result['segmentation_learned'] is False
    actual = result['rows'][0]
    assert actual['segmentation_learned'] is False and actual['supplied_oracle_segmentation'] is True
    assert actual['status'] == 'composed' and actual['source_sha256'] == source['source_sha256']
    composition = actual['composition']
    assert composition['source_rule_list'] == [row['canonical_ir']['rules'][0]]*2
    assert [(c['char_start'],c['char_end']) for c in composition['source_plan']['clauses']] == [
        (0,len(row['source_text'])),(len(row['source_text'])+1,len(source['source_text']))]
    assert len(composition['occurrences']) == 2


def test_oracle_document_keeps_decoder_abstention_and_full_occurrence_denominator():
    row, source, plan = oracle_toy(); decoder = AuthoredToyDecoder(row, abstain_second=True)
    result = runner.generate_oracle_documents(decoder, [plan], [source])
    assert len(result['rows']) == 1
    actual = result['rows'][0]
    assert actual['status'] == 'abstained' and actual['composition'] is None
    assert len(actual['clause_generation']['rows']) == 2
    assert actual['reason'].startswith('complete_document_composition_rejected:')


@pytest.mark.parametrize('mutation', ['wrapper_hash','plan_source','missing_plan','unsupported','duplicate_identity'])
def test_oracle_source_and_complete_identity_provenance_checked_before_inference(mutation):
    row, source, plan = oracle_toy(); decoder = AuthoredToyDecoder(row)
    plans, sources = [plan], [source]
    if mutation == 'wrapper_hash': plan['source_sha256'] = '0'*64
    elif mutation == 'plan_source': plan['source_plan']['source']['source_text'] += 'changed'
    elif mutation == 'missing_plan': plans = []
    elif mutation == 'unsupported': plan['status'] = 'abstained'; plan['source_plan'] = None
    else:
        plans = [plan, deepcopy(plan)]
        sources = [source, {**source,'candidate_id':'other-document'}]
    with pytest.raises(ValueError): runner.generate_oracle_documents(decoder, plans, sources)
    assert decoder.calls == []


def alias_fixture():
    descriptor={k:'a'*64 for k in ('single_sources_sha256','document_sources_sha256',
      'oracle_document_sources_sha256','oracle_plans_sha256','fixed_boundaries_sha256','training_sources_sha256')}
    parent={'name':'parent_continuation-1730','objective':'parent','decoder_kind':'facet_retention','checkpoint':{'sha256':'1'*64}}
    fallback={**parent,'name':'common_continuation-1730','objective':'common'}
    stage={'name':'ownership_grounding-1730','objective':'ownership','decoder_kind':'timing_ownership','checkpoint':{'sha256':'2'*64}}
    final={**stage,'name':stage['name']+'_final200'}
    return [fallback,stage,parent,final],descriptor


def test_output_aliases_retain_logical_names_and_prefer_parent_or_final_training_slot():
    models,descriptor=alias_fixture();executions,aliases=runner.generation_groups(models,descriptor)
    assert len(executions)==2 and len(aliases)==4
    assert aliases['common_continuation-1730']['executed_model']=='parent_continuation-1730'
    assert aliases['ownership_grounding-1730']['executed_model']=='ownership_grounding-1730_final200'
    assert not aliases['ownership_grounding-1730']['training_logical_slot']
    assert all(e['include_training'] for e in executions)
    assert all(all(value[k]==v for k,v in descriptor.items()) for value in aliases.values())


@pytest.mark.parametrize('mutation',['checkpoint','kind','separate100'])
def test_aliases_do_not_merge_distinct_numeric_kind_or_checkpoint(mutation):
    models,descriptor=alias_fixture()
    if mutation=='checkpoint':models[0]['checkpoint']={'sha256':'3'*64}
    elif mutation=='kind':models[0]['decoder_kind']='temporal_presence'
    else:models[1]['checkpoint']={'sha256':'4'*64}
    groups,aliases=runner.generation_groups(models,descriptor)
    assert len(groups)==3 and len(aliases)==4


@pytest.mark.parametrize('mutation',['missing_plan','invalid_hash','duplicate_name'])
def test_alias_inventory_requires_every_provenance_dimension(mutation):
    models,descriptor=alias_fixture()
    if mutation=='missing_plan':del descriptor['oracle_plans_sha256']
    elif mutation=='invalid_hash':descriptor['single_sources_sha256']=False
    else:models.append(deepcopy(models[0]))
    with pytest.raises(ValueError):runner.generation_groups(models,descriptor)
