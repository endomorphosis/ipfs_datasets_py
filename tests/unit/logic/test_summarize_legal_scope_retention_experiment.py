from copy import deepcopy
import math
from pathlib import Path
import subprocess
import sys

import pytest
from scripts.ops.legal_ir import summarize_legal_scope_retention_experiment as q


def clause_fixture():
    sources=[];targets=[];predictions=[]
    for i in range(4):
        text=f'The clerk{i} shall archive notice{i}.'
        source={'id':str(i),'source_text':text,'source_sha256':q.boundary.text_sha(text)}
        rule={'modality':'O','actor':f'The clerk{i}','action':'archive','object':f'notice{i}',
            'conditions':['permit is active'] if i<2 else [],'exceptions':[], 'temporal':['within 3 days'] if i%2 else []}
        target={'id':str(i),'source_text':text,'canonical_ir':{'rules':[rule]}}
        pred={'source_sha256':source['source_sha256'],'status':'decoded','canonical_ir':deepcopy(target['canonical_ir']),
            'target_access':False,'teacher_forcing':False}
        sources.append(source);targets.append(target);predictions.append(pred)
    return {'rows':predictions},sources,targets


def test_condition_presence_strata_keep_abstentions_and_do_not_conflate_full_rule_correctness():
    generation,sources,targets=clause_fixture()
    generation['rows'][0]['canonical_ir']['rules'][0]['modality']='P'
    generation['rows'][1].update(status='abstained',canonical_ir=None)
    generation['rows'][2]['canonical_ir']['rules'][0]['conditions']=['invented permit']
    result=q.clause_strata(generation,sources,targets)
    assert result['count']==4 and result['decoded']==3 and result['exact']==1 and result['modality_exact']==2
    assert result['Cpresent_count']==result['Cabsent_count']==2
    assert result['Cpresent_facet_exact']==1 and result['Cpresent_rule_exact']==0
    assert result['Cabsent_facet_exact']==result['Cabsent_rule_exact']==1


def test_all_reject_clause_model_has_zero_facet_and_rule_accuracy_in_both_classes():
    generation,sources,targets=clause_fixture()
    for row in generation['rows']:row.update(status='abstained',canonical_ir=None)
    result=q.clause_strata(generation,sources,targets)
    assert result['count']==4 and result['decoded']==result['exact']==result['modality_exact']==0
    assert all(result[p+'_'+s]==0 for p in ('Cpresent','Cabsent','Tpresent','Tabsent') for s in ('facet_exact','rule_exact'))


def scope_fixture(supported=False):
    text='The clerk shall archive the notice.';tokens=q.boundary.tokenize(text)
    source={'candidate_id':'scope-unit','source_text':text,'source_sha256':q.boundary.text_sha(text)}
    target={**source,'supported':supported,'construction':'unit','repeated_rule_occurrences':False,
        'clauses':[{'char_start':0,'char_end':len(text)}] if supported else []}
    pred={'candidate_id':source['candidate_id'],'source_sha256':source['source_sha256'],'status':'abstained',
        'reason':'declared_surface_policy_unsupported_scope','plan':None,'boundary_logits':[-1.]*len(tokens),
        'boundary_token_indices':[],'predicted_rule_count':0,'scope_logits':[0.,2.],
        'scope_supported_probability':1/(1+math.exp(-2)),'raw_learned_scope_supported':True,'target_access':False}
    return {'rows':[pred]},[source],[target]


def test_surface_guard_rejection_cannot_hide_raw_scope_false_acceptance():
    generation,sources,targets=scope_fixture();result=q.scope_metrics(generation,sources,targets)['metrics']
    assert result['count']==result['unsupported']==result['raw_unsupported_accepted']==1
    assert result['unsupported_accepted']==0


def test_raw_scope_ties_abstain_and_supported_false_rejections_remain_visible():
    generation,sources,targets=scope_fixture(True);row=generation['rows'][0]
    row.update(scope_logits=[0.,0.],raw_learned_scope_supported=False,scope_supported_probability=.5,reason='learned_scope_abstention')
    result=q.scope_metrics(generation,sources,targets)['metrics']
    assert result['supported']==1 and result['raw_supported_correct']==result['supported_exact']==0


