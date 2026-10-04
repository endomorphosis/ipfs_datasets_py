"""Bind three matched generated-replay arms without changing selection or exposure."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

PATH = Path(__file__).resolve().parents[5]/'scripts/ops/autoencoder/benchmark_source_margin_training.py'
SPEC = importlib.util.spec_from_file_location('_source_margin_runner_tests', PATH)
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)


@pytest.mark.parametrize('index,joint,weight', [(0,False,0.),(1,True,0.),(2,True,.01)])
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
    assert kw['generated_source_margin_replay'] is joint
    assert kw['generated_source_margin_weight']==weight
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
        assert [(r['generated_source_margin_replay'],r['generated_source_margin_weight']) for d,s,r in jobs if (d,s)==(dimension,seed)]==[(False,0.),(True,0.),(True,.01)]


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
    assert control.pop('generated_source_margin_weight')==0.
    assert candidate.pop('generated_source_margin_weight')==.01
    assert control==candidate
    assert subject.FIXED['zero_weight_auxiliary_graph_attached'] is False


def margin_fixture(index=1):
    digest=lambda value:json.dumps(value,sort_keys=True,allow_nan=False)
    names=['recurrent.'+str(i) for i in range(11)]
    ctx=dict(core=SimpleNamespace(digest=digest), rows={'train':[{'id':'train'}]},
        references={'train':[{'id':'train','target':{}}]},
        source_contexts={'train':{'train':{'segments':[]}}},donor={'codec':{}},
        owners={'generated_source_margin_training':SimpleNamespace(RECURRENT_PARAMETER_NAMES=names)})
    inventory=dict(validation_rows_used=False,reference_documents_passed_to_model=False,
        source_alignment_inferred=False,fields=subject.FIXED['source_margin_fields'],
        training_rows_sha256=digest(ctx['rows']['train']),
        training_references_sha256=digest(ctx['references']['train']),
        training_contexts_sha256=digest(ctx['source_contexts']['train']),codec_sha256=digest({}))
    receipt=dict(reference_labels_used_only_after_rollout=True,reference_documents_passed_to_model=False,
        target_prefixes_used=False,validation_rows_used=False,generation=dict(source_only=True,
            reference_count_access=False,complete_rollout_before_site_selection=True,rows=[{'id':'train'}]))
    enabled=index==2
    gradient=dict(parameter_names=names,parameter_count=100,backward_executed=enabled,
        unscaled_l2_norm=2. if enabled else 0.,scaled_l2_norm=.02 if enabled else 0.,
        backward_elapsed_seconds=.001 if enabled else 0.,combined_preclip_norm=.5,
        shared_clip_factor=1.,none_gradient_parameter_names=[] if enabled else names)
    report=dict(generated_source_margin_replay=True,generated_source_margin_weight=.01 if enabled else 0.,
        generated_source_margin_objective_enabled=enabled,generated_source_margin_used_for_selection=False,
        generated_source_margin_scheduled_updates=340,generated_source_margin_zero_weight_graph_attached=False,
        generated_source_margin_shared_clip_can_change_other_parameter_updates=True,
        generated_source_margin_gradient_scope='explicit_recurrent_parameters_only_before_shared_global_clip',
        generated_source_margin_inventory=inventory,generated_source_margin_parameter_names=names,
        generated_source_margin_parameter_count=100,generated_source_margin_auxiliary_backward_updates=340 if enabled else 0,
        committed_updates=[dict(decoder_row_ids=['train'],preclip_norm=.5,objective=1.,ordinary_objective=1.,
            generated_source_margin=dict(interval=1,zero_based_committed_step=i,
                receipt=deepcopy(receipt),gradient=deepcopy(gradient))) for i in range(340)])
    return ctx,report,subject.ARMS[index]


@pytest.mark.parametrize('index',[1,2])
def test_margin_report_requires_complete_training_only_execution(index):
    ctx,report,recipe=margin_fixture(index);before=deepcopy(report)
    subject.validate_margin_report(ctx,report,recipe)
    assert report==before


@pytest.mark.parametrize('mutation',[
    lambda r:r.update(generated_source_margin_replay=1),
    lambda r:r.update(generated_source_margin_weight=.01),
    lambda r:r.update(generated_source_margin_used_for_selection=True),
    lambda r:r.update(generated_source_margin_scheduled_updates=339),
    lambda r:r.update(generated_source_margin_zero_weight_graph_attached=True),
    lambda r:r.update(generated_source_margin_shared_clip_can_change_other_parameter_updates=False),
    lambda r:r.update(generated_source_margin_parameter_names=['scalar_head']),
    lambda r:r['generated_source_margin_inventory'].update(training_rows_sha256='stale'),
    lambda r:r['generated_source_margin_inventory'].update(validation_rows_used=True),
    lambda r:r['committed_updates'].pop(),
    lambda r:r['committed_updates'][0]['generated_source_margin'].update(interval=True),
    lambda r:r['committed_updates'][0]['generated_source_margin'].update(zero_based_committed_step=1),
    lambda r:r['committed_updates'][0]['generated_source_margin']['gradient'].update(backward_executed=True),
    lambda r:r['committed_updates'][0]['generated_source_margin']['gradient'].update(scaled_l2_norm=float('nan')),
    lambda r:r['committed_updates'][0]['generated_source_margin']['gradient'].update(shared_clip_factor=.2),
    lambda r:r['committed_updates'][0]['generated_source_margin']['receipt'].update(target_prefixes_used=True),
    lambda r:r['committed_updates'][0]['generated_source_margin']['receipt']['generation'].update(reference_count_access=True),
    lambda r:r['committed_updates'][0]['generated_source_margin']['receipt']['generation'].update(rows=[{'id':'validation'}]),
    lambda r:r.update(generated_source_margin_auxiliary_backward_updates=340),
])
def test_margin_report_rejects_missing_or_contaminated_work(mutation):
    ctx,report,recipe=margin_fixture();mutation(report)
    with pytest.raises(ValueError,match='source-margin'):
        subject.validate_margin_report(ctx,report,recipe)


def test_disabled_baseline_has_no_margin_receipts():
    subject.validate_margin_report({}, {}, subject.ARMS[0])
    with pytest.raises(ValueError,match='baseline'):
        subject.validate_margin_report({}, {'generated_source_margin_weight':0.}, subject.ARMS[0])


def test_baseline_equivalence_keeps_all_numerical_evidence():
    raw={'elapsed_seconds':1., 'selected_weights_sha256':'retained', 'committed_updates':[
        {'generated_boundary':{'elapsed_seconds':2., 'generation':{'elapsed_seconds':3.,'tokens':[1,2]},
         'collection_sha256':'elapsed-dependent','loss':.2}}]}
    got=subject.baseline_comparable(raw)
    assert got=={'selected_weights_sha256':'retained', 'committed_updates':[{'generated_boundary':{
        'generation':{'tokens':[1,2]},'loss':.2}}]}
    assert raw['committed_updates'][0]['generated_boundary']['collection_sha256']=='elapsed-dependent'


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
