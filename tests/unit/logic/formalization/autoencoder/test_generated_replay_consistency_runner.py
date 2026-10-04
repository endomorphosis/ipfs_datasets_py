"""Bind three matched generated-replay arms without changing selection or exposure."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

PATH = Path(__file__).resolve().parents[5]/'scripts/ops/autoencoder/benchmark_generated_replay_consistency.py'
SPEC = importlib.util.spec_from_file_location('_joint_generated_replay_runner_tests', PATH)
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)


@pytest.mark.parametrize('index,joint,weight', [(0,False,0.),(1,True,0.),(2,True,.05)])
def test_intervention_reaches_only_explicit_trainer_knob(index,joint,weight):
    calls=[]
    def train(*args,**kwargs):
        calls.append((args,kwargs));return 'private-result'
    ctx=dict(owners={'long_span_source_value_training':SimpleNamespace(train=train)},
        rows={'train':['training'], 'validation':['development']},
        references={'train':{'t':1},'validation':{'v':2}},
        donor={'codec':{},'input_transform':{}},lineage={},validate_rule=object(),
        validator_id='test',stages=[],source_contexts={})
    assert subject.train_candidate(ctx,'model',1729,deepcopy(subject.ARMS[index]))=='private-result'
    args,kw=calls[0]
    assert args==('model',['training'],['development'])
    assert kw['non_action_learning_rate_multiplier']==10.
    assert kw['joint_generated_replay'] is joint
    assert kw['generated_field_weight']==weight and kw['generated_site_interval']==1
    assert kw['generated_boundary_weight']==.05 and kw['action_contrastive_weight']==.05
    assert kw['source_value_weight']==kw['cardinality_weight']==.25
    assert kw['config']['learning_rate']==.001
    assert kw['config']['max_target_tokens']==512 and kw['config']['max_seconds']==180
    assert kw['config']['alpha']==0.


def test_all_widths_and_seeds_have_three_fresh_recipes():
    jobs=subject.jobs()
    assert len(jobs)==18
    assert {(dim,seed) for dim,seed,_ in jobs}=={(d,s) for d in (8,384,768) for s in (1729,2718)}
    for dimension,seed in {(d,s) for d,s,_ in jobs}:
        assert [(r['joint_generated_replay'],r['generated_field_weight']) for d,s,r in jobs if (d,s)==(dimension,seed)]==[(False,0.),(True,0.),(True,.05)]


@pytest.mark.parametrize('key,value',[('temperature',1),('fit_count',12),('dimensions',[8]),
    ('selection_unchanged',False),('production_promotion_allowed',True),('full_vocabulary_retained',False),
    ('fixed_encoder_context_tokens',1024),('expected_optimizer_steps_per_arm',1000)])
def test_recipe_cannot_silently_change_success_or_exposure(key,value):
    plan=deepcopy(subject.FIXED)
    subject.validate_plan(plan)
    plan[key]=value
    with pytest.raises(ValueError):subject.validate_plan(plan)


def test_zero_control_changes_only_field_coefficient_from_intervention():
    control,candidate=deepcopy(subject.ARMS[1:])
    control.pop('name');candidate.pop('name')
    assert control.pop('generated_field_weight')==0.
    assert candidate.pop('generated_field_weight')==.05
    assert control==candidate
    assert subject.FIXED['zero_weight_field_graph_attached'] is False


def test_baseline_equivalence_keeps_all_numerical_evidence():
    raw={'elapsed_seconds':1., 'selected_weights_sha256':'retained', 'committed_updates':[
        {'generated_boundary':{'elapsed_seconds':2., 'generation':{'elapsed_seconds':3.,'tokens':[1,2]},
         'collection_sha256':'elapsed-dependent','loss':.2}}]}
    got=subject.baseline_comparable(raw)
    assert got=={'selected_weights_sha256':'retained', 'committed_updates':[{'generated_boundary':{
        'generation':{'tokens':[1,2]},'loss':.2}}]}
    assert raw['committed_updates'][0]['generated_boundary']['collection_sha256']=='elapsed-dependent'


def joint_report(index=1):
    digest=lambda value:json.dumps(value,sort_keys=True,allow_nan=False)
    ctx=dict(core=SimpleNamespace(digest=digest), rows={'train':[{'id':'train'}]},
        references={'train':[{'id':'train','target':{}}]},
        source_contexts={'train':{'train':{'segments':[]}}}, donor={'codec':{'vocabulary':[]}})
    recipe=deepcopy(subject.ARMS[index])
    inventory=dict(validation_rows_used=False,reference_documents_passed_to_model=False,
        source_alignment_inferred=False,fields=deepcopy(subject.FIXED['generated_field_names']),rows={'train':{}},
        training_rows_sha256=digest(ctx['rows']['train']),
        training_references_sha256=digest(ctx['references']['train']),
        training_contexts_sha256=digest(ctx['source_contexts']['train']),codec_sha256=digest(ctx['donor']['codec']))
    receipt=dict(reference_labels_used_only_after_rollout=True,reference_documents_passed_to_model=False,
        target_prefixes_used=False,validation_rows_used=False,full_vocabulary_cross_entropy=True,
        field=dict(fields=deepcopy(subject.FIXED['generated_field_names']),selection_policy=subject.FIXED['generated_field_policy'],
            full_vocabulary_cross_entropy=True,selected_sites=1,mean_loss=.25),
        generation=dict(source_only=True,reference_count_access=False,complete_rollout_before_site_selection=True,
            rows=[{'id':'train'}]))
    report=dict(joint_generated_replay=True,generated_field_objective_enabled=index==2,
        generated_field_diagnostic_only=index==1,generated_field_weight=recipe['generated_field_weight'],
        generated_site_interval=1,generated_site_scheduled_updates=340,generated_site_skipped_updates=0,
        generated_site_joint_replay=True,generated_field_used_for_selection=False,
        generated_field_policy=subject.FIXED['generated_field_policy'],generated_field_inventory=inventory,
        committed_updates=[dict(decoder_row_ids=['train'],generated_sites=dict(scheduled=True,interval=1,
            zero_based_committed_step=i,skip_reason=None,receipt=deepcopy(receipt))) for i in range(340)])
    return ctx,report,recipe


@pytest.mark.parametrize('index',[1,2])
def test_joint_report_checks_actual_execution_without_mutating_receipts(index):
    ctx,report,recipe=joint_report(index)
    before=deepcopy(report)
    subject.validate_joint_report(ctx,report,recipe)
    assert report==before
    for update in report['committed_updates']:
        update['generated_sites']['receipt']['field'].update(selected_sites=0,mean_loss=None)
    subject.validate_joint_report(ctx,report,recipe)


@pytest.mark.parametrize('field,value',[
    ('joint_generated_replay',False),('joint_generated_replay',1),
    ('generated_field_objective_enabled',0),('generated_field_objective_enabled',True),
    ('generated_field_diagnostic_only',1),('generated_field_diagnostic_only',False),
    ('generated_field_weight',.05),('generated_field_weight',False),
    ('generated_site_interval',True),('generated_site_interval',2),
    ('generated_site_scheduled_updates',339),('generated_site_skipped_updates',False),
    ('generated_site_skipped_updates',1),('generated_site_joint_replay',False),
    ('generated_field_used_for_selection',True),('generated_field_policy','first_wrong_action')])
def test_joint_report_refuses_missing_or_changed_objective_and_cadence(field,value):
    ctx,report,recipe=joint_report();report[field]=value
    with pytest.raises(ValueError,match='objective flags or cadence'):
        subject.validate_joint_report(ctx,report,recipe)
    del report[field]
    with pytest.raises(ValueError,match='objective flags or cadence'):
        subject.validate_joint_report(ctx,report,recipe)


@pytest.mark.parametrize('field,value',[
    ('validation_rows_used',True),('reference_documents_passed_to_model',0),
    ('source_alignment_inferred',True),('fields',['action']),('rows',{'validation':{}}),
    ('training_rows_sha256','stale'),('training_references_sha256','stale'),
    ('training_contexts_sha256','stale'),('codec_sha256','stale')])
def test_joint_report_refuses_unbound_or_nontraining_inventory(field,value):
    ctx,report,recipe=joint_report();report['generated_field_inventory'][field]=value
    with pytest.raises(ValueError,match='inventory'):
        subject.validate_joint_report(ctx,report,recipe)


@pytest.mark.parametrize('mutation',[
    lambda r:r['committed_updates'].pop(),
    lambda r:r['committed_updates'][0]['generated_sites'].update(scheduled=1),
    lambda r:r['committed_updates'][0]['generated_sites'].update(interval=2),
    lambda r:r['committed_updates'][1]['generated_sites'].update(zero_based_committed_step=0),
    lambda r:r['committed_updates'][0]['generated_sites'].update(skip_reason='skipped'),
    lambda r:r['committed_updates'][0]['generated_sites'].update(receipt=None),
    lambda r:r['committed_updates'][0]['generated_sites']['receipt'].update(validation_rows_used=True),
    lambda r:r['committed_updates'][0]['generated_sites']['receipt'].update(target_prefixes_used=True),
    lambda r:r['committed_updates'][0]['generated_sites']['receipt'].update(full_vocabulary_cross_entropy=False),
    lambda r:r['committed_updates'][0]['generated_sites']['receipt']['field'].update(selected_sites=True),
    lambda r:r['committed_updates'][0]['generated_sites']['receipt']['field'].update(mean_loss=None),
    lambda r:r['committed_updates'][0]['generated_sites']['receipt']['field'].update(mean_loss=float('nan')),
    lambda r:r['committed_updates'][0]['generated_sites']['receipt']['generation'].update(reference_count_access=True),
    lambda r:r['committed_updates'][0]['generated_sites']['receipt']['generation'].update(source_only=False),
    lambda r:r['committed_updates'][0]['generated_sites']['receipt']['generation'].update(inventory_access=True),
    lambda r:r['committed_updates'][0]['generated_sites']['receipt']['generation'].update(rows=[{'id':'validation'}]),
    lambda r:r['committed_updates'][0].update(decoder_row_ids=['validation']),
])
def test_joint_report_refuses_missing_or_contaminated_per_update_evidence(mutation):
    ctx,report,recipe=joint_report();mutation(report)
    with pytest.raises(ValueError,match='joint'):
        subject.validate_joint_report(ctx,report,recipe)


def test_original_baseline_report_does_not_require_joint_telemetry():
    subject.validate_joint_report({}, {}, subject.ARMS[0])


def baseline_fixture():
    digest=lambda value:json.dumps(value,sort_keys=True,allow_nan=False)
    report=dict(elapsed_seconds=1.,selected_weights_sha256='weights',token_ce=.25,
        committed_updates=[dict(objective=.5,generated_boundary=dict(elapsed_seconds=2.,
            collection_sha256='time-dependent',generation=dict(elapsed_seconds=3.,rows=[dict(id='train',
                consumed_prefix=[1,3],available_sites=[dict(position=1,actual_next_token_id=4,collection_logits=[.1,.3])])]),
            mean_loss=.4,events=[dict(target_token_id=3,cross_entropy=.4)]))])
    panels={role:{label:{'predictions':[{'id':'validation','token_ids':[3,4]}]}
        for label in [*[row[0] for row in subject.CONTROLS],'recurrent-residual-off']}
        for role in ('selected','last-attempt')}
    ctx=dict(dimension=8,core=SimpleNamespace(digest=digest),baseline_runs={
        '8-source-head-lr10-1729':dict(training=deepcopy(report),postfit=deepcopy(panels))})
    return ctx,report,panels


def test_baseline_replay_ignores_only_registered_time_paths():
    ctx,report,panels=baseline_fixture();report['elapsed_seconds']=99.
    boundary=report['committed_updates'][0]['generated_boundary']
    boundary['elapsed_seconds']=100.;boundary['generation']['elapsed_seconds']=101.
    boundary['collection_sha256']='new-time-dependent-digest'
    assert subject.validate_baseline(ctx,report,panels,1729)['complete']


@pytest.mark.parametrize('mutation',[
    lambda r:r.update(token_ce=.5),
    lambda r:r.update(selected_weights_sha256='different'),
    lambda r:r['committed_updates'][0].update(objective=.6),
    lambda r:r['committed_updates'][0]['generated_boundary'].update(mean_loss=.8),
    lambda r:r['committed_updates'][0]['generated_boundary']['events'][0].update(target_token_id=4),
    lambda r:r['committed_updates'][0]['generated_boundary']['generation']['rows'][0].update(consumed_prefix=[1,4]),
    lambda r:r['committed_updates'][0]['generated_boundary']['generation']['rows'][0]['available_sites'][0].update(actual_next_token_id=3),
    lambda r:r['committed_updates'][0]['generated_boundary']['generation']['rows'][0]['available_sites'][0].update(collection_logits=[.4,.1]),
])
def test_baseline_replay_refuses_numerical_or_generated_decision_tampering(mutation):
    ctx,report,panels=baseline_fixture();mutation(report)
    with pytest.raises(ValueError,match='numerical report replay differs'):
        subject.validate_baseline(ctx,report,panels,1729)


@pytest.mark.parametrize('role',['selected','last-attempt'])
def test_baseline_replay_refuses_residual_off_prediction_changes(role):
    ctx,report,panels=baseline_fixture()
    panels[role]['recurrent-residual-off']['predictions'][0]['token_ids']=[3,5]
    with pytest.raises(ValueError,match='control predictions differ'):
        subject.validate_baseline(ctx,report,panels,1729)
