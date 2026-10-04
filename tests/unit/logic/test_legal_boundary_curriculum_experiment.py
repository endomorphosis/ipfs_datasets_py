"""Boundary continuation quotas, selection, and source/target separation."""
from copy import deepcopy
import json
import random
from types import SimpleNamespace

import pytest

from scripts.ops.legal_ir import run_legal_boundary_curriculum_experiment as runner


def stage(steps, old=36, decision=48, new=60, guards=0):
    return {"steps": steps, "old_supported_exact": old, "old_decision_exact": decision,
        "new_supported_exact": new, "new_unsupported_accepted": guards}


@pytest.mark.parametrize("old,guards,eligible", [(36,0,True), (35,0,True), (34,0,False), (36,1,False), (0,24,False)])
def test_retention_and_zero_guard_gate(old, guards, eligible):
    selected = runner.select_stage([stage(200,old=old,guards=guards),stage(400,old=0),stage(600,old=0)],36)
    assert (selected is not None) is eligible


def test_selection_ranks_new_then_old_decision_then_earliest():
    a,b,c=stage(200,new=60,decision=47),stage(400,new=61,decision=46),stage(600,new=60,decision=48)
    assert runner.select_stage([a,b,c],36)==b
    b['new_supported_exact']=60
    assert runner.select_stage([a,b,c],36)==c
    a['old_decision_exact']=48
    assert runner.select_stage([c,b,a],36)==a


@pytest.mark.parametrize("mutation", ['missing','duplicate','bool_steps','bool_count','bad_old','bad_new','bad_guards','bad_parent'])
def test_invalid_stage_inventory_fails_closed(mutation):
    stages=[stage(200),stage(400),stage(600)];parent=36
    if mutation=='missing': stages.pop()
    elif mutation=='duplicate': stages[-1]['steps']=200
    elif mutation=='bool_steps': stages[-1]['steps']=True
    elif mutation=='bool_count': stages[0]['old_supported_exact']=True
    elif mutation=='bad_old': stages[0]['old_supported_exact']=37
    elif mutation=='bad_new': stages[0]['new_supported_exact']=73
    elif mutation=='bad_guards': stages[0]['new_unsupported_accepted']=-1
    else: parent=True
    with pytest.raises(ValueError): runner.select_stage(stages,parent)


def pool(prefix,count):
    return [{'candidate_id':f'{prefix}-{i}'} for i in range(count)]


@pytest.mark.parametrize('curriculum,old,new',[('replay_only',12,0),('expanded',6,6)])
def test_batch_quota_and_complete_schedule_reproducibility(curriculum,old,new):
    original,extra=pool('old',192),pool('new',384)
    schedule=list(runner.batch_schedule(original,extra,curriculum,1729))
    assert len(schedule)==600
    assert schedule==list(runner.batch_schedule(original,extra,curriculum,1729))
    assert schedule!=list(runner.batch_schedule(original,extra,curriculum,1730))
    for step,(batch,receipt) in enumerate(schedule,1):
        assert receipt['steps']==step and len(batch)==12
        assert len(receipt['old_ids'])==old and len(receipt['new_ids'])==new
        assert [r['candidate_id'] for r in batch]==receipt['old_ids']+receipt['new_ids']
    assert {row for _,receipt in schedule for row in receipt['old_ids']}=={r['candidate_id'] for r in original}
    assert {row for _,receipt in schedule for row in receipt['new_ids']}==({r['candidate_id'] for r in extra} if new else set())


def test_cycling_wraparound_has_full_quota_and_no_skip_within_epoch():
    rows=pool('x',5);stream=runner.CyclingRows(rows,random.Random(1729))
    first=stream.take(3);second=stream.take(3)
    assert len(first)==len(second)==3
    assert {r['candidate_id'] for r in first+second[:2]}=={r['candidate_id'] for r in rows}


def test_replay_schedule_cannot_depend_on_unused_new_examples():
    assert list(runner.batch_schedule(pool('old',192),pool('new',384),'replay_only',1729))==list(
        runner.batch_schedule(pool('old',192),pool('changed',2),'replay_only',1729))


