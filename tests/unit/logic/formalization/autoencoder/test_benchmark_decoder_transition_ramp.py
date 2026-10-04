"""Admission controls for the paired transition intervention."""
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[5]

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value

subject=module('_ramp_benchmark_tests',ROOT/'scripts/ops/autoencoder/benchmark_decoder_transition_ramp.py')
trace=module('_ramp_trace_tests',ROOT/'scripts/ops/autoencoder/benchmark_decoder_gradient_trace.py')
exposure=module('_ramp_exposure_tests',ROOT/'scripts/ops/autoencoder/benchmark_decoder_count_exposure.py')


def recipe():
    return dict(schema='decoder-transition-ramp-plan/v1',representation_dimension=384,
        arms=[dict(name='unchanged',transition_schedule='unchanged',count_exposure='balanced_all',guide_boundary=False,cardinality_weight=.25),
              dict(name='ramp20',transition_schedule='first_expansion_ramp20',count_exposure='balanced_all',guide_boundary=False,cardinality_weight=.25)],
        transition_policy=dict(trigger='first_strict_training_id_superset',committed_updates=20,start_factor=.1,end_factor=1.,
            interpolation='linear_inclusive_endpoints',preserve_optimizer_state=True,scheduler_uses_base_learning_rate=True),
        seed_order=[1729,2718],conditioning='every_step',loss='semantic_fields',epochs_per_source_stage=20,
        expected_optimizer_steps_per_arm=340,expected_training_token_presentations_per_arm=225840,
        expected_count_presentations_per_arm=2440,batch_size=8,learning_rate=.001,max_seconds_per_arm=60,
        validation_interval=4,fixed_encoder_context_tokens=512,fixed_decoder_output_limit=512,projection_frozen=True,
        teacher_distillation_used=False,selection_unchanged=True,no_downloads=True,generation_reference_count_access=False,
        native_qualification=False,gradient_trace=dict(enabled=True,threshold=50.0,top_k=2,module_summaries=True),
        event_replay_seconds=30,event_replay_memory_bytes=536870912)


def test_paired_recipe_preserves_plan_and_prior_budgets():
    plan=recipe();before=deepcopy(plan)
    subject.validate_plan(plan,trace,exposure)
    assert plan==before
    assert subject.FALSE['qualified'] is False and subject.FALSE['lake_executed'] is False


@pytest.mark.parametrize('key,value',[
    ('schema','decoder-gradient-trace-plan/v1'),('representation_dimension',768),('learning_rate',.002),
    ('fixed_encoder_context_tokens',1024),('fixed_decoder_output_limit',1024),('seed_order',[1729]),
    ('projection_frozen',False),('native_qualification',True),('selection_unchanged',False),
    ('no_downloads',False),('generation_reference_count_access',True),('expected_count_presentations_per_arm',0),
    ('event_replay_seconds',31),('event_replay_seconds',True),('event_replay_seconds',float('nan')),
    ('event_replay_memory_bytes',1073741824),('event_replay_memory_bytes',False),
])
def test_rejects_budget_or_authority_drift(key,value):
    plan=recipe();plan[key]=value
    with pytest.raises(ValueError):subject.validate_plan(plan,trace,exposure)


@pytest.mark.parametrize('key,value',[
    ('trigger','every_stage'),('committed_updates',19),('committed_updates',True),('start_factor',0.),
    ('end_factor',2.),('interpolation','cosine'),('preserve_optimizer_state',False),
    ('scheduler_uses_base_learning_rate',False),('extra_tuning',True),
])
def test_transition_recipe_cannot_silently_change(key,value):
    plan=recipe();plan['transition_policy'][key]=value
    with pytest.raises(ValueError):subject.validate_plan(plan,trace,exposure)


@pytest.mark.parametrize('arm,key,value',[
    (0,'transition_schedule','first_expansion_ramp20'),(1,'transition_schedule','unchanged'),
    (0,'count_exposure','current_stage'),(1,'guide_boundary',True),(1,'cardinality_weight',0.),
])
def test_single_intervention_pair_remains_explicit(arm,key,value):
    plan=recipe();plan['arms'][arm][key]=value
    with pytest.raises(ValueError):subject.validate_plan(plan,trace,exposure)


@pytest.mark.parametrize('key,value',[
    ('enabled',False),('top_k',3),('top_k',True),('threshold',49.0),('threshold',float('inf')),
    ('module_summaries',False),('unexpected',1),
])
def test_previous_capture_controls_remain_required(key,value):
    plan=recipe();plan['gradient_trace'][key]=value
    with pytest.raises(ValueError):subject.validate_plan(plan,trace,exposure)


def test_trace_helper_digest_checked_before_import(tmp_path):
    relative='scripts/ops/autoencoder/benchmark_decoder_gradient_trace.py';path=tmp_path/relative
    path.parent.mkdir(parents=True);path.write_text('raise AssertionError("must not import")\n')
    with pytest.raises(ValueError,match='frozen gradient'):
        subject.load_trace_helper(tmp_path,{relative:'0'*64})


def test_imports_exact_pinned_trace_helper(tmp_path):
    relative='scripts/ops/autoencoder/benchmark_decoder_gradient_trace.py';path=tmp_path/relative
    path.parent.mkdir(parents=True);content=b'identity = "pinned"\n';path.write_bytes(content)
    helper=subject.load_trace_helper(tmp_path,{relative:hashlib.sha256(content).hexdigest()})
    assert helper.identity=='pinned'
