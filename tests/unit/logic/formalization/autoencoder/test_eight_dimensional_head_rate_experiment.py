"""The8D rate ablation changes one factor and preserves source/gate boundaries."""
from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest
P=Path(__file__).resolve().parents[5]
def load(relative,name):
    spec=importlib.util.spec_from_file_location(name,P/relative);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
helper=load('ipfs_datasets_py/logic/formalization/autoencoder/eight_dimensional_head_rate_experiment.py','_head_rate_helper')
runner=load('scripts/ops/autoencoder/benchmark_eight_dimensional_head_rate.py','_head_rate_runner')

def fixture():
    contexts={split:{'row':{'segments':[{'source_text':split,'vector':[float(split=='train')]+[0.]*7}]}} for split in ('train','validation')}
    state={'clause_source_mean':[0.]*8,'clause_source_scale':1.,'non_action_head.source_projection.weight':[[1.]+[0.]*7 for _ in range(64)],'non_action_head.source_projection.bias':[0.]*64}
    return contexts,state


def test_saved_geometry_does_not_mutate_inputs_or_fit():
    contexts,state=fixture();before=deepcopy((contexts,state));value=helper.diagnose_source_geometry(contexts,state)
    assert (contexts,state)==before
    assert value['splits']['train']['unique_vectors']==1 and value['splits']['train']['activation_count']==64
    assert value['cross_split_exact_vector_collisions']==[] and not value['normalization_refitted']
    assert not value['qualified'] and not value['admitted'] and not value['training_executed']


def test_exact_collisions_and_saturation_are_visible():
    contexts,state=fixture();contexts['validation']['row']['segments'][0]['vector']=[1.]+[0.]*7
    contexts['train']['row']['segments'].append({'source_text':'different','vector':[1.]+[0.]*7})
    state['non_action_head.source_projection.bias']=[10.]*64
    value=helper.diagnose_source_geometry(contexts,state)
    assert value['splits']['train']['colliding_source_groups']==[['train','different']]
    assert len(value['cross_split_exact_vector_collisions'])==2
    assert value['splits']['train']['tanh_abs_at_least_point99']==128


@pytest.mark.parametrize('bad',[0.,-1.,float('nan'),float('inf'),True])
def test_bad_normalization_fails(bad):
    contexts,state=fixture();state['clause_source_scale']=bad
    with pytest.raises(ValueError):helper.diagnose_source_geometry(contexts,state)


@pytest.mark.parametrize('width',[7,9,384])
def test_vectors_cannot_change_width(width):
    contexts,state=fixture();contexts['train']['row']['segments'][0]['vector']=[0.]*width
    with pytest.raises(ValueError):helper.diagnose_source_geometry(contexts,state)


def test_source_conflict_fails():
    contexts,state=fixture();contexts['train']['row']['segments'].append({'source_text':'train','vector':[2.]+[0.]*7})
    with pytest.raises(ValueError):helper.diagnose_source_geometry(contexts,state)


@pytest.mark.parametrize('arm',helper.ARMS)
def test_registered_arm_has_two_group_multiplier(arm):
    assert helper.multiplier(arm)>1


@pytest.mark.parametrize('bad',[None,{},dict(name='head-rate2-candidate',non_action_learning_rate_multiplier=2),dict(name='head-rate1',non_action_learning_rate_multiplier=1.)])
def test_unregistered_arm_fails(bad):
    with pytest.raises(ValueError):helper.multiplier(bad)


@pytest.mark.parametrize('key,value',[('dimensions',[8,384]),('optimizer_steps',340),('full_vocabulary_size',2),('max_target_tokens',1024),
    ('context_tokens',1024),('temperature',1),('optimizer_groups_unchanged',False),('selection_unchanged',False),
    ('additional_losses',True),('learning_rate',.01),('architecture_changed',True)])
def test_fixed_recipe_cannot_silently_change(key,value):
    plan=deepcopy(runner.FIXED);runner.validate_plan(plan);plan[key]=value
    with pytest.raises(ValueError):runner.validate_plan(plan)


def test_training_calls_differ_only_by_head_rate():
    calls=[];lane=dict(owners={'long_span_source_value_training':SimpleNamespace(train=lambda *a,**k:calls.append((a,k)))},
        rows={'train':['train'],'validation':['dev']},references={'train':['trainrefs'],'validation':['devrefs']},
        donor={'codec':{},'input_transform':{}},lineage={},validate_rule='rule',validator_id='validator',stages=['half'],source_contexts={})
    for arm in runner.ARMS:runner.train_candidate(lane,'sameparent',arm)
    first,second=calls
    assert first[0]==second[0]==('sameparent',['train'],['dev'])
    assert first[1].pop('non_action_learning_rate_multiplier')==10.
    assert second[1].pop('non_action_learning_rate_multiplier')==2.
    assert first[1]==second[1]
    k=first[1];assert k['config']['learning_rate']==.001 and k['config']['max_target_tokens']==512
    assert k['generated_boundary_retry_on_mismatch'] and k['source_value_weight']==k['cardinality_weight']==.25
    assert k['action_contrastive_weight']==k['generated_boundary_weight']==.05
    assert not any(key.startswith('auxiliary_source_') for key in k)


def test_bound_inputs_fail_on_unbound_or_changed_bytes(tmp_path):
    path=tmp_path/'source.json';path.write_text('{"source":1}');manifest={'inputs':{str(path):runner.sha(path)}}
    assert runner.bound_json(manifest,path)=={'source':1}
    with pytest.raises(ValueError):runner.bound_json({'inputs':{}},path)
    path.write_text('{"source":2}')
    with pytest.raises(ValueError):runner.bound_json(manifest,path)