def fixture_docs(prefix,count):
    rows=[]
    for i in range(count):
        text=f'{prefix}{i} Authority must retain records.'
        rows.append({'candidate_id':f'{prefix}-{i}','source_text':text,'source_sha256':runner.boundary.text_sha(text)})
    return rows


@pytest.mark.parametrize('mutation',['label_leak','hash','duplicate','dropped'])
def test_source_only_panels_reject_leaks_or_incomplete_identity(mutation):
    rows=fixture_docs('fresh',3)
    if mutation=='label_leak':rows[0]['supported']=True
    elif mutation=='hash':rows[0]['source_sha256']='bad'
    elif mutation=='duplicate':rows[1]=deepcopy(rows[0])
    else:rows.pop()
    with pytest.raises(ValueError):runner.validate_sources(rows,3)


def controls_fixture():
    return {(a,s):{'checkpoint':{'sha256':f'{a}-{s}'},'name':f'prior_{a}-{s}'} for a in runner.ARCHITECTURES for s in runner.SEEDS}


def trials_fixture(parent):
    return [{'name':f'{c}-{s}','curriculum':c,'seed':s,'checkpoint':parent,'selection':'parent_fallback_no_acceptable_replacement',
        'selected_steps':0} for c in runner.CURRICULA for s in runner.SEEDS]


def test_pipeline_inventory_preserves_all18_slots_and_parent_fallback_attribution():
    parent={'sha256':'parent'}
    models=runner.model_inventory(trials_fixture(parent),controls_fixture(),parent)
    assert len(models)==len({r['name'] for r in models})==18
    assert {r['boundary_head'] for r in models}=={'parent',*(f'{c}-{s}' for c in runner.CURRICULA for s in runner.SEEDS)}
    assert all(r['boundary_checkpoint']==parent and r['boundary_selected_steps']==0 and r['clause_optimizer_updates']==0 for r in models)
    for model in models:
        assert model['checkpoint']==controls_fixture()[model['architecture'],model['seed']]['checkpoint']
        assert model['enabled'] is (model['architecture']=='grounding')


def test_missing_training_trial_cannot_drop_pipeline_denominator():
    with pytest.raises(ValueError,match='six boundary'):
        runner.model_inventory(trials_fixture({})[:-1],controls_fixture(),{})


@pytest.fixture
def inputs(tmp_path,monkeypatch):
    from scripts.ops import legal_ir as package
    corpus=SimpleNamespace(load_training_inputs=None)
    monkeypatch.setattr(package,'prepare_legal_boundary_curriculum',corpus,raising=False)
    def put(name,value):
        path=tmp_path/name;path.write_text(json.dumps(value));return runner.ref(path)
    def sealed(name):return {'path':str(tmp_path/name),'sha256':'a'*64,'bytes':10}
    def refs(prefix,count):
        return [{**r,'supported':i%4!=3,'construction':'fixture','repeated_rule_occurrences':False,
            'clauses':[{'char_start':0,'char_end':len(r['source_text']),'rule':{}}] if i%4!=3 else []}
            for i,r in enumerate(fixture_docs(prefix,count))]
    replay,old,new,tune=refs('oldtrain',192),refs('oldtune',48),refs('newtrain',384),refs('newtune',96)
    original={'schema':runner.clauses.SCHEMA,'config':runner.boundary.CONFIG,'producer_pins':{},
        'references':{'train':put('oldtrain.json',replay),'tuning':put('oldtune.json',old)},
        'sources':{'train':put('oldtrain-sources.json',runner.clauses.source_rows(replay)),
            'tuning':put('oldtune-sources.json',runner.clauses.source_rows(old))}}
    manifest={'artifacts':{'fresh_targets':sealed('fresh-targets.json')}}
    loaded={'manifest':manifest,'replay':replay,'new_train':new,'new_tuning':tune,'fresh_sources':fixture_docs('fresh',96)}
    corpus.load_training_inputs=lambda _:loaded
    monkeypatch.setattr(runner.boundary,'restore',lambda _:None)
    monkeypatch.setattr(runner,'clause_inventory',lambda *_:controls_fixture())
    frozen={'plan':put('prior-plan.json',{'producer_pins':{}}),'heads':put('heads.json',[])}
    config={'schema':runner.CONFIG_SCHEMA,'corpus_manifest':put('manifest.json',manifest),
        'boundary_parent':put('parent.json',{'optimizer_steps':200,'training_manifest_sha256':runner.digest(replay),
            'tuning_manifest_sha256':runner.digest(old)}),'prior_generation':put('prior.json',frozen),
        'prior_boundary_plan':put('old-plan.json',original),'prior_construction_sources':put('prior-sources.json',fixture_docs('prior',96)),
        'prior_construction_targets':sealed('prior-targets.json'),'exposed_document_sources':put('exposed-sources.json',fixture_docs('exposed',96)),
        'exposed_document_targets':sealed('exposed-targets.json'),'study_design':put('design.json',{}),'producer_files':[]}
    path=tmp_path/'config.json';path.write_text(json.dumps(config))
    return path,loaded


