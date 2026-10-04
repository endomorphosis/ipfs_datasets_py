"""Predeclared endpoints and a two-prediction gate before fresh labels."""
from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest
P=Path(__file__).resolve().parents[5]
spec=importlib.util.spec_from_file_location('_fresh_style',P/'scripts/ops/autoencoder/observe_fresh_normative_style.py')
subject=importlib.util.module_from_spec(spec);spec.loader.exec_module(subject)
@pytest.mark.parametrize('key,value',[('dimensions',[8,384,768]),('max_target_tokens',1024),('context_tokens',1024),('temperature',1),
    ('holdout_used_for_selection',True),('models_selected_before_source_generation',False),('greedy_passes_per_model',2),
    ('all_predictions_before_reference_load',False),('vocabulary_size',3),('training_executed',True)])
def test_fixed_recipe_rejects_changes(key,value):
    plan=deepcopy(subject.FIXED);subject.validate_plan(plan);plan[key]=value
    with pytest.raises(ValueError):subject.validate_plan(plan)

def test_endpoints_predeclared_selected_lr001():
    assert subject.ENDPOINTS=={'384':dict(run='384-continue-lr001-1729',role='selected'), '768':dict(run='768-continue-lr001-1729',role='selected')}

@pytest.mark.parametrize('records',[[],[{'dimension':384}],[{'dimension':384},{'dimension':384}]])
def test_reference_gate_rejects_missing_pred_before_open(monkeypatch,records):
    monkeypatch.setattr(subject,'bound_json',lambda *a:pytest.fail('opened fresh labels'))
    with pytest.raises(ValueError,match='both complete'):subject.load_references({},records)

def test_changed_persisted_prediction_rejected_before_labels(tmp_path,monkeypatch):
    file=tmp_path/'prediction.json';file.write_text('{}')
    records=[dict(dimension=d,predictions_ref=dict(path=str(file),sha256='0'*64)) for d in (384,768)]
    monkeypatch.setattr(subject,'bound_json',lambda *a:pytest.fail('opened fresh labels'))
    with pytest.raises(ValueError,match='persisted'):subject.load_references({},records)

def test_unknown_or_changed_input_rejected(tmp_path):
    path=tmp_path/'input.json';path.write_text('{}');manifest={'inputs':{str(path):subject.sha(path)}}
    assert subject.bound_json(manifest,path)=={}
    path.write_text('[]')
    with pytest.raises(ValueError):subject.bound_json(manifest,path)

@pytest.mark.parametrize('dimension',[384,768])
def test_artifact_directory_only_for384(dimension,tmp_path):
    calls=[];producer=SimpleNamespace(produce_width=lambda *a,**k:calls.append(k))
    subject.produce_or_reuse(producer,{},dimension,{str(dimension):{}},tmp_path,{})
    assert calls[0]['source_artifact_directory']==(tmp_path/'source384-artifacts' if dimension==384 else None)
    assert calls[0]['max_seconds']==600 and calls[0]['batch_size']==4

def test_completed384_cache_revalidated_without_forward(monkeypatch,tmp_path):
    report={'complete':True};events=[]
    producer=SimpleNamespace(_plan=lambda p:p,_validate_report=lambda p,r:events.append((p,r)) or 384,
        produce_width=lambda *a,**k:pytest.fail('duplicate384encoder'))
    monkeypatch.setattr(subject,'bound_json',lambda *a:report)
    result=subject.produce_or_reuse(producer,{'plan':1},384,{},tmp_path,{'completed_384_production':{'path':'saved','sha256':'h'}})
    assert result is report and events==[({'plan':1},report)]
