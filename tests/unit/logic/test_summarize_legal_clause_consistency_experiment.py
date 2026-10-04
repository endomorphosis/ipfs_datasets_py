from copy import deepcopy
import pytest
from scripts.ops.legal_ir import summarize_legal_clause_consistency_experiment as subject


def stages():
    return [{'steps': step, 'earlier': 95, 'temporal': 119, 'document_parent': 69,
        'document_expanded': 69, 'new': 80, 'guard_parent': 0, 'guard_expanded': 0} for step in (400,800)]


def parent():
    return {'earlier':96,'temporal':120,'document_parent':70,'document_expanded':70}


@pytest.mark.parametrize('field', ['earlier','temporal','document_parent','document_expanded'])
def test_each_independent_retention_gate_can_force_parent_fallback(field):
    rows=stages()
    for row in rows: row[field]-=1
    assert subject.selection_choice(rows,parent()) is None


@pytest.mark.parametrize('field',['guard_parent','guard_expanded'])
def test_either_boundary_guard_acceptance_rejects_stage(field):
    rows=stages(); rows[0][field]=1
    assert subject.selection_choice(rows,parent())['steps']==800


def test_rank_new_then_temporal_then_expanded_doc_then_parent_doc_then_earlier_then_earliest():
    rows=stages(); assert subject.selection_choice(rows,parent())['steps']==400
    order=('new','temporal','document_expanded','document_parent','earlier')
    for i,key in enumerate(order):
        rows=stages(); rows[1][key]+=1
        for lower in order[i+1:]: rows[0][lower]+=1
        assert subject.selection_choice(rows,parent())['steps']==800


@pytest.mark.parametrize('mutation',['test_metric','bool','bound','step','missing'])
def test_gate_rejects_test_metrics_or_incomplete_protocol(mutation):
    rows=stages()
    if mutation=='test_metric':rows[0]['fresh_exact']=144
    elif mutation=='bool':rows[0]['guard_parent']=False
    elif mutation=='bound':rows[0]['new']=97
    elif mutation=='step':rows[0]['steps']=800
    else:rows.pop()
    with pytest.raises(ValueError):subject.selection_choice(rows,parent())


def pairs_fixture():
    rule={'rules':[{'modality':'O','actor':'Office','action':'retain','object':'files','conditions':[],
        'exceptions':['notice remains active'],'temporal':[]}]}
    rows=[{'id':str(i),'source_text':'Source '+str(i),'canonical_ir':deepcopy(rule),'domain':'new',
        'trigger_supervised':True,'trigger_span':[0,1]} for i in range(4)]
    rows[2]['canonical_ir']['rules'][0]['exceptions']=[]
    rows[3]['canonical_ir']['rules'][0]['exceptions']=[]
    pairs=[{'pair_id':str(i),'case_group':'case','left_id':str(i*2),'right_id':str(i*2+1),
        'canonical_ir_sha256':subject.digest(rows[i*2]['canonical_ir'])} for i in range(2)]
    return rows,pairs


def test_semantic_pair_audit_preserves_complete_atoms_and_both_source_members():
    result=subject.verify_pairs(*pairs_fixture())
    assert result['pairs']==2 and result['rows']==4 and result['complete_canonical_semantics_equal'] is True


@pytest.mark.parametrize('mutation',['modality','exception','missing_row','reused_case','reused_member','foreign_member','same_source','guessed_trigger'])
def test_semantic_pair_audit_rejects_partial_equivalence_or_leakage(mutation):
    rows,pairs=pairs_fixture()
    if mutation=='modality':rows[1]['canonical_ir']['rules'][0]['modality']='P'
    elif mutation=='exception':rows[1]['canonical_ir']['rules'][0]['exceptions']=[]
    elif mutation=='missing_row':rows.pop()
    elif mutation=='reused_case':pairs[1]['case_group']='split_case'
    elif mutation=='reused_member':pairs[1]['left_id']='0'
    elif mutation=='foreign_member':pairs[1]['left_id']='foreign'
    elif mutation=='same_source':rows[1]['source_text']=rows[0]['source_text']
    else:rows[1]['trigger_supervised']=False
    with pytest.raises(ValueError):subject.verify_pairs(rows,pairs)


