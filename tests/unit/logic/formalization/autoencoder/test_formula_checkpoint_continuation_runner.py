"""Continuation reuses exact source coordinates but starts a fresh optimizer."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

PATH=Path(__file__).resolve().parents[5]/'scripts/ops/autoencoder/benchmark_formula_checkpoint_continuation.py'
SPEC=importlib.util.spec_from_file_location('_formula_continuation_tests',PATH)
subject=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(subject)


def test_fixed_endpoint_roles_and_equal_six_job_budget():
    assert len(subject.jobs())==6 and subject.FIXED['optimizer_steps_per_fit']==170
    assert subject.ENDPOINTS['8']['role']==subject.ENDPOINTS['768']['role']=='last-attempt'
    assert subject.ENDPOINTS['384']==dict(arm='384-aux-used113-1729',role='selected')
    assert subject.FIXED['exact_optimizer_resume'] is False and subject.FIXED['fresh_optimizer']


@pytest.mark.parametrize('key,value',[('optimizer_steps_per_fit',160),('epochs_per_stage',20),('fixed_decoder_output_limit',1024),
    ('fixed_encoder_context_tokens',1024),('temperature',1),('full_vocabulary_size',3),('exact_optimizer_resume',True),
    ('fresh_optimizer',False),('selection_unchanged',False),('auxiliary_sampler','content_matched_cycles'),
    ('boundary_replay_atol',1e-4),('source_value_weight',0.)])
def test_recipe_rejects_unregistered_changes(key,value):
    plan=deepcopy(subject.FIXED);subject.validate_plan(plan);plan[key]=value
    with pytest.raises(ValueError,match='fixed continuation'):subject.validate_plan(plan)


@pytest.mark.parametrize('dimension',[8,384,768])
@pytest.mark.parametrize('arm',subject.ARMS)
def test_each_width_inherits_losses_with_paired_learning_rate_only(dimension,arm):
    calls=[];lane=dict(dimension=dimension,owners={'long_span_source_value_training':SimpleNamespace(train=lambda *a,**k:calls.append((a,k)))},
        rows={'train':['train'],'validation':['dev']},references={'train':['trainlabels'],'validation':['devlabels']},
        donor={'codec':{},'input_transform':{}},lineage={},validate_rule='rule',validator_id='validator',stages=['halved'],source_contexts={},
        modality_banks={'used113':{'bank':'actual384'}})
    subject.train_candidate(lane,'parent',arm);args,kw=calls[0]
    assert args==('parent',['train'],['dev']) and kw['curriculum']==['halved']
    assert kw['config']['learning_rate']==arm['learning_rate'] and kw['config']['max_target_tokens']==512
    assert kw['non_action_learning_rate_multiplier']==10 and kw['generated_boundary_retry_on_mismatch'] is True
    assert kw['source_value_weight']==kw['cardinality_weight']==.25
    assert kw['action_contrastive_weight']==kw['generated_boundary_weight']==.05
    assert 'auxiliary_source_modality_sampler' not in kw
    assert ('auxiliary_source_modality_bank' in kw)==(dimension==384)
    if dimension==384:assert kw['auxiliary_source_modality_bank'] is lane['modality_banks']['used113'] and kw['auxiliary_source_modality_weight']==.05


def test_preparation_reuses_saved_coordinates_and_halves_all_stages(tmp_path,monkeypatch):
    stages=[dict(name=str(i),training_ids=list(range(n)),epochs=20) for i,n in enumerate((12,26,36,48))]
    original=deepcopy(stages);lane=dict(preparation={'saved':1},source_contexts={'saved':2},rows={'saved':3},stages=stages)
    ctx=dict(native_runner=SimpleNamespace(prepare_dimension=lambda c,d:deepcopy(lane)),continuation_manifest={'parent_results':str(tmp_path)})
    lookup={'preprocessing.json':lane['preparation'],'source-contexts.json':lane['source_contexts'],'training-rows.json':lane['rows']}
    monkeypatch.setattr(subject,'bound_json',lambda m,p:deepcopy(lookup[Path(p).name]))
    result=subject.prepare_lane(ctx,8)
    assert stages==original and [s['epochs'] for s in result['stages']]==[10]*4
    assert [s['training_ids'] for s in result['stages']]==[s['training_ids'] for s in original]
    lookup['preprocessing.json']={'different':True}
    with pytest.raises(ValueError,match='preprocessing'):subject.prepare_lane(ctx,8)


def test_state_rejects_claimed_optimizer_resume_before_model_restore(monkeypatch):
    fake=dict(schema='private-native-dimension-source-state/v1',dimension=8,role='last-attempt',recipe={'recipe':1},codec={},
        input_transform={},model_state={},weights_sha256='weights',tensor_sha256='tensors',optimizer_resumable=True,
        qualified=False,admitted=False,proof_authority=False,checkpoint_promoted=False)
    monkeypatch.setattr(subject,'bound_json',lambda *a:fake)
    lane=dict(continuation_manifest={},dimension=8,donor={'codec':{},'input_transform':{}},core=SimpleNamespace(digest=lambda _:'weights'))
    with pytest.raises(ValueError,match='parent state'):subject.restore_model(lane,{'path':'unused','sha256':'file','tensor_sha256':'tensors'},{'recipe':1},'last-attempt')


def test_bound_json_does_not_accept_newer_mutated_parent(tmp_path):
    path=tmp_path/'state.json';path.write_text('{"version":1}')
    manifest={'inputs':{str(path):subject.sha(path)}};assert subject.bound_json(manifest,path)=={'version':1}
    path.write_text('{"version":2}')
    with pytest.raises(ValueError,match='sealed artifact'):subject.bound_json(manifest,path)
