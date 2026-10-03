"""Fixed ablation and exact disabled-replay contracts; no checkpoint execution."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[5]
PATH=ROOT/'scripts/ops/autoencoder/benchmark_order_boundary_source_training.py'
spec=importlib.util.spec_from_file_location('_test_order_boundary_benchmark',PATH)
subject=importlib.util.module_from_spec(spec);spec.loader.exec_module(subject)


@pytest.mark.parametrize('key,value',[
 ('representation_dimension',8),('seed_order',[2718]),('arms',[]),('head','independent'),
 ('epochs_per_source_stage',40),('expected_optimizer_steps_per_arm',680),
 ('fixed_encoder_context_tokens',1024),('fixed_decoder_output_limit',1024),('temperature',.1),
 ('batch_size',16),('learning_rate',.01),('max_seconds_per_arm',3600),('order_extra_decoder_presentations',48),
 ('boundary_site_cap_per_row',8),('boundary_site_policy','gold_count'),('full_vocabulary_retained',False),
 ('closure_forced',True),('generation_reference_count_access',True),('native_qualification',True),
 ('baseline_training_replay_required',False),('selection_unchanged',False),('no_downloads',False)])
def test_fixed_plan_rejects_unregistered_changes(key,value):
    plan=deepcopy(subject.FIXED);plan[key]=value
    with pytest.raises(ValueError,match='fixed training recipe'):subject.validate_plan(plan)


def test_plan_declares_all_four_arms_and_boundary_compute_separately():
    subject.validate_plan(dict(subject.FIXED,input_sha256={}))
    assert [(a['order_augmentation'],a['generated_boundary_weight']) for a in subject.ARMS]==[(False,0.),(True,0.),(False,.25),(True,.25)]
    assert subject.FIXED['boundary_extra_computation_reported_separately'] is True
    assert subject.FIXED['order_extra_decoder_presentations']==0
    assert subject.FIXED['verified_cached_embeddings'] is True


def setup_replay():
    fields=['strategy','cardinality_weight','count_exposure','source_value_weight','source_value_head',
        'source_value_presentations','committed_decoder_batch_ids_sha256','committed_updates',
        'count_training_row_presentations','count_training_presentations_by_class','count_mean_loss_exposure_by_class',
        'committed_count_batch_ids_sha256','count_selector_initial','count_selector_final','count_training_inventory_sha256',
        'gradient_norms','curriculum','stage_reports','optimizer_steps','row_presentations','valid_target_token_presentations',
        'optimizer_instance_count','optimizer_reinitialized_between_stages','selected_epoch','selection','baseline','selected',
        'last_complete_attempt','last_complete_attempt_is_selected','history','stopped_reason','initial_weights_sha256',
        'selected_weights_sha256','last_complete_attempt_weights_sha256']
    report={key:{'field':key,'example':1} for key in fields}
    report['config']=dict(max_seconds=180,learning_rate=.001,max_target_tokens=512)
    prior=dict(training=deepcopy(report));prior['training']['config']['max_seconds']=90
    panels={role:{label:{'predictions':[dict(id='sample',token_ids=[4,5],eos_reached=True,generation_status='eos',
        exact_target=False,reconstructed_input=[.1])]} for label,_,_ in subject.CONTROLS} for role in ('selected','last-attempt')}
    prior['postfit']=deepcopy(panels)
    core=SimpleNamespace(digest=lambda value:hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest())
    return report,prior,panels,core


def test_only_wall_headroom_differs_in_disabled_replay():
    args=setup_replay();result=subject.validate_baseline(*args)
    assert result['complete'] and result['all_tensors_and_predictions_equal']
    assert result['current_timeout_seconds']==180 and not result['timing_equality_claimed']


@pytest.mark.parametrize('field',['last_complete_attempt_weights_sha256','selected_weights_sha256','committed_updates',
    'history','stage_reports','gradient_norms','count_selector_final','source_value_presentations'])
def test_replay_detects_trajectory_or_state_changes(field):
    report,prior,panels,core=setup_replay();report[field]={'changed':True}
    with pytest.raises(ValueError,match='baseline replay differs'):subject.validate_baseline(report,prior,panels,core)


@pytest.mark.parametrize('role,label',[(role,label) for role in ('selected','last-attempt') for label,_,_ in subject.CONTROLS])
def test_replay_checks_every_full_prediction_envelope(role,label):
    report,prior,panels,core=setup_replay();panels[role][label]['predictions'][0]['reconstructed_input']=[.2]
    with pytest.raises(ValueError,match='source-control predictions differ'):subject.validate_baseline(report,prior,panels,core)


def test_replay_rejects_optimizer_change_even_if_outputs_match():
    report,prior,panels,core=setup_replay();report['config']['learning_rate']=.02
    with pytest.raises(ValueError,match='optimizer config differs'):subject.validate_baseline(report,prior,panels,core)


def test_helper_hash_precedes_code_execution(tmp_path):
    p=tmp_path/'unsafe.py';p.write_text("raise RuntimeError('must not execute')")
    with pytest.raises(ValueError,match='frozen helper differs'):
        subject.load_helper(tmp_path,{'unsafe.py':'bad'},'unsafe.py','_unsafe_training_helper')