def test_error_metrics_keep_exception_omissions_separate_from_abstentions_and_spurious_insertions(monkeypatch):
    empty={'modality':'O','actor':'Office','action':'retain','object':'files','conditions':[],'exceptions':[],'temporal':[]}
    exception={**empty,'exceptions':['notice remains active']}
    sources=[{'id':str(i)} for i in range(3)]
    references=[{'id':str(i),'canonical_ir':{'rules':[rule]}} for i,rule in enumerate((exception,exception,empty))]
    generation={'rows':[{'status':'decoded','canonical_ir':{'rules':[empty]},'reason':None},
        {'status':'abstained','canonical_ir':None,'reason':'copied_spans_overlap'},
        {'status':'decoded','canonical_ir':{'rules':[exception]},'reason':None}]}
    monkeypatch.setattr(subject.retained.prior,'annotated_metrics',lambda *a,**kw:{'count':3})
    result=subject.single_error_metrics(generation,sources,references,enabled=False)
    counts=result['error_counts']
    assert counts['exceptions_decoded_omissions']==1
    assert counts['exceptions_present_reference_abstained']==1
    assert counts['exceptions_decoded_spurious_insertions']==1
    assert counts['overlap_abstentions']==1
    assert result['modality_confusion_including_abstentions']=={'O->O':2,'O->abstained':1}
    assert result['error_rows'][1]['exceptions']['predicted_present'] is None


def test_probability_role_projection_and_js_gradients_match_independent_formula():
    result=subject.objective_sanity()
    assert result['equal_three_component_mean_verified'] and result['both_pair_sides_have_gradients']
    assert result['absent_endpoint_exclusion_verified'] and result['paired_source_order_and_padding_invariance_verified']


def training_report_fixture():
    inputs={'replay':{'earlier':[{'id':f'old{i}'} for i in range(6)],
        'prior_new':[{'id':f'new{i}'} for i in range(3)],'temporal':[{'id':f'time{i}'} for i in range(3)]},
        'training_pairs':[{'left_id':f'left{i}','right_id':f'right{i}'} for i in range(3)]}
    pools={'earlier':[r['id'] for r in inputs['replay']['earlier']],
        'historical_new':[r['id'] for p in ('prior_new','temporal') for r in inputs['replay'][p]],
        'pairs':[[r['left_id'],r['right_id']] for r in inputs['training_pairs']]}
    preceding={'progress':{'optimizer_steps':0},'model_state':{'z':[0.],'a':[0.]}}
    cp={'progress':{'optimizer_steps':400},'training_config':{'objective':'consistency','seed':1729},
        'model_config':{'trigger_enabled':False,'trigger_loss_weight':.25,'actor_loss_weight':.25},
        'mixed_parent_checkpoint_sha256':'p','mixed_parent_optimizer_steps':800,'model_state':{'a':[1.],'z':[1.]}}
    parts={'semantic':1.,'trigger':0.,'actor':0.,'semantic_earlier':.8,'semantic_new':1.2,
        'actor_earlier':0.,'actor_new':0.,'js_modality':.1,'js_presence':.2,'js_endpoints':.3,
        'base_ce':1.,'consistency_js':.2,'weighted_consistency':.05,'total':1.05,
        'domain_rows':{'earlier':3,'new':9},'supervised_trigger_rows':9,'trigger_loss_rows':0,
        'pair_count':3,'consistency_weight':.25}
    report={'optimizer_steps':400,'new_optimizer_steps_total':400,'training_executed':True,'stopped_reason':'step_limit',
        'tuning_used_for_fit':False,'objective':'consistency','checkpoint_sha256':subject.digest(cp),
        'mixed_parent_checkpoint_sha256':'p','mixed_parent_optimizer_steps':800,
        'batch_losses':[1.05]*400,'batch_loss_components':[deepcopy(parts) for _ in range(400)],
        'batch_exposures':[subject.expected_batch(1729,s,pools) for s in range(1,401)],
        'domain_exposures':{'earlier':1200,'new':3600},'pair_exposures':1200,'elapsed_seconds':5.,'gradient_norm_max':2.,
        'auxiliary_gradient_norm_max':{'trigger_boundary':0.,'trigger_modality':0.,'actor_boundary':0.},
        'changed_parameter_names':['z','a']}
    return report,preceding,cp,inputs