def test_loader_succeeds_with_every_fresh_and_regression_target_absent(inputs):
    path,_=inputs
    value=runner.load_config(path)
    assert len(value['replay'])==192 and len(value['new_train'])==384
    assert {key:len(rows) for key,rows in value['sources'].items()}==runner.COUNTS


def test_loader_rejects_training_evaluation_overlap(inputs):
    path,loaded=inputs
    loaded['fresh_sources'][0]=runner.clauses.source_rows(loaded['new_train'])[0]
    with pytest.raises(ValueError,match='overlap'):runner.load_config(path)


def test_loader_rejects_source_panel_target_leak(inputs):
    path,loaded=inputs
    loaded['fresh_sources'][0]['clauses']=[]
    with pytest.raises(ValueError,match='source-only'):runner.load_config(path)


def frozen_bank():
    models=[]
    for arm in runner.retention.ARMS:
        for seed in runner.SEEDS:
            architecture='grounding' if arm.endswith('grounding') else 'continuation'
            policy='prior' if arm.startswith('prior_') else 'document_retained'
            models.append({'name':f'{arm}-{seed}','architecture':architecture,'seed':seed,'decoder_kind':'mixed',
                'curriculum':'temporal_augmented','selection_policy':policy,'selected_steps':800,
                'enabled':architecture=='grounding','requested_enabled':architecture=='grounding',
                'selection':'prior_selected' if policy=='prior' else 'candidate',
                'source_trial_name':f'temporal_augmented_{architecture}-{seed}','checkpoint':{'path':'placeholder'}})
    models += [{'name':f'parent-{seed}'} for seed in runner.SEEDS]
    frozen={'schema':runner.retention.SCHEMA,'all_selection_and_generation_complete':True,
        'challenge_targets_opened':False,'regression_targets_opened':False,'models':models}
    return frozen,deepcopy(models)


def test_prior_inventory_joins_six_temporal_controls_to_exact_frozen_heads(monkeypatch):
    monkeypatch.setattr(runner,'read_ref',lambda *_args,**_kwargs:None)
    controls=runner.clause_inventory(*frozen_bank())
    assert set(controls)=={(a,s) for a in runner.ARCHITECTURES for s in runner.SEEDS}


@pytest.mark.parametrize('mutation',['missing','mismatched_heads','wrong_seed','wrong_steps','wrong_architecture','wrong_curriculum','wrong_ablation'])
def test_prior_inventory_rejects_checkpoint_attribution_drift(monkeypatch,mutation):
    monkeypatch.setattr(runner,'read_ref',lambda *_args,**_kwargs:None)
    frozen,heads=frozen_bank()
    row=next(r for r in frozen['models'] if r['name']=='prior_grounding-1729')
    if mutation=='missing':frozen['models'].pop()
    elif mutation=='mismatched_heads':heads[0]['checkpoint']={'path':'different'}
    elif mutation=='wrong_seed':row['seed']=1730
    elif mutation=='wrong_steps':row['selected_steps']=400
    elif mutation=='wrong_architecture':row['architecture']='continuation'
    elif mutation=='wrong_curriculum':row['curriculum']='baseline'
    else:row['enabled']=False
    if mutation not in ('missing','mismatched_heads'):heads=deepcopy(frozen['models'])
    with pytest.raises(ValueError):runner.clause_inventory(frozen,heads)
