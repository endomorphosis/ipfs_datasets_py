"""Four-fit architecture isolation and typed state restoration; no trained models."""
from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest

ROOT=Path(__file__).resolve().parents[5]
PATH=ROOT/'scripts/ops/autoencoder/benchmark_multiplicative_source_training.py'
spec=importlib.util.spec_from_file_location('_test_multiplicative_benchmark',PATH)
subject=importlib.util.module_from_spec(spec);spec.loader.exec_module(subject)


def test_registered_comparison_changes_only_interaction():
    subject.validate_plan(dict(subject.FIXED,input_sha256={}))
    assert subject.FIXED['seed_order']==[1729,2718]
    assert [r['slot_interaction'] for r in subject.ARMS]==['additive','additive_multiplicative']
    assert all(not r['order_augmentation'] and r['generated_boundary_weight']==0. for r in subject.ARMS)
    assert subject.FIXED['trainable_parameter_count_unchanged']
    assert subject.FIXED['baseline_training_replay_required']
    assert subject.FIXED['expected_optimizer_steps_per_arm']==340


@pytest.mark.parametrize('key,value',[
    ('arms',[]),('seed_order',[1729]),('candidate_hidden_formula','tanh(source+slot)'),
    ('trainable_parameter_count_unchanged',False),('generated_boundary_loss_enabled',True),
    ('order_augmentation_enabled',True),('fixed_encoder_context_tokens',1024),
    ('fixed_decoder_output_limit',1024),('temperature',.1),('selection_unchanged',False),
    ('production_promotion_allowed',True),('baseline_training_replay_required',False),
    ('expected_optimizer_steps_per_arm',680),('original_training_rows',108)])
def test_plan_rejects_confounded_or_relaxed_experiment(key,value):
    plan=deepcopy(subject.FIXED);plan[key]=value
    with pytest.raises(ValueError,match='fixed training recipe'):subject.validate_plan(plan)


def setup_state():
    torch=pytest.importorskip('torch')
    template={'weight':torch.tensor([.5]),'head_initialization_seed':torch.tensor(1729),
        'slot_interaction_version':torch.tensor(1)}
    state={k:t.tolist() for k,t in template.items()}
    ctx={'numerical':SimpleNamespace(_tensor=lambda values,template,name:torch.tensor(values,dtype=template.dtype))}
    return torch,ctx,state,template


def test_typed_state_preserves_architecture_and_seed_buffers():
    torch,ctx,state,template=setup_state();restored=subject.restored_tensors(ctx,state,template)
    assert all(torch.equal(v,restored[k]) and v.dtype==restored[k].dtype for k,v in template.items())


@pytest.mark.parametrize('key,value',[('head_initialization_seed',1729.),('head_initialization_seed',2718),
    ('slot_interaction_version',True),('slot_interaction_version',2),('slot_interaction_version',1.)])
def test_restoration_rejects_changed_or_coerced_architecture(key,value):
    _,ctx,state,template=setup_state();state[key]=value
    with pytest.raises(ValueError,match='integer architecture'):subject.restored_tensors(ctx,state,template)


def test_restoration_rejects_unregistered_or_missing_buffers():
    torch,ctx,state,template=setup_state()
    with pytest.raises(ValueError,match='inventory'):
        subject.restored_tensors(ctx,{k:v for k,v in state.items() if k!='slot_interaction_version'},template)
    state['unknown']=1;template['unknown']=torch.tensor(1)
    with pytest.raises(ValueError,match='integer architecture'):
        subject.restored_tensors(ctx,state,template)


def test_candidate_binding_dispatches_only_declared_recipe():
    seen=[]
    ctx={'prior':SimpleNamespace(fresh_base=lambda *args:'base'),
         'owners':{'shared_slot_source_decoder_experiment':SimpleNamespace(
             bind_shared_slot_source_model=lambda *args,**kw:seen.append((args,kw)))}}
    subject.bind_candidate(ctx,subject.ARMS[1],1729)
    assert seen==[(('base',),dict(head_seed=1729,hidden_width=64,slot_interaction='additive_multiplicative'))]
    with pytest.raises(ValueError,match='unplanned'):subject.bind_candidate(ctx,dict(subject.ARMS[1],name='other'),1729)