@pytest.mark.parametrize('mutation',['argmax','tie','probability','nan','boolean'])
def test_raw_scope_logit_policy_corruption_rejected(mutation):
    generation,_,_=scope_fixture();row=generation['rows'][0]
    if mutation=='argmax':row['raw_learned_scope_supported']=False
    if mutation=='tie':row['scope_logits']=[0.,0.]
    if mutation=='probability':row['scope_supported_probability']=.2
    if mutation=='nan':row['scope_logits'][0]=float('nan')
    if mutation=='boolean':row['raw_learned_scope_supported']=1
    with pytest.raises(ValueError):q.verify_scope_logits(generation)


def boundary_state():
    parent={key:None for key in ('schema','profile','implementation_sha256','config','optimizer_resumption_supported')}
    parent['model_state']={'scope.weight':[[0.]*64 for _ in range(2)],'scope.bias':[0.,0.],
        'embedding.weight':[[.1]],'encoder.weight':[.2],'boundary.weight':[.3]}
    child=deepcopy(parent);child['model_state']['scope.bias'][0]=.1
    return parent,child


def test_scope_state_change_is_limited_to130_parameters():
    assert q.verify_frozen_boundary_tensors(*boundary_state())=={'trainable_parameters':130,
        'changed_scope_tensors':['scope.bias'],'non_scope_tensors_bit_identical':True}


@pytest.mark.parametrize('mutation',['embedding.weight','encoder.weight','boundary.weight','shape','nan','extra','no_update'])
def test_scope_only_receipt_rejects_hidden_encoder_or_boundary_changes(mutation):
    parent,child=boundary_state()
    if mutation in ('embedding.weight','encoder.weight','boundary.weight'):child['model_state'][mutation]=[9.]
    if mutation=='shape':child['model_state']['scope.weight'][0].pop()
    if mutation=='nan':child['model_state']['scope.bias'][0]=float('nan')
    if mutation=='extra':child['model_state']['new.head']=[0.]
    if mutation=='no_update':child=deepcopy(parent)
    with pytest.raises(ValueError):q.verify_frozen_boundary_tensors(parent,child)


def test_scope_change_never_changes_raw_token_boundaries():
    parent,_,_=scope_fixture();child=deepcopy(parent)
    child['rows'][0]['scope_logits']=[2.,0.]
    assert q.verify_frozen_token_outputs(parent,child)==1
    child['rows'][0]['boundary_logits'][0]+=.001
    with pytest.raises(ValueError):q.verify_frozen_token_outputs(parent,child)


def auxiliary_fixture():
    import torch
    torch.manual_seed(834)
    output={'presence':torch.randn(4,4,2,dtype=torch.float64,requires_grad=True),
        'start':torch.randn(4,6,5,dtype=torch.float64,requires_grad=True),
        'end':torch.randn(4,6,5,dtype=torch.float64,requires_grad=True),
        'modality':torch.randn(4,3,dtype=torch.float64,requires_grad=True)}
    records=[{'tokens':['t']*5,'labels':{'presence':[True,True,True,i<2,False,False],
        'spans':[(0,0),(0,0),(0,0),(1,3) if i<2 else(-1,-1),(-1,-1),(-1,-1)]}} for i in range(4)]
    return output,records


def test_condition_loss_oracle_matches_runtime_and_only_updates_declared_heads():
    import torch
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_scope_retention as runtime
    output,records=auxiliary_fixture();actual,parts=runtime._condition_rehearsal_loss(torch,output,records)
    expected,wanted=q.condition_auxiliary_oracle(torch,output,records)
    assert float(actual)==pytest.approx(float(expected),abs=1e-12)
    for key,value in wanted.items():assert float(parts[key])==pytest.approx(float(value),abs=1e-12)
    gradients=torch.autograd.grad(actual,list(output.values()),retain_graph=True,allow_unused=True)
    oracle_gradients=torch.autograd.grad(expected,list(output.values()),allow_unused=True)
    for a,b in zip(gradients,oracle_gradients):
        assert (a is None and b is None) or (a is not None and b is not None and torch.allclose(a,b,rtol=1e-12,atol=1e-12))
    assert not torch.count_nonzero(gradients[0][:,[0,2,3]])
    for gradient in gradients[1:3]:
        assert not torch.count_nonzero(gradient[2:]) and not torch.count_nonzero(gradient[:,[0,1,2,4,5]])
    assert gradients[3] is None or not torch.count_nonzero(gradients[3])


