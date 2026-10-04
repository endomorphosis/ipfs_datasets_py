from copy import deepcopy
from pathlib import Path
import subprocess
import sys

import pytest
from scripts.ops.legal_ir import summarize_legal_temporal_presence_experiment as q


def selection():
    parent={'earlier':80,'temporal':100,'prior_consistency':80,'document_parent':40,'document_expanded':60,
        'prior_facet_document_parent':20,'prior_facet_document_expanded':40,'role':60,'facet':140,'new':70,
        'new_positive':35,'new_negative':35,'new_document_parent':20,'new_document_expanded':40}
    stages=[{'steps':step,**parent,**{key:0 for key in q.GUARDS}} for step in q.STAGES]
    return parent,stages


def improve(stage):
    stage['new']+=1;stage['new_positive']+=1


def test_selection_earliest_only_after_frozen_ranking_ties():
    parent,stages=selection();assert q.selection_choice(stages,parent)['steps']==100
    improve(stages[2]);assert q.selection_choice(stages,parent)['steps']==400


@pytest.mark.parametrize('metric',list(q.OLD_BOUNDS))
def test_all_seven_old_gates_allow_one_and_reject_two_losses(metric):
    parent,stages=selection();improve(stages[2]);stages[2][metric]=parent[metric]-2
    assert q.selection_choice(stages,parent)['steps']==100
    stages[2][metric]+=1;assert q.selection_choice(stages,parent)['steps']==400


@pytest.mark.parametrize('metric',['role','facet','new_document_parent','new_document_expanded'])
def test_preservation_and_new_document_gates_allow_no_loss(metric):
    parent,stages=selection();improve(stages[2]);stages[2][metric]=parent[metric]-1
    assert q.selection_choice(stages,parent)['steps']==100
    stages[2][metric]+=1;assert q.selection_choice(stages,parent)['steps']==400


@pytest.mark.parametrize('metric',['new_positive','new_negative'])
def test_stratum_regression_cannot_hide_behind_improved_total_exactness(metric):
    parent,stages=selection();other='new_negative' if metric=='new_positive' else 'new_positive'
    stages[2][metric]-=1;stages[2][other]+=2;stages[2]['new']+=1
    assert q.selection_choice(stages,parent)['steps']==100


@pytest.mark.parametrize('guard',list(q.GUARDS))
def test_all_six_scope_guard_counts_disqualify_and_preserve_explicit_fallback(guard):
    parent,stages=selection()
    for row in stages:row[guard]=1
    assert q.selection_choice(stages,parent) is None


@pytest.mark.parametrize('bad',['missing_stage','wrong_stage','extra_training_score','extra_fresh_score','strata_sum','bool_count','negative','parent_strata_sum'])
def test_malformed_stage_and_reference_leakage_fields_rejected(bad):
    parent,stages=selection()
    if bad=='missing_stage':stages.pop()
    if bad=='wrong_stage':stages[0]['steps']=50
    if bad=='extra_training_score':stages[0]['training_new_exact']=192
    if bad=='extra_fresh_score':stages[0]['fresh_exact']=192
    if bad=='strata_sum':stages[0]['new_positive']+=1
    if bad=='bool_count':stages[0]['role']=True
    if bad=='negative':stages[0]['new_document_parent']=-1
    if bad=='parent_strata_sum':parent['new_positive']-=1
    with pytest.raises(ValueError):q.selection_choice(stages,parent)


def test_equal_weight_old_clause_rank_and_document_tiebreak_order():
    parent,stages=selection();stages[1]['role']+=2;stages[2]['facet']+=3
    assert q.selection_choice(stages,parent)['steps']==200
    stages[2]['facet']+=1;stages[2]['new_document_expanded']+=1
    assert q.selection_choice(stages,parent)['steps']==400
    stages[1]['new_document_expanded']+=1;stages[1]['prior_consistency']+=1
    assert q.selection_choice(stages,parent)['steps']==200


