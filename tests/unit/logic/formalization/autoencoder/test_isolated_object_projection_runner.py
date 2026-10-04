"""Fixed paired recipe and saved baseline checks; no native assets or corpus fits."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import pytest

P=Path(__file__).resolve().parents[5]
spec=importlib.util.spec_from_file_location('isolated_runner_test',P/'scripts/ops/autoencoder/benchmark_isolated_object_projection.py')
subject=importlib.util.module_from_spec(spec);spec.loader.exec_module(subject)


def test_two_arms_keep_original_work_and_no_authority():
    subject.validate_plan(deepcopy(subject.FIXED))
    assert subject.FIXED['optimizer_steps']==340 and subject.FIXED['target_token_presentations']==225840
    assert subject.FIXED['additional_object_parameters']==576 and subject.FIXED['selection_unchanged']
    assert not any(subject.FALSE.values())


@pytest.mark.parametrize('field,value',[('optimizer_steps',170),('temperature',1),('fixed_encoder_context_tokens',1024),
    ('source_value_weight',0.),('selection_unchanged',False),('additional_object_parameters',0),('dimensions',[384])])
def test_fixed_recipe_cannot_be_weakened(field,value):
    changed=deepcopy(subject.FIXED);changed[field]=value
    with pytest.raises(ValueError):subject.validate_plan(changed)


def test_real_archived_baseline_schema_and_only_declared_clock_fields_excluded():
    path=P/'workspace/test-logs/decoder-four-width-20261004/training-r1/results/8-source-head-lr10-1729/training.json'
    if not path.is_file():pytest.skip('local historical evidence not installed')
    report=json.loads(path.read_bytes());subject.validate_report(report,subject.ARMS[0])
    altered=deepcopy(report);altered['elapsed_seconds']+=1
    for update in altered['committed_updates']:
        receipt=update['generated_boundary'];receipt['elapsed_seconds']+=1
        receipt['generation']['elapsed_seconds']+=1;receipt['collection_sha256']='0'*64
    assert subject.comparable(report)==subject.comparable(altered)
    altered['committed_updates'][0]['objective']+=.1
    assert subject.comparable(report)!=subject.comparable(altered)


def test_bound_input_requires_hash_and_inventory(tmp_path):
    path=tmp_path/'input.json';path.write_text('{"a":1}')
    manifest={'inputs':{str(path):subject.sha(path)}}
    assert subject.bound_json(manifest,path)=={'a':1}
    path.write_text('{"a":2}')
    with pytest.raises(ValueError):subject.bound_json(manifest,path)
    with pytest.raises(ValueError):subject.bound_json({'inputs':{}},path)