def test_balanced_rehearsal_sampler_matches_runtime_over_all200_updates_and_wraps():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_scope_retention as runtime
    pools={'earlier':[f'e{i}' for i in range(7)],'historical_new':[f'h{i}' for i in range(11)],
        'positive_pairs':[[f'p{i}a',f'p{i}b'] for i in range(4)],'negative_pairs':[[f'n{i}a',f'n{i}b'] for i in range(4)]}
    hard={label:[label+str(i) for i in range(64)] for label in ('positive','negative')}
    counts={key:len(value) for key,value in pools.items()};progress=runtime._progress(counts,1730)
    for step in range(1,201):
        actual,progress=runtime.next_batch_indices(progress,counts,1730);expected=q.expected_clause_batch(1730,step,pools,hard)
        assert actual==expected['indices_by_pool'] and progress==runtime._progress(counts,1730,step)
        assert len(expected['ids'])==12 and len(expected['rehearsal_ids'])==4
        assert all(identity.startswith('positive') for identity in expected['rehearsal_ids'][:2])
        assert all(identity.startswith('negative') for identity in expected['rehearsal_ids'][2:])


def mining_fixture():
    parent={'fake_weights':True};rows=[];scores=[]
    for i in range(160):
        text=f'source{i}';present=i<80
        row={'id':str(i),'source_text':text,'canonical_ir':{'rules':[{'conditions':['permit'] if present else []}]}}
        rows.append(row);scores.append({'id':row['id'],'source_sha256':q.boundary.text_sha(text),'condition_present':present,
            'condition_presence_ce':float(i%80),'condition_endpoint_ce':1. if present else 0.,'condition_loss_sum':float(i%80)+(1. if present else 0.)})
    selected={label:[s['id'] for s in sorted((s for s in scores if s['condition_present'] is present),key=lambda s:(-s['condition_loss_sum'],s['id']))[:64]]
        for present,label in ((True,'positive'),(False,'negative'))}
    mining={'schema':'training-only-condition-hard-mining/v1','parent_kind':'facet_retention','parent_checkpoint_sha256':q.digest(parent),
        'training_manifest_sha256':q.digest(rows),'mining_batch_size':48,'score_rows':deepcopy(scores),'selected_ids':selected,
        'selected_count_per_class':64,'ranking':'descending_presence_plus_present_mean_endpoint_CE_then_ascending_id/v1',
        'training_labels_only':True,'tuning_or_test_used':False,'model_state_unchanged':True}
    return parent,'facet_retention',rows,mining,scores


def test_mining_reproduces_all_gold_scores_and_deterministic64_per_class():
    assert q.verify_mining_manifest(*mining_fixture()) is True


@pytest.mark.parametrize('mutation',['score','rank','class','source','parent','labels','missing','absent_endpoint','batch'])
def test_mining_corruptions_and_tuning_label_use_rejected(mutation):
    args=mining_fixture();parent,kind,rows,mining,scores=args
    if mutation=='score':mining['score_rows'][0]['condition_presence_ce']+=1
    if mutation=='rank':mining['selected_ids']['positive'].reverse()
    if mutation=='class':mining['score_rows'][0]['condition_present']=False
    if mutation=='source':mining['score_rows'][0]['source_sha256']='0'*64
    if mutation=='parent':mining['parent_checkpoint_sha256']='0'*64
    if mutation=='labels':mining['tuning_or_test_used']=True
    if mutation=='missing':mining['score_rows'].pop()
    if mutation=='absent_endpoint':mining['score_rows'][-1]['condition_endpoint_ce']=1.
    if mutation=='batch':mining['mining_batch_size']=16
    with pytest.raises(ValueError):q.verify_mining_manifest(*args)