def test_independent_sampler_reconstructs_all400_updates_with_epoch_wraps():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_temporal_presence as runtime
    pools={'earlier':[f'e{i}' for i in range(7)],'historical_new':[f'h{i}' for i in range(11)],
        'positive_pairs':[[f'p{i}a',f'p{i}b'] for i in range(4)],'negative_pairs':[[f'n{i}a',f'n{i}b'] for i in range(4)]}
    counts={k:len(v) for k,v in pools.items()};progress=runtime._progress(counts,1730)
    for step in range(1,401):
        actual,progress=runtime.next_batch_indices(progress,counts,1730);expected=q.expected_batch(1730,step,pools)
        assert actual==expected['indices_by_pool'] and progress==runtime._progress(counts,1730,step)
        assert len(expected['ids'])==12 and len(expected['pairs'])==3
        assert all(identity.startswith('e') for identity in expected['ids'][:3])
        assert all(identity.startswith('h') for identity in expected['ids'][3:6])
        assert sum(identity.startswith('p') for identity in expected['ids'][6:])==(4 if step%2 else 2)


@pytest.mark.parametrize('positive_count',[2,4])
def test_temporal_ce_matches_independent_formula_and_gradient_and_excludes_old_rows(positive_count):
    import torch
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_temporal_presence as runtime
    torch.manual_seed(1309)
    logits=torch.randn(12,4,2,dtype=torch.float64,requires_grad=True)
    output={'presence':logits,'modality':torch.zeros(12,3,dtype=torch.float64)}
    records=[{'labels':{'presence':[True,True,True,False,False,i<6+positive_count]}} for i in range(12)]
    actual,parts=runtime._temporal_presence_loss(torch,output,records)
    terms={0:[],1:[]}
    for i in range(6,12):
        label=int(records[i]['labels']['presence'][5]);scores=logits[i,3]
        terms[label].append(torch.logsumexp(scores,0)-scores[label])
    wanted=sum(torch.stack(values).mean() for values in terms.values())/2
    actual_gradient=torch.autograd.grad(actual,logits,retain_graph=True)[0]
    expected_gradient=torch.autograd.grad(wanted,logits)[0]
    assert float(actual)==pytest.approx(float(wanted),abs=1e-12)
    assert torch.allclose(actual_gradient,expected_gradient,atol=1e-12,rtol=1e-12)
    assert not torch.count_nonzero(actual_gradient[:6]) and not torch.count_nonzero(actual_gradient[:, :3])
    assert parts['temporal_positive_rows']==positive_count and parts['temporal_negative_rows']==6-positive_count
    for row in records[:6]:row['labels']['presence'][5]=not row['labels']['presence'][5]
    with torch.no_grad():logits[:6]=1000
    changed,_=runtime._temporal_presence_loss(torch,output,records);assert actual==changed


