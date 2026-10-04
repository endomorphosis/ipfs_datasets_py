"""Same-parent retention, class-sensitive selection and complete matched slots."""
from copy import deepcopy

import pytest

from scripts.ops.legal_ir import run_legal_temporal_presence_experiment as runner


def metrics(steps=100, positive=24, negative=24):
    value={k:(0 if 'unsupported' in k else maximum//2) for k,maximum in runner.metric_keys().items()}
    return value | {'steps':steps,'tuning_new_exact':positive+negative,
        'tuning_new_Tpresent_exact':positive,'tuning_new_Tabsent_exact':negative,'training_new_exact':0}


@pytest.mark.parametrize('key',['tuning_earlier_exact','tuning_temporal_exact','tuning_prior_consistency_exact',
    'tuning_document_parent_exact','tuning_document_expanded_exact',
    'tuning_prior_facet_document_parent_exact','tuning_prior_facet_document_expanded_exact'])
def test_all_seven_old_gates_allow_only_one_case_loss(key):
    parent=metrics(); stages=[metrics(100),metrics(200),metrics(400,25,25)]
    stages[-1][key]=parent[key]-2
    assert runner.select_stage(stages,parent) is stages[0]
    stages[-1][key]=parent[key]-1
    assert runner.select_stage(stages,parent) is stages[-1]


@pytest.mark.parametrize('key',['tuning_prior_role_exact','tuning_prior_facet_exact',
    'tuning_new_document_parent_exact','tuning_new_document_expanded_exact'])
def test_new_task_nonregression_cannot_be_hidden_by_temporal_improvement(key):
    parent=metrics(); stages=[metrics(step,25,25) for step in runner.STAGES]
    for stage in stages: stage[key]=parent[key]-1
    assert runner.select_stage(stages,parent) is None


@pytest.mark.parametrize('class_name',['Tpresent','Tabsent'])
def test_temporal_class_regression_rejected_even_when_total_improves(class_name):
    parent=metrics(); stages=[metrics(step,23 if class_name=='Tpresent' else 27,
        23 if class_name=='Tabsent' else 27) for step in runner.STAGES]
    assert all(stage['tuning_new_exact']>parent['tuning_new_exact'] for stage in stages)
    assert runner.select_stage(stages,parent) is None


@pytest.mark.parametrize('panel',list(runner.DOCUMENT_PREFIX.values()))
@pytest.mark.parametrize('policy',['parent','expanded'])
def test_all_six_document_guard_gates_required(panel,policy):
    parent=metrics(); stages=[metrics(step,25,25) for step in runner.STAGES]
    for stage in stages: stage[f'tuning_{panel}_{policy}_unsupported_accepted']=1
    assert runner.select_stage(stages,parent) is None


def test_exact_rank_order_and_training_diagnostic_exclusion():
    parent=metrics(); stages=[metrics(step) for step in runner.STAGES]
    stages[-1]['training_new_exact']=192
    assert runner.select_stage(stages,parent) is stages[0]
    stages[-1]['tuning_new_exact']+=1; stages[-1]['tuning_new_Tpresent_exact']+=1
    stages[0]['tuning_prior_role_exact']+=20
    assert runner.select_stage(stages,parent) is stages[-1]
    assert runner.ranking(stages[-1]) == (49,192,36,36,60,36,36,36,36,48,-400)
    stages[-1]['tuning_new_exact']-=1; stages[-1]['tuning_new_Tpresent_exact']-=1
    assert runner.select_stage(stages,parent) is stages[0]


@pytest.mark.parametrize('change',['missing','bool','overflow','wrong_steps','class_sum'])
def test_malformed_stage_metrics_cannot_select(change):
    parent=metrics(); stages=[metrics(step) for step in runner.STAGES]
    if change=='missing': stages[0].pop('tuning_prior_role_exact')
    elif change=='bool': stages[0]['tuning_new_Tpresent_exact']=True
    elif change=='overflow': stages[0]['tuning_new_Tpresent_exact']=49
    elif change=='wrong_steps': stages[0]['steps']=800
    else: stages[0]['tuning_new_exact']+=1
    with pytest.raises((ValueError,KeyError)): runner.select_stage(stages,parent)


def inventory():
    parents,trials={},[]
    for architecture in runner.ARCHITECTURES:
        for seed in runner.SEEDS:
            checkpoint={'path':f'/{architecture}-{seed}','sha256':str(seed)}
            parents[(architecture,seed)]={'checkpoint':checkpoint}
            for objective in runner.OBJECTIVES:
                trials.append({'name':f'{objective}_{architecture}-{seed}','arm':f'{objective}_{architecture}',
                    'objective':objective,'architecture':architecture,'seed':seed,'enabled':architecture=='grounding',
                    'parent':checkpoint,'checkpoint':checkpoint,'decoder_kind':'facet_retention',
                    'executed_steps':400,'selected_steps':0,'selection':'parent_fallback_no_acceptable_replacement'})
    return parents,trials


def test_complete_four_trial_six_model_twelve_pipeline_fallback_inventory():
    parents,trials=inventory();models,pipelines=runner.model_inventory(trials,parents)
    assert len(models)==6 and len(pipelines)==len({p['name'] for p in pipelines})==12
    assert all(model['selected_steps']==0 for model in models)
    bad=deepcopy(trials);bad[0]['checkpoint']={'path':'/different'}
    with pytest.raises(ValueError,match='fallback'):runner.model_inventory(bad,parents)


def test_candidate_cannot_claim_unplanned_stage_or_wrong_runtime():
    parents,trials=inventory(); trial=trials[0]
    trial.update(selection='candidate',selected_steps=200,decoder_kind='temporal_presence')
    assert len(runner.model_inventory(trials,parents)[0])==6
    trial['selected_steps']=800
    with pytest.raises(ValueError,match='candidate'): runner.model_inventory(trials,parents)


def test_matched_updates_and_actual_exposure_coverage(monkeypatch):
    _,trials=inventory()
    pools={'earlier':1152,'historical_new':2736,'positive_pairs':48,'negative_pairs':48}
    def exposure(i):
        return {'optimizer_step':i,'indices_by_pool':{pool:[(i*3+j)%count for j in range(3 if pool in ('earlier','historical_new')
            else (2 if (pool=='positive_pairs') == (i%2==1) else 1))] for pool,count in pools.items()}}
    for trial in trials:
        trial['initial_checkpoint']={'pool_counts':pools}
        trial['stages']=[{'training_report':{'batch_exposures':[exposure(i) for i in range(a,b+1)]}}
            for a,b in ((1,100),(101,200),(201,400))]
    monkeypatch.setattr(runner,'read_ref',lambda value:value)
    audit=runner.audit_trials(trials)
    assert len(audit)==4 and all(r['batch_count']==400 for r in audit)
    assert audit[0]['actual_pool_coverage']['historical_new']['unique_entries_seen']==1200
    assert audit[0]['actual_pool_coverage']['historical_new']['pool_entries']==2736
    trials[0]['stages'][0]['training_report']['batch_exposures'][0]['indices_by_pool']['earlier']=[900]
    with pytest.raises(ValueError,match='matched objectives'):runner.audit_trials(trials)


def test_bounded_full_panel_denominators_exclude_training_diagnostic():
    assert sum(runner.SINGLE_COUNTS.values())==1166 and runner.SINGLE_COUNTS['fresh']==192
    assert runner.SINGLE_COUNTS['real_exposed']==86 and 'training_new' not in runner.SINGLE_COUNTS
    assert sum(runner.DOCUMENT_COUNTS.values())==480
    assert (12+2)*(696+576+192)+6*1166+12*480+2*480==34212
