"""The diagnostic runner must keep data and the fixed comparison bound."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest


PATH = Path(__file__).resolve().parents[5]/'scripts/ops/autoencoder/benchmark_source_field_readout_probe.py'
SPEC = importlib.util.spec_from_file_location('_field_probe_runner_tests', PATH)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def plan():
    return dict(deepcopy(runner.FIXED), input_sha256={})


def test_plan_is_explicit_and_rejects_a_second_inferred_recipe():
    runner.validate_plan(plan())
    for changed in [dict(plan(), dimension=384), dict(plan(), updates=2000),
                    dict(plan(), learning_rates=[.001, .02]), dict(plan(), extra_recipe=True),
                    dict(plan(), training_occurrences=113)]:
        with pytest.raises(ValueError):
            runner.validate_plan(changed)


@pytest.mark.parametrize('key,value', [('qualified',True),('lake_executed',True),
    ('validation_selection',True),('full_vocabulary_retained',False),
    ('worker_count',True),('metric_disk_cache_used',True),('field_coefficient',float('nan'))])
def test_plan_rejects_authority_data_exposure_and_numerical_changes(key, value):
    with pytest.raises(ValueError):
        runner.validate_plan(dict(plan(), **{key:value}))


def test_input_must_be_hash_bound_before_deserialization(tmp_path):
    path = tmp_path/'input.json'
    path.write_text(json.dumps({'split':'train'}))
    pins = {str(path.resolve()):runner.sha(path)}
    assert runner.bound_json(path, pins) == {'split':'train'}
    path.write_text(json.dumps({'split':'validation'}))
    with pytest.raises(ValueError, match='unbound probe input'):
        runner.bound_json(path, pins)
    with pytest.raises(ValueError, match='unbound probe input'):
        runner.bound_json(path, {})


def test_saved_attempt_cannot_be_overwritten(tmp_path):
    path = tmp_path/'attempt'/'report.json'
    ref = runner.save(path, {'complete':True, 'admitted':False})
    assert ref['sha256'] == runner.sha(path)
    old = path.read_bytes()
    with pytest.raises(FileExistsError):
        runner.save(path, {'admitted':True})
    assert path.read_bytes() == old
