"""One preregistered parent and matched fields, work and checkpoints."""
from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest
P=Path(__file__).resolve().parents[5]
spec=importlib.util.spec_from_file_location('_object_auxiliary_runner',P/'scripts/ops/autoencoder/benchmark_object_auxiliary_continuation.py')
subject=importlib.util.module_from_spec(spec);spec.loader.exec_module(subject)

@pytest.mark.parametrize('key,value',[('dimensions',[8,384]),('optimizer_steps',340),('full_vocabulary_size',2),('max_target_tokens',1024),
    ('context_tokens',1024),('temperature',1),('same_auxiliary_source_indices',False),('auxiliary_used_for_selection',True),
    ('additional_training_labels',True),('learning_rate',.01),('replay_atol',1e-4),('architecture_changed',True)])
def test_fixed_recipe_cannot_silently_change(key,value):
    plan=deepcopy(subject.FIXED);subject.validate_plan(plan);plan[key]=value
    with pytest.raises(ValueError):subject.validate_plan(plan)

@pytest.mark.parametrize('arm',subject.ARMS)
def test_only_auxiliary_field_changes(arm):
    calls=[];lane=dict(owners={'long_span_source_value_training':SimpleNamespace(train=lambda *a,**k:calls.append((a,k)))},
        rows={'train':['train'],'validation':['dev']},references={'train':['trainrefs'],'validation':['devrefs']},
        donor={'codec':{},'input_transform':{}},lineage={},validate_rule='rule',validator_id='validator',stages=['half'],source_contexts={},auxiliary_bank={'only113':True})
    subject.train_candidate(lane,'sameparent',arm);args,k=calls[0]
    assert args==('sameparent',['train'],['dev']) and k['config']['learning_rate']==.001
    assert k['curriculum']==['half'] and k['config']['max_target_tokens']==512
    assert k['generated_boundary_retry_on_mismatch'] and k['non_action_learning_rate_multiplier']==10.
    assert k['source_value_weight']==k['cardinality_weight']==.25 and k['action_contrastive_weight']==k['generated_boundary_weight']==.05
    for field in ('modality','object'):
        assert ('auxiliary_source_'+field+'_bank' in k)==(arm['field']==field)
        if arm['field']==field:assert k['auxiliary_source_'+field+'_bank'] is lane['auxiliary_bank'] and k['auxiliary_source_'+field+'_weight']==.05
    assert 'auxiliary_source_modality_sampler' not in k

def test_bound_inputs_fail_on_unbound_or_changed_bytes(tmp_path):
    path=tmp_path/'source.json';path.write_text('{"source":1}')
    manifest={'inputs':{str(path):subject.sha(path)}};assert subject.bound_json(manifest,path)=={'source':1}
    with pytest.raises(ValueError):subject.bound_json({'inputs':{}},path)
    path.write_text('{"source":2}')
    with pytest.raises(ValueError):subject.bound_json(manifest,path)

def test_source_inventory_only_accepts_sealed_paths(tmp_path,monkeypatch):
    path=tmp_path/'test.py';path.write_text('pass\n');expected=subject.sha(path)
    monkeypatch.setattr(subject,'package_inventory',lambda:{str(path):expected})
    ctx={'object_old_inventory':{},'object_manifest':{'extensions':{'test.py':expected}}}
    assert subject.source_inventory(SimpleNamespace(extension_root=tmp_path),ctx)=={str(path):expected}
    ctx['object_manifest']['extensions']['test.py']='0'*64
    with pytest.raises(ValueError):subject.source_inventory(SimpleNamespace(extension_root=tmp_path),ctx)
