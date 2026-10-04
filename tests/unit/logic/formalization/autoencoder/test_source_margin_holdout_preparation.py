"""The source preparation command binds its policy and input files before use."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

PATH=Path(__file__).resolve().parents[5]/'scripts/ops/autoencoder/prepare_source_margin_holdout.py'
SPEC=importlib.util.spec_from_file_location('_fresh_source_preparation_test',PATH)
subject=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(subject)


@pytest.mark.parametrize('key,value',[
    ('dimensions',[384]),('samples',47),('max_tokens',1024),('max_tokens',512.),
    ('max_seconds_per_width',float('inf')),('batch_size',8),('weights_downloaded',True),
    ('test_used_for_selection',True),('source_only_encoder_inputs',False),('temperature',1),
])
def test_policy_cannot_silently_change_context_or_holdout_boundary(key,value):
    plan=deepcopy(subject.FIXED);subject.validate_plan(plan);plan[key]=value
    with pytest.raises(ValueError,match='policy'):
        subject.validate_plan(plan)


def test_bound_input_rejects_changed_and_unregistered_sources(tmp_path):
    path=tmp_path/'source.json';path.write_text(json.dumps({'rows':[]}))
    manifest={'inputs':{str(path):subject.sha(path)}}
    assert subject.bound_json(manifest,path)=={'rows':[]}
    path.write_text(json.dumps({'rows':['changed']}))
    with pytest.raises(ValueError,match='unbound or changed'):
        subject.bound_json(manifest,path)
    with pytest.raises(ValueError,match='unbound or changed'):
        subject.bound_json({'inputs':{}},path)