def scope_selection_fixture():
    metric={'count':96,'supported':48,'unsupported':48,'raw_supported_correct':44,'raw_unsupported_accepted':1,
        'supported_exact':30,'unsupported_accepted':1,'raw_boundary_exact':35}
    parent={'old':deepcopy(metric),'scope_new':deepcopy(metric)}
    stages=[]
    for step in q.SCOPE_STAGES:
        panels=deepcopy(parent)
        for value in panels.values():value['raw_unsupported_accepted']=value['unsupported_accepted']=0
        stages.append({'steps':step,'metrics':panels,'raw_token_logits_unchanged':True})
    return parent,stages


def test_scope_selection_earliest_then_new_supported_then_historical_segmentation():
    parent,stages=scope_selection_fixture();assert q.scope_choice(stages,parent)['steps']==100
    stages[2]['metrics']['scope_new']['raw_supported_correct']+=1;assert q.scope_choice(stages,parent)['steps']==400
    stages[1]['metrics']['scope_new']['raw_supported_correct']+=1
    stages[1]['metrics']['old']['supported_exact']+=1;assert q.scope_choice(stages,parent)['steps']==200


@pytest.mark.parametrize('change',['raw_guard','final_guard','all_reject','segmentation_loss','token_change'])
def test_scope_guard_failure_and_positive_rejection_cannot_create_fake_improvement(change):
    parent,stages=scope_selection_fixture()
    for stage in stages:
        row=stage['metrics']['old']
        if change=='raw_guard':row['raw_unsupported_accepted']=1
        if change=='final_guard':row['unsupported_accepted']=1
        if change=='all_reject':row['raw_supported_correct']=row['supported_exact']=0
        if change=='segmentation_loss':row['supported_exact']-=1
        if change=='token_change':stage['raw_token_logits_unchanged']=False
    assert q.scope_choice(stages,parent) is None
    assert parent['old']['raw_unsupported_accepted']==1  # Fallback does not mean passing the new scope gate.


@pytest.mark.parametrize('change',['missing_panel','missing_stage','count','boolean','fresh_selection'])
def test_scope_selection_closed_admitted_only_metric_contract(change):
    parent,stages=scope_selection_fixture()
    if change=='missing_panel':stages[0]['metrics'].pop('old')
    if change=='missing_stage':stages.pop()
    if change=='count':stages[0]['metrics']['old']['count']+=1
    if change=='boolean':stages[0]['metrics']['old']['raw_unsupported_accepted']=False
    if change=='fresh_selection':stages[0]['fresh_accuracy']=1.
    with pytest.raises(ValueError):q.scope_choice(stages,parent)


def scope_pair_fixture():
    from scripts.ops.legal_ir import prepare_legal_scope_retention_corpus as corpus
    rows,pair,_=corpus.make_pair('train',7)
    return rows,[pair]


def test_independent_scope_pair_keeps_repeated_body_and_opposite_labels():
    rows,pairs=scope_pair_fixture()
    assert rows[0]['repeated_rule_occurrences'] is True and len(pairs[0]['local_clause_body_sha256'])==3
    assert q.verify_scope_pairs(rows,pairs,1)['same_local_bodies_with_different_scope_labels'] is True


@pytest.mark.parametrize('change',['body','third_body','duplicate_occurrence','hash','same_labels','nested_flat_target','source_hash','missing'])
def test_scope_pair_meaning_or_attachment_mutations_rejected_after_repaired_source_hash(change):
    rows,pairs=scope_pair_fixture();left,right=rows
    if change=='body':right['source_text']=right['source_text'].replace('unless','when').replace('except when','when').replace('except where','when')
    if change=='third_body':right['source_text']=right['source_text'][:-2]+'.'
    if change=='duplicate_occurrence':left['clauses'].pop()
    if change=='hash':pairs[0]['local_clause_body_sha256'][0]='0'*64
    if change=='same_labels':right['supported']=True
    if change=='nested_flat_target':right['clauses']=deepcopy(left['clauses'])
    if change=='source_hash':right['source_sha256']='0'*64
    else:right['source_sha256']=q.boundary.text_sha(right['source_text'])
    if change=='missing':rows.pop()
    with pytest.raises(ValueError):q.verify_scope_pairs(rows,pairs,1)


