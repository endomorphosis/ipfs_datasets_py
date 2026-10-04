"""Profile isolation and reference-barrier controls; no model execution."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

P = Path(__file__).resolve().parents[5]


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


adapter = module(P/'scripts/ops/autoencoder/evaluate_paraphrase_modality_styles.py', '_test_modality_style_adapter')


def test_profile_reuses_all_gates_without_mutating_default():
    base = module(P/adapter.BASE_FILE, '_test_default_style_owner')
    before = deepcopy(base.FIXED)
    left, right = adapter.load_observer(), adapter.load_observer()
    assert left is not right and left.FIXED is not right.FIXED
    assert base.FIXED == before
    assert base.ARMS == ('original-only', 'half-paraphrases')
    assert base.RESULT_SCHEMA == 'training-mixture-exposed-v3-results/v1'
    assert left.TRAINER == adapter.TRAINER and left.ARMS == adapter.ARMS
    assert left.RESULT_SCHEMA == adapter.RESULT_SCHEMA
    assert left.FIXED == dict(before, schema=adapter.PLAN_SCHEMA, arms=list(adapter.ARMS))
    for name in ('execute', 'verify_predictions', 'load_references', 'restore_before_deadline'):
        assert getattr(left, name).__code__.co_code == getattr(base, name).__code__.co_code
        assert getattr(left, name).__globals__ is left.__dict__
    left.FIXED['temperature'] = 1
    assert right.FIXED['temperature'] == base.FIXED['temperature'] == 0


def test_changed_shared_source_refuses_before_execution(tmp_path):
    source = tmp_path/'changed.py'
    source.write_text('raise RuntimeError("must not execute an unpinned module")\n')
    with pytest.raises(ValueError, match='source pin differs'):
        adapter.load_observer(base_path=source)


@pytest.mark.parametrize('change', [dict(arms=['original-only','half-paraphrases']),
    dict(dimensions=[384]), dict(roles=['selected']), dict(temperature=1),
    dict(context_tokens=1024), dict(used_for_selection=True), dict(fresh_holdout=True),
    dict(all_predictions_before_reference_load=False), dict(panel_count=4)])
def test_configured_recipe_refuses_weakened_gates(change):
    observer = adapter.load_observer()
    observer.validate_plan(deepcopy(observer.FIXED))
    with pytest.raises(ValueError, match='recipe differs'):
        observer.validate_plan(dict(observer.FIXED, **change))


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def predictions(tmp_path, observer):
    rows = [dict(id=f'source:{i}', source_text=f'Source {i}.', input=[float(i)]) for i in range(48)]
    lanes = {d:dict(fresh_rows=rows,fresh_contexts={}) for d in (384,768)}
    runs, records = {}, []
    for d in (384,768):
        for arm in adapter.ARMS:
            run = dict(states={role:dict(tensor_sha256=digest([d,arm,role])) for role in observer.ROLES})
            runs[d,arm] = run
            for role in observer.ROLES:
                panel = dict(complete=True,model_tensor_sha256=run['states'][role]['tensor_sha256'],
                    source_rows_sha256=digest(rows),source_contexts_sha256=digest({}),
                    predictions=[dict(id=r['id'],token_ids=[1,2]) for r in rows],
                    generation_reference_access=False,greedy_passes_per_row=1,
                    generation_temperature=0,max_target_tokens=512)
                path = tmp_path/f'{d}-{arm}-{role}.json'
                path.write_text(json.dumps(panel))
                records.append(dict(dimension=d,arm=arm,role=role,state_ref=run['states'][role],
                    predictions_ref=dict(path=str(path),sha256=observer.sha(path))))
    return records,runs,lanes


def test_eight_new_endpoints_pass_prediction_barrier(tmp_path):
    observer = adapter.load_observer()
    records,runs,lanes = predictions(tmp_path,observer)
    observer.verify_predictions(records,runs,lanes,digest)


@pytest.mark.parametrize('mutation', ['missing','old_arm','state','source','target_access','temperature','file'])
def test_reference_barrier_still_precedes_label_access(tmp_path,monkeypatch,mutation):
    observer = adapter.load_observer()
    records,runs,lanes = predictions(tmp_path,observer)
    if mutation == 'missing':records.pop()
    elif mutation == 'old_arm':records[0]['arm']='original-only'
    elif mutation == 'state':records[0]['state_ref']={'tensor_sha256':'wrong'}
    else:
        record = records[0];path=Path(record['predictions_ref']['path']);panel=json.loads(path.read_bytes())
        if mutation == 'source':panel['source_rows_sha256']='wrong'
        elif mutation == 'target_access':panel['generation_reference_access']=True
        elif mutation == 'temperature':panel['generation_temperature']=1
        path.write_text(json.dumps(panel)+'\n')
        if mutation != 'file':record['predictions_ref']['sha256']=observer.sha(path)
    monkeypatch.setattr(observer,'bound',lambda *a:pytest.fail('references opened before valid predictions'))
    with pytest.raises(ValueError):observer.load_references({},records,runs,lanes,{},digest)