def test_actual_os_guard_blocks_reference_open_until_release(tmp_path):
    path=tmp_path/'reference.json';path.write_text('{}')
    code='''import sys
from pathlib import Path
from scripts.ops.legal_ir import summarize_legal_temporal_presence_experiment as q
p=Path(sys.argv[1]);g=q.SealedReadGuard([{'path':str(p)}]);sys.addaudithook(g.event)
try:p.read_bytes()
except ValueError:pass
else:raise AssertionError('premature target read accepted')
assert len(g.events)==1 and not g.events[0]['after_build_freeze']
g.released=True
assert p.read_bytes()==b'{}' and g.events[-1]['after_build_freeze']
'''
    result=subprocess.run([sys.executable,'-c',code,str(path)],cwd=q.ROOT,capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def report_fixture(start=0,finish=100,objective='temporal_presence'):
    replay={key:[{'id':f'{key}-{i}'} for i in range(6)] for key in
        ('earlier','prior_new','temporal','prior_consistency','prior_role','prior_facet')}
    rows=[];pairs=[]
    for i in range(6):
        for side in ('a','b'):
            rows.append({'id':f'new-{i}{side}','canonical_ir':{'rules':[{'temporal':['within 3 days'] if i<3 else []}]}})
        pairs.append({'left_id':f'new-{i}a','right_id':f'new-{i}b'})
    inputs={'replay':replay,'new_train':rows,'training_pairs':pairs}
    before={'progress':{'optimizer_steps':start},'model_state':{'main':[0],'actor_boundary.weight':[0]}}
    after={'progress':{'optimizer_steps':finish},'model_state':{'main':[1],'actor_boundary.weight':[0]},
        'training_config':{'objective':objective,'seed':1730},
        'model_config':{'trigger_enabled':False,'trigger_loss_weight':0.,'actor_loss_weight':0.},
        'facet_parent_checkpoint_sha256':'a'*64,'facet_parent_optimizer_steps':800}
    pools=q.training_pools(inputs);count=finish-start;weight=.5 if objective=='temporal_presence' else 0.
    parts={'semantic':1.,'trigger':0.,'actor':0.,'semantic_earlier':1.,'semantic_new':1.,'actor_earlier':0.,'actor_new':0.,
        'js_modality':.1,'js_presence':.1,'js_endpoints':.1,'base_ce':1.,'consistency_js':.1,'weighted_consistency':.025,
        'base_objective':1.025,'teacher_presence_kl':.1,'teacher_endpoint_kl':.1,'teacher_kl':.1,'teacher_presence_terms':24,
        'teacher_endpoint_terms':12,'span_overlap':.25,'overlap_facet_pairs':36,'teacher_weight':.5,'overlap_weight':.1,
        'weighted_teacher':.05,'weighted_overlap':.025,'common_objective':1.1,'temporal_positive_ce':.3,'temporal_negative_ce':.5,
        'temporal_presence_ce':.4,'temporal_presence_weight':weight,'weighted_temporal_presence':weight*.4,'total':1.1+weight*.4,
        'domain_rows':{'earlier':3,'new':9},'supervised_trigger_rows':9,'trigger_loss_rows':0,'pair_count':3,'consistency_weight':.25}
    components=[{**parts,'temporal_positive_rows':4 if step%2 else 2,'temporal_negative_rows':2 if step%2 else 4}
        for step in range(start+1,finish+1)]
    report={'optimizer_steps':count,'new_optimizer_steps_total':finish,'training_executed':True,'stopped_reason':'step_limit',
        'tuning_used_for_fit':False,'objective':objective,'checkpoint_sha256':q.digest(after),
        'facet_parent_checkpoint_sha256':'a'*64,'facet_parent_optimizer_steps':800,
        'batch_losses':[parts['total']]*count,'batch_loss_components':deepcopy(components),
        'batch_exposures':[q.expected_batch(1730,step,pools) for step in range(start+1,finish+1)],
        'domain_exposures':{'earlier':3*count,'new':9*count},'pair_exposures':3*count,'elapsed_seconds':1.,'gradient_norm_max':1.,
        'auxiliary_gradient_norm_max':{'trigger_boundary':0.,'trigger_modality':0.,'actor_boundary':0.},
        'changed_parameter_names':['main'],'teacher_training_labels_only':True,'teacher_state_unchanged':True,'teacher_gradients_disabled':True}
    eligibility={r['id']:{'teacher_presence_terms':4,'teacher_endpoint_terms':2,'overlap_facet_pairs':3} for pool in replay.values() for r in pool}
    eligibility.update({r['id']:{'overlap_facet_pairs':3} for r in rows})
    return report,before,after,inputs,eligibility


@pytest.mark.parametrize('start,finish',[(0,100),(100,200),(200,400)])
@pytest.mark.parametrize('objective',q.OBJECTIVES)
def test_each_declared_stage_and_both_objectives_verify_complete_update_receipts(start,finish,objective):
    result=q.verify_training_report(*report_fixture(start,finish,objective))
    assert result['optimizer_updates']==finish-start and not result['optimizer_trajectory_replayed']


@pytest.mark.parametrize('mutation',['old_pool','pair_order','class_pool','missing_step','parent_hash','parent_steps','js_total','js_bound',
    'nan_loss','aux_gradient','changed_parameter','tuning_fit','teacher_count','endpoint_count','new_pair_teacher','overlap_count',
    'unbounded_overlap','teacher_weight','overlap_weight','teacher_changed','temporal_weight','positive_rows','negative_rows',
    'temporal_mean','temporal_weighted','common_objective','total'])
def test_corrupted_training_schedule_parent_mask_and_target_objective_rejected(mutation):
    report,before,after,inputs,eligibility=report_fixture();parts=report['batch_loss_components'][11]
    if mutation=='old_pool':inputs['replay']['prior_facet'].reverse()
    if mutation=='pair_order':report['batch_exposures'][11]['pairs'][0].reverse()
    if mutation=='class_pool':inputs['new_train'][0]['canonical_ir']['rules'][0]['temporal']=[]
    if mutation=='missing_step':report['batch_exposures'].pop()
    if mutation=='parent_hash':report['facet_parent_checkpoint_sha256']='b'*64
    if mutation=='parent_steps':report['facet_parent_optimizer_steps']=400
    if mutation=='js_total':parts['consistency_js']=.2
    if mutation=='js_bound':parts['js_endpoints']=.8
    if mutation=='nan_loss':report['batch_losses'][11]=float('nan')
    if mutation=='aux_gradient':report['auxiliary_gradient_norm_max']['actor_boundary']=1.
    if mutation=='changed_parameter':report['changed_parameter_names']=[]
    if mutation=='tuning_fit':report['tuning_used_for_fit']=True
    if mutation=='teacher_count':parts['teacher_presence_terms']-=1
    if mutation=='endpoint_count':parts['teacher_endpoint_terms']+=2
    if mutation=='new_pair_teacher':parts['teacher_presence_terms']+=24
    if mutation=='overlap_count':parts['overlap_facet_pairs']-=1
    if mutation=='unbounded_overlap':parts['span_overlap']=1.1
    if mutation=='teacher_weight':parts['teacher_weight']=.4
    if mutation=='overlap_weight':parts['overlap_weight']=.2
    if mutation=='teacher_changed':report['teacher_state_unchanged']=False
    if mutation=='temporal_weight':parts['temporal_presence_weight']=0.
    if mutation=='positive_rows':parts['temporal_positive_rows']=4
    if mutation=='negative_rows':parts['temporal_negative_rows']=2
    if mutation=='temporal_mean':parts['temporal_presence_ce']=.5
    if mutation=='temporal_weighted':parts['weighted_temporal_presence']=.3
    if mutation=='common_objective':parts['common_objective']=1.
    if mutation=='total':parts['total']+=.1
    with pytest.raises(ValueError):q.verify_training_report(report,before,after,inputs,eligibility)


def inventory_fixture():
    models=[];pipelines=[];files={};document_files={};heads={'parent':{},'expanded-1730':{}}
    boundaries={name:{panel:{} for panel in q.DOCUMENT_COUNTS} for name in heads}
    for objective in q.POLICIES:
        for architecture in q.ARCHITECTURES:
            name=f'{objective}_{architecture}-1730';control=objective=='parent'
            model={'name':name,'objective':objective,'architecture':architecture,'seed':1730,'enabled':architecture=='grounding',
                'decoder_kind':'facet_retention' if control else 'temporal_presence','checkpoint':{'sha256':name},
                'selection':'unchanged_parent' if control else 'candidate','selected_steps':0 if control else 100,'executed_steps':0 if control else 400}
            models.append(model);files[name]={panel:{} for panel in q.SINGLE_COUNTS}
            for policy in ('parent','expanded'):
                pipe={**model,'name':name+'__'+policy,'source_model_name':name,'boundary_policy':policy,
                    'boundary_head':'parent' if policy=='parent' else 'expanded-1730'}
                pipelines.append(pipe);document_files[pipe['name']]={panel:{} for panel in q.DOCUMENT_COUNTS}
    return models,pipelines,files,document_files,heads,boundaries


def test_bounded_inventory_preserves_every_source_and_fixed_parent():
    assert q.verify_inventory(*inventory_fixture())=={'single_model_slots':6,'document_pipeline_slots':12,'fixed_boundary_heads':2,
        'selected_single_rows':6996,'selected_pipeline_documents':5760,'fixed_boundary_documents':960}


@pytest.mark.parametrize('mutation',['missing_model','missing_real_panel','boundary_seed','control_updates','changed_pipeline_weights'])
def test_inventory_rejects_unreported_coverage_loss_or_parent_update(mutation):
    args=inventory_fixture();models,pipelines,files,_,_,_=args
    if mutation=='missing_model':models.pop()
    if mutation=='missing_real_panel':files[models[0]['name']].pop('real_exposed')
    if mutation=='boundary_seed':pipelines[1]['boundary_head']='expanded-1731'
    if mutation=='control_updates':models[0]['executed_steps']=1
    if mutation=='changed_pipeline_weights':pipelines[0]['checkpoint']={'sha256':'other'}
    with pytest.raises(ValueError):q.verify_inventory(*args)


def test_grouped_replay_loads_once_and_recomputes_each_saved_panel(monkeypatch):
    from scripts.ops.legal_ir import run_legal_temporal_presence_experiment as runner
    checkpoint={'path':'fixture','sha256':'a'*64};model={'checkpoint':checkpoint,'decoder_kind':'temporal_presence'}
    jobs=[{'kind':'single','name':str(i),'model':model,'sources':[{'id':str(i)}]} for i in range(4)]
    groups=q.group_replay_jobs(jobs);loads=[];replayed=[]
    monkeypatch.setattr(runner,'load_decoder',lambda *args:loads.append(args) or object())
    monkeypatch.setattr(q,'read_ref',lambda *args,**kwargs:None)
    monkeypatch.setattr(q,'replay_with_decoder',lambda job,decoder:replayed.append(job['name']) or {'name':job['name']})
    assert len(groups)==1 and len(q.replay_group(groups[0]))==4 and len(loads)==1 and replayed==['0','1','2','3']


def admitted_annotations():
    from scripts.ops.legal_ir import prepare_legal_temporal_presence_corpus as corpus
    return [corpus.render('train',family,modality,mask,side) for family in corpus.FAMILIES for modality in range(3)
        for mask in range(8) for side in range(2)]


def test_admitted_temporal_coordinates_and_opaque_negative_scope_independently_reconstruct():
    rows=admitted_annotations();count=0
    for row,label in rows:
        q.verify_annotation(row,label,'train');result=q.verify_temporal_annotation(row,label)
        count+=result['condition_owned_temporal_language']
    assert len(rows)==192 and count==24
    assert {label['temporal_kind'] for _,label in rows}=={None,'within_days','within_hours','before_calendar'}
    assert {label['temporal_placement'] for _,label in rows}=={'absent','before_actor','between_actor_and_modal','between_modal_and_action','after_object'}


@pytest.mark.parametrize('mutation',['scope','present','kind','placement','opaque','coordinate','invented_deadline','boolean_type'])
def test_scope_metadata_cannot_relabel_applicability_atom_as_action_deadline(mutation):
    rows=admitted_annotations()
    row,label=deepcopy(next((r,a) for r,a in rows if a['condition_owned_temporal_language']))
    if mutation=='scope':label['temporal_scope']='action_deadline'
    if mutation=='present':label['temporal_present']=True
    if mutation=='kind':label['temporal_kind']='within_days'
    if mutation=='placement':label['temporal_placement']='before_actor'
    if mutation=='opaque':label['condition_owned_temporal_language']=False
    if mutation=='coordinate':row['facet_spans']['temporal']=row['facet_spans']['conditions']
    if mutation=='invented_deadline':row['canonical_ir']['rules'][0]['temporal']=['within 17 days']
    if mutation=='boolean_type':label['temporal_present']=0
    with pytest.raises(ValueError):q.verify_temporal_annotation(row,label)


def test_admitted_document_annotations_preserve_duplicate_occurrence_and_temporal_scope():
    from scripts.ops.legal_ir import prepare_legal_temporal_presence_corpus as corpus
    pairs=[corpus.authored_document('document_tuning',i) for i in range(96)]
    rows,labels=map(list,zip(*pairs));clauses=q.document_clauses(rows,labels)
    coords=[c for label in labels for c in label['clause_coordinates']]
    assert len(clauses)==len(coords)==144 and sum(r['repeated_rule_occurrences'] for r in rows)==12
    scopes=[q.verify_temporal_annotation(row,annotation) for row,annotation in zip(clauses,coords,strict=True)]
    assert any(row['condition_owned_temporal_language'] for row in scopes)
    corrupted=deepcopy(coords[0]);corrupted['temporal_scope']='invented'
    with pytest.raises(ValueError):q.verify_temporal_annotation(clauses[0],corrupted)


def test_opaque_negative_timing_requires_stipulated_explicit_origin():
    row,label=deepcopy(next((r,a) for r,a in admitted_annotations() if a['condition_owned_temporal_language']))
    rule=row['canonical_ir']['rules'][0];rule['conditions'][0]=rule['conditions'][0].removesuffix(' of publication')
    with pytest.raises(ValueError,match='origin'):q.verify_temporal_annotation(row,label)