def test_independent_scope_schedule_matches_both400_update_arms_and_common_stream():
    from scripts.ops.legal_ir import prepare_legal_scope_retention_corpus as corpus
    from scripts.ops.legal_ir import run_legal_scope_retention_experiment as runner
    pairs=[corpus.make_pair('train',i) for i in range(96)]
    rows=[row for batch,_,_ in pairs for row in batch];metadata=[pair for _,pair,_ in pairs]
    replay=[deepcopy(row) for row in rows[:14]]
    for i,row in enumerate(replay):row['candidate_id']='old-'+str(i)
    schedules={}
    for arm in ('control','target'):
        actual=[receipt for _,receipt in runner.batch_schedule(replay,rows,metadata,arm)]
        schedules[arm]=q.expected_scope_batches(replay,rows,metadata,arm)
        assert actual==schedules[arm] and len(actual)==400
    assert [r['common_replay_ids'] for r in schedules['control']]==[r['common_replay_ids'] for r in schedules['target']]
    assert all(len(row['extra_ids'])==6 and len(row['pair_ids'])==3 for row in schedules['target'])


def clause_selection_fixture():
    def nested(n):
        return {'count':n,'fullrule_exact':n//2,'modality_fullrule':{m:{'count':n//3,'exact':n//6} for m in 'OPF'},
            **{k:{p:{'count':n//2,'exact':n//4} for p in ('present','absent')} for k in ('condition_facet','temporal_facet','condition_fullrule','temporal_fullrule')}}
    bounds={**q.prior.OLD_BOUNDS,**q.prior.NEW_BOUNDS}
    parent={k:n//2 for k,n in bounds.items()};parent.update({k:0 for k in q.prior.GUARDS})
    parent.update(condition=48,condition_metrics=nested(96),retention_metrics={p:nested(192) for p in ('facet','temporal')})
    for prefix in ('condition_','retention_facet_','retention_temporal_'):
        for policy in ('parent','expanded'):
            parent[prefix+'document_'+policy]=36;parent[prefix+'guard_'+policy]=int(prefix=='retention_temporal_' and policy=='expanded')
    return parent,[{'steps':s,**deepcopy(parent)} for s in (100,200)]


def test_closed_clause_gates_preserve_known_exposed_guard_count_without_qualifying_new_guard_accepts():
    parent,stages=clause_selection_fixture();assert q.clause_choice(stages,parent)['steps']==100
    stages[0]['retention_temporal_guard_expanded']=2;assert q.clause_choice(stages,parent)['steps']==200
    stages[1]['condition_guard_expanded']=1;assert q.clause_choice(stages,parent) is None


@pytest.mark.parametrize('panel,kind,label',[('facet',k,p) for k,p in [('condition_facet','present'),('condition_facet','absent'),('temporal_facet','present'),('temporal_facet','absent'),('modality_fullrule','O')]]+ [('temporal','condition_facet','present')])
def test_facet_and_modality_regression_cannot_hide_behind_total_fullrule_gain(panel,kind,label):
    parent,stages=clause_selection_fixture()
    for stage in stages:
        stage['retention_metrics'][panel][kind][label]['exact']-=1
        if kind=='modality_fullrule':
            stage['retention_metrics'][panel]['modality_fullrule']['P']['exact']+=1
    assert q.clause_choice(stages,parent) is None


@pytest.mark.parametrize('kind',['condition_fullrule','temporal_fullrule'])
def test_new_condition_classes_gate_fullrules_and_keep_class_counts(kind):
    parent,stages=clause_selection_fixture()
    for s in stages:
        s['condition_metrics'][kind]['present']['exact']-=1;s['condition_metrics'][kind]['absent']['exact']+=1
    assert q.clause_choice(stages,parent) is None


def test_train_or_fresh_metric_cannot_enter_closed_clause_selection():
    parent,stages=clause_selection_fixture();stages[0]['fresh_exact']=192
    with pytest.raises(ValueError):q.clause_choice(stages,parent)


def test_actual_spawn_worker_guard_denies_sealed_file_access(tmp_path):
    sealed=tmp_path/'sealed.json';sealed.write_text('{}')
    code="from scripts.ops.legal_ir import summarize_legal_scope_retention_experiment as q\nfrom pathlib import Path\nq.init_replay_worker([{'path':"+repr(str(sealed))+"}])\ntry: Path("+repr(str(sealed))+").read_bytes()\nexcept ValueError: pass\nelse: raise AssertionError('read succeeded')\nassert len(q._WORKER_GUARD.events)==1 and not q._WORKER_GUARD.events[0]['after_build_freeze']\n"
    result=subprocess.run([sys.executable,'-c',code],cwd=Path(q.ROOT),capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_parent_guard_allows_reference_reads_only_after_explicit_build_phase_release(tmp_path):
    sealed=tmp_path/'sealed.json';sealed.write_text('{}');guard=q.SealedReadGuard([{'path':str(sealed)}])
    with pytest.raises(ValueError):guard.event('open',(str(sealed),'r',0))
    guard.released=True;guard.event('open',(str(sealed),'r',0))
    assert [r['after_build_freeze'] for r in guard.events]==[False,True]


def training_report_fixture(start=0,finish=100,objective='condition_rehearsal'):
    import importlib.util
    path=Path(__file__).with_name('test_summarize_legal_temporal_presence_experiment.py')
    spec=importlib.util.spec_from_file_location('temporal_qualifier_test_fixture',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    report,before,after,inputs,eligibility=module.report_fixture(start,finish,'base')
    hard={'positive':[f'hard-positive-{i}' for i in range(64)],'negative':[f'hard-negative-{i}' for i in range(64)]}
    after['training_config']['objective']=objective
    after.update(frozen_parent_checkpoint_sha256=after.pop('facet_parent_checkpoint_sha256'),frozen_parent_optimizer_steps=after.pop('facet_parent_optimizer_steps'),frozen_parent_kind='facet_retention',hard_mining={'selected_ids':hard},hard_mining_sha256='c'*64)
    report.update(objective=objective,frozen_parent_checkpoint_sha256=report.pop('facet_parent_checkpoint_sha256'),frozen_parent_optimizer_steps=report.pop('facet_parent_optimizer_steps'),frozen_parent_kind='facet_retention',hard_mining_sha256='c'*64,rehearsal_exposures={'positive':2*(finish-start),'negative':2*(finish-start)})
    weight=.5 if objective=='condition_rehearsal' else 0.
    for parts in report['batch_loss_components']:
        for key in list(parts):
            if key.startswith('temporal_') or key=='weighted_temporal_presence':parts.pop(key)
        parts.update(condition_positive_ce=.3,condition_negative_ce=.5,condition_balanced_presence_ce=.4,condition_present_endpoint_ce=.2,condition_rehearsal_ce=.3,condition_weight=weight,weighted_condition_rehearsal=weight*.3,condition_positive_rows=2,condition_negative_rows=2,rehearsal_rows=4,total=1.1+weight*.3)
    report['batch_losses']=[p['total'] for p in report['batch_loss_components']]
    report['batch_exposures']=[q.expected_clause_batch(1730,step,q.prior.training_pools(inputs),hard) for step in range(start+1,finish+1)]
    report['checkpoint_sha256']=q.digest(after)
    return report,before,after,inputs,eligibility


@pytest.mark.parametrize('start,finish',[(0,100),(100,200)])
@pytest.mark.parametrize('objective',['base','condition_rehearsal'])
def test_complete_condition_reports_both_matched_objectives(start,finish,objective):
    assert q.verify_training_report(*training_report_fixture(start,finish,objective))['optimizer_updates']==100


@pytest.mark.parametrize('mutation',['hard_hash','parent_kind','aux_ids','aux_count','aux_mean','aux_endpoints','aux_weight','aux_total','teacher_count','scope_fit','main_order','nonfinite'])
def test_rehearsal_report_corruption_rejected(mutation):
    report,before,after,inputs,eligibility=training_report_fixture();parts=report['batch_loss_components'][7]
    if mutation=='hard_hash':report['hard_mining_sha256']='d'*64
    if mutation=='parent_kind':report['frozen_parent_kind']='temporal_presence'
    if mutation=='aux_ids':report['batch_exposures'][7]['rehearsal_ids'].reverse()
    if mutation=='aux_count':parts['condition_positive_rows']=1
    if mutation=='aux_mean':parts['condition_balanced_presence_ce']=.5
    if mutation=='aux_endpoints':parts['condition_present_endpoint_ce']=.4
    if mutation=='aux_weight':parts['condition_weight']=0.
    if mutation=='aux_total':parts['total']+=.1
    if mutation=='teacher_count':parts['teacher_endpoint_terms']+=1
    if mutation=='scope_fit':report['tuning_used_for_fit']=True
    if mutation=='main_order':report['batch_exposures'][7]['ids'].reverse()
    if mutation=='nonfinite':parts['condition_positive_ce']=float('nan')
    with pytest.raises(ValueError):q.verify_training_report(report,before,after,inputs,eligibility)


def test_condition_specific_admitted_annotations_do_not_require_obsolete_template_fields():
    from scripts.ops.legal_ir import prepare_legal_condition_rehearsal_corpus as corpus
    rows,annotations,_=corpus.make_panel('tuning')
    for row,a in zip(rows,annotations,strict=True):
        q.verify_annotation(row,a,'tuning');q.verify_condition_annotation(row,a)
    assert len(rows)==96
    assert {a['family'] for a in annotations}==set(corpus.FAMILIES[:2])


@pytest.mark.parametrize('mutation',['mask','literal','layout','authority','cue','placement','temporal_role'])
def test_condition_annotations_reject_meaning_or_provenance_corruption(mutation):
    from scripts.ops.legal_ir import prepare_legal_condition_rehearsal_corpus as corpus
    row,a=corpus.render('tuning',0,0,5,0)
    if mutation=='mask':a['presence_mask']=0
    if mutation=='literal':row['canonical_ir']['rules'][0]['conditions']=['wrong condition']
    if mutation=='layout':a['role_masked_layout']='different layout'
    if mutation=='authority':a['annotation_authority']='statutory_gold'
    if mutation=='cue':a['condition_cue']='unless'
    if mutation=='placement':a['condition_placement']='absent'
    if mutation=='temporal_role':a['temporal_scope']='opaque_timing_applicability_atom'
    with pytest.raises(ValueError):q.verify_annotation(row,a,'tuning');q.verify_condition_annotation(row,a)


def test_primary_boundary_choice_uses_actual_frozen_raw_metric_names(monkeypatch):
    parent,stages=clause_selection_fixture();trial={'name':'base_grounding-1730','architecture':'grounding','selection':'candidate','selected_steps':100,'stages':[{'additional_steps_after':100,'tuning':{k:v for k,v in stages[0].items() if k!='steps'}}]}
    models=[{'name':'parent_continuation-1730','architecture':'continuation','checkpoint':'c','decoder_kind':'facet_retention','selected_steps':0,'selection':'unchanged_parent'},
        {'name':'base_grounding-1730','architecture':'grounding','checkpoint':'g','decoder_kind':'scope_retention','selected_steps':100,'selection':'candidate'}]
    head={'name':'target','arm':'target','checkpoint':'b','selected_steps':100,'selection':'candidate'}
    choice={'choice_frozen_before_fresh_reference_release':True,'fresh_results_used_for_choice':False,'clause_generation':'clause','boundary_generation':'scope','choices':deepcopy(models),'boundary_choice':head}
    selections={'trials':[{'name':'target','stages':[{'steps':100,'metrics':{'scope_new':{'raw_supported_scope_correct':48,'exact_supported_segmentation':30},'old':{'exact_supported_segmentation':40}}}]}]}
    monkeypatch.setattr(q,'read_ref',lambda pin:choice if pin=='choice' else selections)
    assert q.verify_candidate_choice('choice',{'clause_generation':'clause','boundary_generation':'scope'},{'models':models},{'models':[head],'selections':'selections'},{'trials':[trial]}, {})==choice
