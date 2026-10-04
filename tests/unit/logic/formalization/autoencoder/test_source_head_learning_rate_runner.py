"""Bind the measured head intervention without changing baseline objectives."""
from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

PATH = Path(__file__).resolve().parents[5]/'scripts/ops/autoencoder/benchmark_source_head_learning_rate.py'
SPEC = importlib.util.spec_from_file_location('_source_head_lr_runner_tests', PATH)
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)


@pytest.mark.parametrize('index,multiplier', [(0,1.),(1,10.)])
def test_intervention_reaches_only_explicit_trainer_knob(index,multiplier):
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
    assert kw['non_action_learning_rate_multiplier']==multiplier
    assert kw['generated_field_weight']==0 and kw['generated_site_interval']==1
    assert kw['generated_boundary_weight']==.05 and kw['action_contrastive_weight']==.05
    assert kw['source_value_weight']==kw['cardinality_weight']==.25
    assert kw['config']['learning_rate']==.001
    assert kw['config']['max_target_tokens']==512 and kw['config']['max_seconds']==180
    assert kw['config']['alpha']==0.


def test_all_widths_and_seeds_have_both_fresh_recipes():
    jobs=subject.jobs()
    assert len(jobs)==12
    assert {(dim,seed) for dim,seed,_ in jobs}=={(d,s) for d in (8,384,768) for s in (1729,2718)}
    for dimension,seed in {(d,s) for d,s,_ in jobs}:
        assert [r['non_action_learning_rate_multiplier'] for d,s,r in jobs if (d,s)==(dimension,seed)]==[1.,10.]


@pytest.mark.parametrize('key,value',[('temperature',1),('fit_count',18),('dimensions',[8]),
    ('selection_unchanged',False),('production_promotion_allowed',True),('full_vocabulary_retained',False),
    ('fixed_encoder_context_tokens',1024),('expected_optimizer_steps_per_arm',1000)])
def test_recipe_cannot_silently_change_success_or_exposure(key,value):
    plan=deepcopy(subject.FIXED)
    subject.validate_plan(plan)
    plan[key]=value
    with pytest.raises(ValueError):subject.validate_plan(plan)