def test_training_report_independently_checks_objective_batches_loss_and_json_reordered_parameters():
    result=subject.verify_training_report(*training_report_fixture())
    assert result['optimizer_updates']==400 and result['pair_exposures']==1200
    assert result['independent_schedule_and_loss_accounting_verified'] is True
    assert result['optimizer_trajectory_replayed'] is False


@pytest.mark.parametrize('mutation',['batch_pair','batch_order','missing_step','weighted_js','averaging','js_bound','nan',
    'trigger_mask','aux_gradient','changed_tensor','historical_steps','tuning_fit'])
def test_training_report_rejects_corrupt_objective_and_exposure_claims(mutation):
    report,prev,cp,inputs=training_report_fixture()
    if mutation=='batch_pair':report['batch_exposures'][0]['pairs'][0][0]='foreign'
    elif mutation=='batch_order':report['batch_exposures'][0]['ids'].reverse()
    elif mutation=='missing_step':report['batch_losses'].pop()
    elif mutation=='weighted_js':report['batch_loss_components'][0]['weighted_consistency']=0.
    elif mutation=='averaging':report['batch_loss_components'][0]['consistency_js']=.6
    elif mutation=='js_bound':report['batch_loss_components'][0]['js_modality']=1.
    elif mutation=='nan':report['batch_losses'][0]=float('nan')
    elif mutation=='trigger_mask':report['batch_loss_components'][0]['trigger_loss_rows']=9
    elif mutation=='aux_gradient':report['auxiliary_gradient_norm_max']['actor_boundary']=1.
    elif mutation=='changed_tensor':report['changed_parameter_names']=['a','a']
    elif mutation=='historical_steps':report['mixed_parent_optimizer_steps']=400
    else:report['tuning_used_for_fit']=True
    with pytest.raises(ValueError):subject.verify_training_report(report,prev,cp,inputs)


def inventory_fixture():
    models=[];pipelines=[]
    for o in subject.POLICIES:
        for a in subject.ARCHITECTURES:
            for s in subject.SEEDS:
                model={'name':f'{o}_{a}-{s}','objective':o,'architecture':a,'seed':s,'enabled':a=='grounding',
                    'decoder_kind':'mixed' if o=='parent' else 'consistency','checkpoint':{'path':f'{o}_{a}-{s}'},
                    'selection':'unchanged_parent' if o=='parent' else 'candidate',
                    'selected_steps':0 if o=='parent' else 800,'executed_steps':0 if o=='parent' else 800}
                models.append(model)
                for policy in ('parent','expanded'):
                    pipelines.append({**model,'name':model['name']+'__'+policy,'source_model_name':model['name'],
                        'boundary_policy':policy,'boundary_head':'parent' if policy=='parent' else f'expanded-{s}'})
    heads=dict.fromkeys(['parent',*(f'expanded-{s}' for s in subject.SEEDS)])
    return models,pipelines,{m['name']:dict.fromkeys(subject.SINGLE_COUNTS) for m in models},\
        {p['name']:dict.fromkeys(subject.DOCUMENT_COUNTS) for p in pipelines},heads,\
        {h:dict.fromkeys(subject.DOCUMENT_COUNTS) for h in heads}


def test_inventory_preserves_all_control_objective_and_two_boundary_slots():
    result=subject.verify_inventory(*inventory_fixture())
    assert result['single_model_slots']==18 and result['document_pipeline_slots']==36
    assert result['fixed_boundary_documents']==1536


@pytest.mark.parametrize('mutation',['model','pipeline','head','source_model','wrong_seed','source_panel','document_panel'])
def test_inventory_rejects_missing_slots_or_cross_seed_boundary_pairing(mutation):
    models,pipelines,files,documents,heads,boundaries=inventory_fixture()
    if mutation=='model':models.pop()
    elif mutation=='pipeline':pipelines.pop()
    elif mutation=='head':heads.pop('expanded-1731')
    elif mutation=='source_model':pipelines[-1]['source_model_name']=models[0]['name']
    elif mutation=='wrong_seed':pipelines[-1]['boundary_head']='expanded-1729'
    elif mutation=='source_panel':files[models[0]['name']].pop('fresh')
    else:documents[pipelines[0]['name']].pop('fresh_documents')
    with pytest.raises(ValueError):subject.verify_inventory(models,pipelines,files,documents,heads,boundaries)
