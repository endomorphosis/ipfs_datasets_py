"""Leakage, replay and sealed-budget contracts for the action-binding study."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core

ROOT=Path(__file__).resolve().parents[5]
PATH=ROOT/'scripts/ops/autoencoder/benchmark_action_binding_source_training.py'
SPEC=importlib.util.spec_from_file_location('_action_binding_runner_tests',PATH)
subject=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(subject)


def write(path,value):
    path.write_text(json.dumps(value,sort_keys=True,allow_nan=False))


@pytest.mark.parametrize('field,value',[
    ('dimensions',[8,384]),('fit_count',12),('fresh_initialization',False),
    ('validation_pairs_added_to_training',True),('teacher_distillation_used',True),
    ('selection_unchanged',False),('fixed_encoder_context_tokens',8192),('temperature',.1),
    ('syntax_forced',True),('full_vocabulary_retained',False),('baseline_replay_required',False),
    ('expected_optimizer_steps_per_arm',339),('no_downloads',False),('production_promotion_allowed',True)])
def test_changed_authority_or_matched_exposure_rejected(field,value):
    plan=deepcopy(subject.FIXED); subject.validate_plan(plan); plan[field]=value
    with pytest.raises(ValueError,match='fixed action-binding'): subject.validate_plan(plan)


def test_loss_temperature_does_not_change_generation_temperature_or_recipes():
    assert subject.FIXED['temperature']==0
    assert subject.FIXED['action_contrastive_temperature']==.1
    jobs=subject.jobs()
    assert len(jobs)==18 and len(subject.CONTROLS)*2*len(jobs)==288
    assert [(d,s,a['name']) for d,s,a in jobs]==[(d,s,a) for d in (8,384,768)
        for s in (1729,2718) for a in ('clauses','action-head','action-contrastive')]
    jobs[0][2]['action_contrastive_weight']=.9
    assert subject.jobs()[0][2]['action_contrastive_weight']==0
    assert all(v is False for v in subject.FALSE.values())


def fixture(tmp_path,monkeypatch):
    parent_manifest=tmp_path/'parent-manifest.json'; parent_plan=tmp_path/'parent-plan.json'
    baseline=tmp_path/'baseline.json'
    for path,value in [(parent_manifest,{}),(parent_plan,{}),
        (baseline,dict(complete=True,runs=[dict(arm=str(i)) for i in range(12)]))]: write(path,value)
    inputs={str(p):subject.sha(p) for p in (parent_manifest,parent_plan,baseline)}
    plan=tmp_path/'plan.json'; write(plan,dict(subject.FIXED,input_sha256=inputs))
    manifest=tmp_path/'manifest.json'; write(manifest,dict(inputs=inputs,plan_sha256=subject.sha(plan),extensions={},
        parent_manifest=str(parent_manifest),parent_plan=str(parent_plan),baseline_summary=str(baseline)))
    calls=[]
    ctx=dict(owners={},helpers=SimpleNamespace(extension=lambda *a:calls.append(('extension',a)) or object()))
    native=SimpleNamespace(load_context=lambda args:calls.append(('parent',args)) or ctx)
    monkeypatch.setattr(subject,'load_helper',lambda *a:native)
    args=SimpleNamespace(manifest=manifest,plan=plan,extension_root=tmp_path,dependency_root=tmp_path,
        output=tmp_path/'output',phase='training')
    return args,calls,baseline


def test_context_preserves_authenticated_parent_and_explicit_new_owners(tmp_path,monkeypatch):
    args,calls,_=fixture(tmp_path,monkeypatch); ctx=subject.load_context(args)
    assert calls[0][0]=='parent' and calls[0][1].manifest.name=='parent-manifest.json'
    assert set(ctx['owners'])=={'action_factorized_clause_decoder_experiment','action_contrastive_decoder_training'}
    assert len(ctx['baseline_runs'])==12


def test_changed_baseline_bytes_fail_before_parent_model_load(tmp_path,monkeypatch):
    args,calls,baseline=fixture(tmp_path,monkeypatch); write(baseline,{'complete':True,'runs':[]})
    with pytest.raises(ValueError,match='input changed'): subject.load_context(args)
    assert calls==[]


def test_unbound_parent_alias_is_rejected(tmp_path,monkeypatch):
    args,calls,_=fixture(tmp_path,monkeypatch)
    m=json.loads(args.manifest.read_bytes()); m['parent_plan']=str(tmp_path/'unbound.json'); write(args.manifest,m)
    with pytest.raises(ValueError,match='unbound manifest alias'): subject.load_context(args)
    assert calls==[]


def replay():
    report={'elapsed_seconds':1.,'selected_weights_sha256':'selected','last_complete_attempt_weights_sha256':'final',
        'history':[{'source_fidelity':{'ordered_exact':0},'learning_rate':.001}],'config':{'max_seconds':180}}
    panels={role:{label:dict(predictions=[{'id':'v1','token_ids':[1,2]}]) for label,_,_ in subject.CONTROLS}
        for role in ('selected','last-attempt')}
    ctx=dict(core=core,dimension=8,baseline_runs={'8-clauses-1729':dict(training=deepcopy(report),postfit=deepcopy(panels))})
    return ctx,report,panels


def test_only_elapsed_time_is_excluded_from_baseline_replay():
    ctx,report,panels=replay(); report['elapsed_seconds']=999
    assert subject.validate_baseline(ctx,report,panels,1729)['complete']
    report['config']['max_seconds']=181
    with pytest.raises(ValueError,match='baseline replay differs: config'): subject.validate_baseline(ctx,report,panels,1729)


@pytest.mark.parametrize('field',['selected_weights_sha256','last_complete_attempt_weights_sha256','history'])
def test_changed_state_or_trajectory_is_not_a_replay(field):
    ctx,report,panels=replay(); report[field]='different'
    with pytest.raises(ValueError,match='baseline replay differs'): subject.validate_baseline(ctx,report,panels,1729)


@pytest.mark.parametrize('role',['selected','last-attempt'])
def test_each_negative_control_is_bound_to_previous_predictions(role):
    ctx,report,panels=replay(); panels[role]['context-only-shuffle']['predictions'][0]['token_ids']=[1,7,2]
    with pytest.raises(ValueError,match='control predictions'): subject.validate_baseline(ctx,report,panels,1729)


def test_extra_report_field_is_not_silently_ignored():
    ctx,report,panels=replay(); report['new_authority']=True
    with pytest.raises(ValueError,match='report inventory'): subject.validate_baseline(ctx,report,panels,1729)
