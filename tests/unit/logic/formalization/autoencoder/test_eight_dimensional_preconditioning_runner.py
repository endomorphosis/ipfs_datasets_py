"""One closed8D preconditioning ablation; sources/losses/gates stay fixed."""
from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest
P=Path(__file__).resolve().parents[5]
spec=importlib.util.spec_from_file_location('_eight_preconditioning_runner',P/'scripts/ops/autoencoder/benchmark_eight_dimensional_preconditioning.py')
subject=importlib.util.module_from_spec(spec);spec.loader.exec_module(subject)

@pytest.mark.parametrize('key,value',[('dimensions',[8,384]),('optimizer_steps',340),('preconditioner_condition_cap',64.),('full_vocabulary_size',2),
    ('max_target_tokens',1024),('context_tokens',1024),('temperature',1),('optimizer_groups_unchanged',False),('selection_unchanged',False),
    ('additional_losses',True),('learning_rate',.01),('architecture_changed',True),('preconditioner_fit_split','all'),('identity_exact_baseline_replay',False)])
def test_fixed_recipe_rejects_mutation(key,value):
    plan=deepcopy(subject.FIXED);subject.validate_plan(plan);plan[key]=value
    with pytest.raises(ValueError):subject.validate_plan(plan)


def test_calls_change_only_preconditioner_policy():
    calls=[];lane=dict(owners={'long_span_source_value_training':SimpleNamespace(train=lambda *a,**k:calls.append((a,k)))},
        rows={'train':['train'],'validation':['dev']},references={'train':['trainrefs'],'validation':['devrefs']},
        donor={'codec':{},'input_transform':{}},lineage={},validate_rule='rule',validator_id='validator',stages=['half'],source_contexts={})
    for arm in subject.ARMS:subject.train_candidate(lane,'sameparent',arm)
    left,right=calls;assert left[0]==right[0]
    assert left[1].pop('source_gradient_preconditioning')=='identity'
    assert right[1].pop('source_gradient_preconditioning')=='train_covariance_inverse'
    assert left[1]==right[1]
    assert left[1]['non_action_learning_rate_multiplier']==10. and left[1]['config']['learning_rate']==.001
    assert left[1]['source_value_weight']==left[1]['cardinality_weight']==.25
    assert left[1]['generated_boundary_weight']==left[1]['action_contrastive_weight']==.05
    assert left[1]['generated_boundary_retry_on_mismatch']
