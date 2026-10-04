"""Declared exposed retention gates, abstention-aware facets and factor isolation."""
from copy import deepcopy
from pathlib import Path
import runpy

import pytest
from scripts.ops.legal_ir import run_legal_condition_rehearsal_experiment as runner


def scoped(n):
    return {'count':n,'fullrule_exact':n//2,'modality_fullrule':{m:{'count':n//3,'exact':n//6} for m in 'OPF'},
        **{kind:{label:{'count':n//2,'exact':n//4+(n//16 if kind.endswith('facet') else 0)} for label in ('present','absent')}
            for kind in ('condition_facet','temporal_facet','condition_fullrule','temporal_fullrule')}}


def metrics(step=100):
    v={k:(0 if 'unsupported' in k else count//2) for k,count in runner.metric_keys().items()}
    return v|{'steps':step,'training_new_exact':0,'retention_metrics':{p:scoped(192) for p in runner.RETENTION_PANELS},'condition_metrics':scoped(96)}


@pytest.mark.parametrize('panel',['facet','temporal'])
@pytest.mark.parametrize('kind',['condition_facet','temporal_facet'])
@pytest.mark.parametrize('label',['present','absent'])
def test_exposed_facet_classes_cannot_regress_with_unchanged_fullrule(panel,kind,label):
    parent=metrics();stages=[metrics(100),metrics(200)]
    for stage in stages:stage['retention_metrics'][panel][kind][label]['exact']-=1
    assert runner.select_stage(stages,parent) is None


@pytest.mark.parametrize('panel',['facet','temporal'])
@pytest.mark.parametrize('modality',list('OPF'))
def test_modality_fullrule_regression_cannot_hide_in_total(panel,modality):
    parent=metrics();stages=[metrics(100),metrics(200)];other=next(m for m in 'OPF' if m!=modality)
    for stage in stages:
        stage['retention_metrics'][panel]['modality_fullrule'][modality]['exact']-=1
        stage['retention_metrics'][panel]['modality_fullrule'][other]['exact']+=1
    assert runner.select_stage(stages,parent) is None


@pytest.mark.parametrize('kind',['condition_fullrule','temporal_fullrule'])
@pytest.mark.parametrize('label',['present','absent'])
def test_new_condition_class_gates_use_fullrule_accuracy(kind,label):
    parent=metrics();stages=[metrics(100),metrics(200)];other='absent' if label=='present' else 'present'
    for stage in stages:
        stage['condition_metrics'][kind][label]['exact']-=1;stage['condition_metrics'][kind][other]['exact']+=1
    assert runner.select_stage(stages,parent) is None


@pytest.mark.parametrize('panel',['facet','temporal'])
@pytest.mark.parametrize('policy',['parent','expanded'])
def test_only_exposed_document_guard_ceiling_tracks_parent(panel,policy):
    parent=metrics();stages=[metrics(100),metrics(200)];prefix='tuning_retention_'+panel+'_document_'+policy
    parent[prefix+'_unsupported_accepted']=1
    for stage in stages:stage[prefix+'_unsupported_accepted']=1
    assert runner.select_stage(stages,parent) is stages[0]
    for stage in stages:stage[prefix+'_unsupported_accepted']=2
    assert runner.select_stage(stages,parent) is None
    for stage in stages:
        stage[prefix+'_unsupported_accepted']=0;stage[prefix+'_exact']=parent[prefix+'_exact']-1
    assert runner.select_stage(stages,parent) is None


@pytest.mark.parametrize('prefix',['document','prior_facet_document','new_document','condition_document'])
def test_original_and_new_tuning_guards_remain_zero(prefix):
    parent=metrics();stages=[metrics(100),metrics(200)]
    for stage in stages:stage['tuning_'+prefix+'_expanded_unsupported_accepted']=1
    assert runner.select_stage(stages,parent) is None


def test_rank_prioritizes_new_condition_then_condition_repair_and_never_train_accuracy():
    parent=metrics();early=metrics(100);late=metrics(200);late['training_new_exact']=192
    assert runner.select_stage([late,early],parent) is early
    late['retention_metrics']['facet']['condition_facet']['present']['exact']+=1
    assert runner.select_stage([late,early],parent) is late
    assert runner.ranking(early)==(48,120,192,*runner.previous.ranking(early)[:-1],-100)
    assert len(runner.ranking(early))==14


def test_abstentions_are_errors_for_absent_qualifiers_and_exact_modality():
    truth={'rules':[{'modality':'O','actor':'office','action':'retain','object':'files','conditions':[],'exceptions':[],'temporal':[]}]}
    sources=[{'id':'a'},{'id':'b'}];targets=[{'id':'a','canonical_ir':truth},{'id':'b','canonical_ir':truth}]
    rows=[{'status':'decoded','canonical_ir':truth},{'status':'abstained','canonical_ir':None}]
    result=runner.scoped_metrics(rows,sources,targets)
    assert result['fullrule_exact']==1 and result['modality_fullrule']['O']=={'count':2,'exact':1}
    assert result['condition_facet']['absent']==result['temporal_facet']['absent']=={'count':2,'exact':1}


def test_malformed_nested_metrics_or_stage_inventory_fail_closed():
    parent=metrics();stage=metrics();stage['retention_metrics']['facet']['condition_facet']['present']['count']=95
    with pytest.raises(ValueError):runner.select_stage([stage,metrics(200)],parent)
    stage=metrics();stage['condition_metrics']['fullrule_exact']+=1
    with pytest.raises(ValueError):runner.select_stage([stage,metrics(200)],parent)
    with pytest.raises(ValueError):runner.select_stage([metrics(),metrics(400)],parent)


def inventory():
    parents={};trials=[]
    for arch in runner.ARCHITECTURES:
        kind='facet_retention' if arch=='continuation' else 'temporal_presence'
        pin={'path':'/'+arch,'sha256':arch};parents[(arch,1730)]={'checkpoint':pin,'decoder_kind':kind}
        for objective in runner.OBJECTIVES:
            trials.append({'name':f'{objective}_{arch}-1730','arm':f'{objective}_{arch}','architecture':arch,
                'seed':1730,'objective':objective,'enabled':arch=='grounding','parent':pin,'checkpoint':pin,
                'decoder_kind':kind,'executed_steps':200,'selected_steps':0,'selection':'parent_fallback_no_acceptable_replacement'})
    return parents,trials


def test_heterogeneous_fallbacks_preserve_exact_parent_decoder_kind():
    parents,trials=inventory();models=runner.model_inventory(trials,parents)
    assert len(models)==6 and {m['decoder_kind'] for m in models}=={'facet_retention','temporal_presence'}
    trials[0]['decoder_kind']='scope_retention'
    with pytest.raises(ValueError,match='fallback'):runner.model_inventory(trials,parents)


def test_actual_main_and_auxiliary_exposures_match_across_arms(monkeypatch):
    _,trials=inventory();counts={'earlier':1152,'historical_new':2736,'positive_pairs':48,'negative_pairs':48}
    for trial in trials:
        trial['initial_checkpoint']={'pool_counts':counts}
        trial['stages']=[{'training_report':{'batch_exposures':[{'optimizer_step':i,'indices_by_pool':{k:[i%n] for k,n in counts.items()},
            'rehearsal_ids':[str(i%64),str((i+1)%64),'n'+str(i%64),'n'+str((i+1)%64)]} for i in range(a,b)]}} for a,b in ((1,101),(101,201))]
    monkeypatch.setattr(runner,'read_ref',lambda value:value)
    audit=runner.audit_trials(trials);assert len(audit)==4
    assert all(row['rehearsal_unique_ids']==128 and row['rehearsal_draws']==800 for row in audit)
    trials[0]['stages'][0]['training_report']['batch_exposures'][0]['rehearsal_ids'][0]='wrong'
    with pytest.raises(ValueError,match='matched objectives'):runner.audit_trials(trials)


def test_complete_bounded_panel_counts_and_separate_crossproduct_interface():
    assert sum(runner.SINGLE_COUNTS.values())==1454
    assert len(runner.DOCUMENT_TUNING_PANELS)==6 and sum(runner.DOCUMENT_COUNTS.values())==672
    assert sum(runner.FINAL_DOCUMENT_COUNTS.values())==288
    assert set(runner.FINAL_BOUNDARY_SOURCE_NAMES)==set(runner.FINAL_DOCUMENT_COUNTS)
    assert runner.STAGES==(100,200) and runner.SEEDS==(1730,)
